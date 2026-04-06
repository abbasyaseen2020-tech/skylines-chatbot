# -*- coding: utf-8 -*-
"""
Sky Lines Real Estate - AI Sales Agent
=======================================
Facebook Messenger + WhatsApp + Facebook Comments
Auto-detects OpenAI or Anthropic API
"""

import os
import re
import logging
import time
import random
import requests
from datetime import datetime
from collections import defaultdict
from flask import Flask, request, jsonify

# ============================================
# CONFIGURATION
# ============================================
app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "skylines_bot_verify_2026")

# ---- AI Provider Auto-Detection ----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

if OPENAI_API_KEY:
    AI_PROVIDER = "openai"
    _DEFAULT_MODEL = "gpt-4.1-mini"
elif ANTHROPIC_API_KEY:
    AI_PROVIDER = "anthropic"
    _DEFAULT_MODEL = "claude-sonnet-4-20250514"
else:
    AI_PROVIDER = "fallback"
    _DEFAULT_MODEL = "none"

AI_MODEL = os.getenv("AI_MODEL", _DEFAULT_MODEL)

GRAPH_API_URL = "https://graph.facebook.com/v19.0"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2025-01-01"

from knowledge_base import (
    get_system_prompt, COMMENT_KEYWORDS, COMPANY_INFO,
    format_projects_for_search,
    EMOJI_POSITIVE, EMOJI_RESPONSES, THANK_WORDS
)

# ============================================
# DATA STORES (in-memory)
# ============================================
leads_db = []
conversation_history = defaultdict(list)
user_data = {}
phone_requested = {}
MAX_HISTORY = 20

# ============================================
# DUPLICATE MESSAGE PREVENTION
# ============================================
_processed_messages = {}
_processed_comments = {}
DEDUP_TTL = 60


def is_duplicate_message(msg_id):
    now = time.time()
    for k in [k for k, v in _processed_messages.items() if now - v > DEDUP_TTL]:
        del _processed_messages[k]
    if msg_id in _processed_messages:
        return True
    _processed_messages[msg_id] = now
    return False


def is_duplicate_comment(comment_id):
    now = time.time()
    for k in [k for k, v in _processed_comments.items() if now - v > DEDUP_TTL]:
        del _processed_comments[k]
    if comment_id in _processed_comments:
        return True
    _processed_comments[comment_id] = now
    return False


# ============================================
# SANITIZE HISTORY (alternating user/assistant)
# ============================================
def sanitize_history(history):
    if not history:
        return []
    sanitized = []
    for msg in history:
        role = msg.get("role")
        content = msg.get("content", "").strip()
        if not content:
            continue
        if not sanitized:
            if role == "user":
                sanitized.append(msg)
            continue
        if role == sanitized[-1]["role"]:
            if role == "user":
                sanitized[-1] = {"role": "user", "content": sanitized[-1]["content"] + "\n" + content}
            else:
                sanitized[-1] = msg
        else:
            sanitized.append(msg)
    if sanitized and sanitized[-1]["role"] != "user":
        sanitized.pop()
    return sanitized


# ============================================
# AI API CALLS
# ============================================
def _call_openai(system_prompt, messages, max_tokens):
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": AI_MODEL,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    resp = requests.post(OPENAI_API_URL, headers=headers, json=payload, timeout=25)
    if resp.status_code != 200:
        logger.error(f"OpenAI {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_anthropic(system_prompt, messages, max_tokens):
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": AI_MODEL,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "system": system_prompt,
        "messages": messages,
    }
    resp = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=25)
    if resp.status_code != 200:
        logger.error(f"Anthropic {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def _call_ai(system_prompt, messages, max_tokens=150):
    if AI_PROVIDER == "openai":
        return _call_openai(system_prompt, messages, max_tokens)
    elif AI_PROVIDER == "anthropic":
        return _call_anthropic(system_prompt, messages, max_tokens)
    return None


# ============================================
# AI AGENT
# ============================================
def ask_ai(user_id, user_message, platform="messenger"):
    if AI_PROVIDER == "fallback":
        logger.warning("No AI API key set — fallback mode")
        return fallback_response(user_message)

    conversation_history[user_id].append({"role": "user", "content": user_message})

    if len(conversation_history[user_id]) > MAX_HISTORY:
        conversation_history[user_id] = conversation_history[user_id][-MAX_HISTORY:]

    clean_history = sanitize_history(conversation_history[user_id])
    if not clean_history:
        clean_history = [{"role": "user", "content": user_message}]

    system_prompt = get_system_prompt()

    # User context
    if user_id in user_data:
        data = user_data[user_id]
        if data.get("name"):
            ctx = f"\n[الاسم: {data['name']}"
            if data.get("phone"):
                ctx += f", التليفون: {data['phone']}"
            if data.get("interest"):
                ctx += f", مهتم بـ: {data['interest']}"
            ctx += "]"
            system_prompt += f"\n\n## العميل الحالي:{ctx}"

    is_first = len(conversation_history[user_id]) <= 1
    msg_count = len(conversation_history[user_id])

    if is_first:
        system_prompt += "\n\n## ⚠️ أول رسالة — رحبي بالعميل كفريق Sky Lines. ممنوع تذكري أي اسم شخصي."
    else:
        system_prompt += "\n\n## ⚠️ محادثة مكملة — ردي مباشر ومختصر."

    has_phone = bool(user_data.get(user_id, {}).get("phone"))
    asked_phone = phone_requested.get(user_id, False)

    if has_phone:
        system_prompt += "\n## العميل ساب رقمه — ماتطلبيش تاني."
    elif asked_phone:
        system_prompt += "\n## ⛔ طلبتي الرقم قبل كده — ممنوع تطلبيه تاني. اديله بيانات الشركة لو عايز يتواصل."
    elif msg_count < 4:
        system_prompt += f"\n## ⛔ رسالة {msg_count} — بدري على طلب الرقم."

    system_prompt += f"\n\n## المنصة: {platform}"
    if platform == "whatsapp":
        system_prompt += "\n(واتساب — ردود أقصر)"

    try:
        ai_response = _call_ai(system_prompt, clean_history, max_tokens=150)
        if not ai_response:
            fb = fallback_response(user_message)
            conversation_history[user_id].append({"role": "assistant", "content": fb})
            return fb

        ai_response = _post_process(user_id, ai_response, is_first)
        conversation_history[user_id].append({"role": "assistant", "content": ai_response})
        extract_user_data(user_id, user_message, ai_response)

        phone_patterns = ["رقم حضرتك", "رقم تليفون", "رقم موبايل", "رقمك",
                          "ابعتلي رقم", "ابعتلنا رقم", "سيب رقمك",
                          "واتساب ولا مكالمة", "يكلمك", "يتواصل مع حضرتك", "نمبرك"]
        if any(p in ai_response for p in phone_patterns):
            phone_requested[user_id] = True

        logger.info(f"[{AI_PROVIDER}] {user_id}: {ai_response[:100]}...")
        return ai_response

    except requests.exceptions.Timeout:
        logger.error(f"{AI_PROVIDER} timeout")
        fb = "عذراً، حصل تأخير بسيط. ممكن تبعت رسالتك تاني؟ 🙏"
        conversation_history[user_id].append({"role": "assistant", "content": fb})
        return fb

    except requests.exceptions.RequestException as e:
        logger.error(f"{AI_PROVIDER} error: {e}")
        fb = fallback_response(user_message)
        conversation_history[user_id].append({"role": "assistant", "content": fb})
        return fb

    except (KeyError, IndexError) as e:
        logger.error(f"API response parse error: {e}")
        fb = fallback_response(user_message)
        conversation_history[user_id].append({"role": "assistant", "content": fb})
        return fb


def ask_ai_comment(comment_text, sender_name):
    if AI_PROVIDER == "fallback":
        return None

    system_prompt = get_system_prompt() + """

## رد على تعليق فيسبوك (عام)
- سطر واحد — 15 كلمة ماكس
- رحبي بالعميل باسمه
- وجهيه يبعتلنا رسالة خاصة
- ممنوع أسعار أو أرقام
- ممنوع تذكري أي اسم شخصي — ردي كفريق Sky Lines
- ممنوع تطلبي رقم تليفون
"""

    try:
        return _call_ai(system_prompt,
                        [{"role": "user", "content": f"العميل {sender_name} علّق: \"{comment_text}\"\nرد مختصر."}],
                        max_tokens=80)
    except Exception as e:
        logger.error(f"Comment AI error: {e}")
        return None


def _post_process(user_id, response, is_first):
    # Always strip the name — never allow it
    response = re.sub(r'أنا\s*أسيل[^.!؟\n]*[.!؟]?\s*', '', response)
    response = re.sub(r'أسيل\s*هنا[^.!؟\n]*[.!؟]?\s*', '', response)
    response = re.sub(r'أسيل\s*من\s*Sky\s*Lines[^.!؟\n]*[.!؟]?\s*', '', response)
    response = re.sub(r'معاكِ?\s*أسيل[^.!؟\n]*[.!؟]?\s*', '', response)
    response = re.sub(r'أسيل', '', response)

    lines = response.strip().split('\n')
    has_card = any('🟢' in l or '💰' in l or '━' in l for l in lines)
    max_lines = 12 if has_card else 5
    if len(lines) > max_lines:
        response = '\n'.join(lines[:max_lines])

    response = re.sub(r'\n{3,}', '\n\n', response).strip()
    return response


def extract_user_data(user_id, user_message, ai_response):
    if user_id not in user_data:
        user_data[user_id] = {}
    text = user_message.strip()

    phone = extract_phone(text)
    if phone:
        user_data[user_id]["phone"] = phone
        if user_data[user_id].get("name"):
            auto_save_lead(user_id)

    history = conversation_history.get(user_id, [])
    if len(history) >= 2:
        prev = history[-2].get("content", "") if history[-2]["role"] == "assistant" else ""
        if any(w in prev for w in ["اسمك", "اسم حضرتك", "نعرف اسمك"]):
            if len(text.split()) <= 4 and not text.startswith("0"):
                user_data[user_id]["name"] = text

    interests = []
    if any(w in text for w in ["شقة", "شقق", "سكني"]):
        interests.append("شقق سكنية")
    if any(w in text for w in ["فيلا", "فيلات"]):
        interests.append("فيلات")
    if any(w in text for w in ["محل", "تجاري"]):
        interests.append("محلات تجارية")
    if any(w in text for w in ["مكتب", "إداري"]):
        interests.append("مكاتب إدارية")
    if interests:
        user_data[user_id]["interest"] = "، ".join(interests)


def extract_phone(text):
    patterns = [r'01[0-9]{9}', r'\+201[0-9]{9}', r'201[0-9]{9}']
    clean = text.replace("-", "").replace(" ", "")
    for p in patterns:
        m = re.search(p, clean)
        if m:
            return m.group()
    return None


def auto_save_lead(user_id):
    data = user_data.get(user_id, {})
    if data.get("name") and data.get("phone"):
        if not any(l.get("phone") == data["phone"] for l in leads_db):
            leads_db.append({
                "name": data["name"], "phone": data["phone"],
                "interest": data.get("interest", "غير محدد"),
                "platform": "auto", "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
            })
            logger.info(f"Lead saved: {data['name']} - {data['phone']}")


def fallback_response(message):
    text = message.lower().strip()
    if any(w in text for w in ["سلام", "هاي", "مرحبا", "صباح", "مساء", "اهلا", "أهلا", "هلو"]):
        return "أهلاً بيك! 🏢 حضرتك بتدور على سكن ولا استثمار؟"
    if any(w in text for w in ["سعر", "كام", "تقسيط", "مقدم", "دفع", "قسط"]):
        return "حضرتك مهتم بأنهي مشروع عشان أفيدك بالأسعار؟ 😊"
    if any(w in text for w in ["مشاريع", "شقة", "شقق", "فيلا", "فيلات", "محل", "مكتب"]):
        return "عندنا مشاريع في بني سويف — سكني وتجاري وإداري. حضرتك بتدور على إيه؟"
    if any(w in text for w in ["حجز", "موعد", "زيارة", "معاينة"]):
        return "تقدر تتواصل معانا على 01055993391 📞 وهنرتب معاك!"
    if any(w in text for w in ["رقم", "تواصل", "تليفون", "واتساب", "فون", "اتصال"]):
        return "📞 01055993391\n🌐 www.skylinesdevelopments.com\nتواصل معانا في أي وقت!"
    return "أهلاً بيك! 🏢 إيه اللي تحب تعرفه عن مشاريعنا؟"


# ============================================
# MESSAGE HANDLER
# ============================================
def handle_message(user_id, message_text, platform="messenger", message_id=None):
    text = message_text.strip()
    if not text:
        return
    if message_id and is_duplicate_message(message_id):
        return
    logger.info(f"[{platform}] {user_id}: {text[:100]}")
    ai_response = ask_ai(user_id, text, platform)
    send_message(user_id, ai_response, platform)


# ============================================
# COMMENT HANDLER
# ============================================
def handle_comment(comment_data):
    comment_id = comment_data.get("comment_id")
    comment_text = comment_data.get("message", "")
    sender_name = comment_data.get("from", {}).get("name", "")
    sender_id = comment_data.get("from", {}).get("id", "")
    verb = comment_data.get("verb", "")
    post_id = comment_data.get("post_id", "")

    if verb != "add":
        return
    if is_duplicate_comment(comment_id):
        return

    page_id = post_id.split("_")[0] if post_id else ""
    if sender_id == page_id:
        return

    is_positive = (
        any(e in comment_text for e in EMOJI_POSITIVE) or
        any(w in comment_text for w in THANK_WORDS)
    )

    if is_positive and not any(k in comment_text for k in COMMENT_KEYWORDS):
        if any(e in comment_text for e in EMOJI_POSITIVE) and len(comment_text.strip()) <= 5:
            resp = random.choice(EMOJI_RESPONSES)
        else:
            resp = f"شكراً ليك يا {sender_name}! نورتنا 🙏❤️"
        reply_to_comment(comment_id, resp)
        return

    if any(k in comment_text for k in COMMENT_KEYWORDS):
        ai_reply = ask_ai_comment(comment_text, sender_name)
        if ai_reply:
            reply_to_comment(comment_id, ai_reply)
        else:
            reply_to_comment(comment_id, f"أهلاً يا {sender_name}! 👋 ابعتلنا رسالة خاصة وهنرد عليك 😊")
        return

    reply_to_comment(comment_id, f"أهلاً يا {sender_name}! 😊 لو محتاج معلومات ابعتلنا رسالة خاصة!")


# ============================================
# SEND FUNCTIONS - MESSENGER
# ============================================
def send_message(user_id, text, platform="messenger"):
    if platform == "whatsapp":
        send_whatsapp_message(user_id, text)
    else:
        send_messenger_message(user_id, text)


def send_messenger_message(recipient_id, text):
    if len(text) > 2000:
        for chunk in split_message(text, 2000):
            _send_messenger_raw(recipient_id, chunk)
            time.sleep(0.5)
    else:
        _send_messenger_raw(recipient_id, text)


def _send_messenger_raw(recipient_id, text):
    url = f"{GRAPH_API_URL}/me/messages"
    payload = {"recipient": {"id": recipient_id}, "message": {"text": text}, "messaging_type": "RESPONSE"}
    try:
        r = requests.post(url, json=payload, params={"access_token": PAGE_ACCESS_TOKEN}, timeout=10)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Messenger send failed: {e}")


def reply_to_comment(comment_id, text):
    url = f"{GRAPH_API_URL}/{comment_id}/comments"
    try:
        r = requests.post(url, data={"message": text}, params={"access_token": PAGE_ACCESS_TOKEN}, timeout=10)
        result = r.json()
        if "error" in result:
            logger.error(f"Comment reply error: {result['error']}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Comment reply failed: {e}")


def send_private_reply(comment_id, text):
    url = f"{GRAPH_API_URL}/me/messages"
    payload = {"recipient": {"comment_id": comment_id}, "message": {"text": text}, "messaging_type": "RESPONSE"}
    try:
        r = requests.post(url, json=payload, params={"access_token": PAGE_ACCESS_TOKEN}, timeout=10)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Private reply failed: {e}")


# ============================================
# SEND FUNCTIONS - WHATSAPP
# ============================================
def send_whatsapp_message(phone_number, text):
    if len(text) > 4000:
        for chunk in split_message(text, 4000):
            _send_whatsapp_raw(phone_number, chunk)
            time.sleep(0.5)
    else:
        _send_whatsapp_raw(phone_number, text)


def _send_whatsapp_raw(phone_number, text):
    url = f"{GRAPH_API_URL}/{WHATSAPP_PHONE_ID}/messages"
    payload = {"messaging_product": "whatsapp", "to": phone_number, "type": "text", "text": {"body": text}}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"WhatsApp send failed: {e}")


# ============================================
# UTILITY
# ============================================
def split_message(text, max_length):
    chunks = []
    while len(text) > max_length:
        split_at = text.rfind('\n', 0, max_length)
        if split_at == -1:
            split_at = text.rfind(' ', 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        chunks.append(text)
    return chunks


# ============================================
# WEBHOOK ROUTES
# ============================================
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verified!")
        return challenge, 200
    return "Verification failed", 403


@app.route("/webhook", methods=["POST"])
def handle_webhook():
    data = request.get_json()
    if data.get("object") == "page":
        for entry in data.get("entry", []):
            for event in entry.get("messaging", []):
                sender_id = event["sender"]["id"]
                msg_id = None
                if "message" in event:
                    message = event["message"]
                    msg_id = message.get("mid")
                    text = message.get("quick_reply", {}).get("payload") or message.get("text", "")
                    if text:
                        handle_message(sender_id, text, "messenger", msg_id)
                elif "postback" in event:
                    handle_message(sender_id, event["postback"]["payload"], "messenger")
            for change in entry.get("changes", []):
                if change.get("field") == "feed" and change["value"].get("item") == "comment":
                    handle_comment(change["value"])
    return "OK", 200


@app.route("/whatsapp-webhook", methods=["GET"])
def verify_whatsapp_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403


@app.route("/whatsapp-webhook", methods=["POST"])
def handle_whatsapp_webhook():
    data = request.get_json()
    if data.get("object") == "whatsapp_business_account":
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "messages":
                    for msg in change["value"].get("messages", []):
                        phone = msg["from"]
                        msg_id = msg.get("id")
                        if msg["type"] == "text":
                            text = msg["text"]["body"]
                        elif msg["type"] == "interactive":
                            interactive = msg.get("interactive", {})
                            text = (interactive.get("list_reply") or interactive.get("button_reply") or {}).get("title", "")
                        else:
                            text = ""
                        if text:
                            handle_message(phone, text, "whatsapp", msg_id)
    return "OK", 200


# ============================================
# API ENDPOINTS
# ============================================
@app.route("/api/leads", methods=["GET"])
def get_leads():
    return jsonify({"leads": leads_db, "total": len(leads_db)})


@app.route("/api/stats", methods=["GET"])
def get_stats():
    return jsonify({
        "total_leads": len(leads_db),
        "active_conversations": len(conversation_history),
        "users_with_data": len(user_data),
    })


@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "running",
        "ai_provider": AI_PROVIDER,
        "ai_model": AI_MODEL,
        "facebook": "configured" if PAGE_ACCESS_TOKEN else "off",
        "whatsapp": "configured" if WHATSAPP_TOKEN else "off",
    })


# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    if AI_PROVIDER == "fallback":
        logger.warning("⚠️ No AI key — set OPENAI_API_KEY or ANTHROPIC_API_KEY")
    else:
        logger.info(f"AI: {AI_PROVIDER} / {AI_MODEL}")
    logger.info(f"Starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)
