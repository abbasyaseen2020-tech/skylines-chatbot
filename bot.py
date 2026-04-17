# -*- coding: utf-8 -*-
"""
Sky Lines Real Estate - AI Sales Agent
=======================================
Facebook Messenger + WhatsApp + Facebook Comments
Auto-detects OpenAI or Anthropic API
"""

import os
import re
import json
import logging
import time
import random
import threading
import requests
from datetime import datetime, timedelta
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
FB_APP_ID = os.getenv("FB_APP_ID", "1158857492390878")
FB_APP_SECRET = os.getenv("FB_APP_SECRET", "")

# ---- Telegram Notifications ----
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else ""

# ---- Persistent Storage ----
DATA_DIR = os.getenv("DATA_DIR", "/tmp/skylines_data")
os.makedirs(DATA_DIR, exist_ok=True)

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
# PERSISTENT DATA STORES
# ============================================
MAX_HISTORY = 20


def _load_json(filename, default=None):
    path = os.path.join(DATA_DIR, filename)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Load {filename} error: {e}")
    return default if default is not None else {}


def _save_json(filename, data):
    path = os.path.join(DATA_DIR, filename)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Save {filename} error: {e}")


# Load persisted data on startup
leads_db = _load_json("leads.json", [])
user_data = _load_json("user_data.json", {})
phone_requested = _load_json("phone_requested.json", {})
conversation_history = defaultdict(list, _load_json("conversations.json", {}))
follow_up_tracker = _load_json("follow_up.json", {})


def save_leads():
    _save_json("leads.json", leads_db)


def save_user_data():
    _save_json("user_data.json", user_data)


def save_conversations():
    _save_json("conversations.json", dict(conversation_history))


def save_follow_up():
    _save_json("follow_up.json", follow_up_tracker)

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
# TELEGRAM NOTIFICATIONS
# ============================================
def send_telegram(text, parse_mode="HTML"):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — skipping notification")
        return False
    try:
        r = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": parse_mode,
        }, timeout=10)
        if r.status_code == 200:
            logger.info(f"📲 Telegram sent: {text[:50]}...")
            return True
        else:
            logger.error(f"📲 Telegram error: {r.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"📲 Telegram exception: {e}")
        return False


def notify_new_lead(lead_data):
    name = lead_data.get("name", "غير معروف")
    phone = lead_data.get("phone", "—")
    interest = lead_data.get("interest", "غير محدد")
    platform = lead_data.get("platform", "messenger")
    ts = lead_data.get("timestamp", "")
    msg = (
        f"🔥 <b>ليد جديد — Sky Lines!</b>\n\n"
        f"👤 الاسم: {name}\n"
        f"📱 الرقم: {phone}\n"
        f"🏢 مهتم بـ: {interest}\n"
        f"📍 المنصة: {platform}\n"
        f"🕐 الوقت: {ts}"
    )
    send_telegram(msg)


def notify_new_conversation(user_id, first_message, platform):
    msg = (
        f"💬 <b>محادثة جديدة!</b>\n\n"
        f"🆔 {user_id}\n"
        f"📍 {platform}\n"
        f"💭 {first_message[:100]}"
    )
    send_telegram(msg)


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


def _call_ai(system_prompt, messages, max_tokens=350):
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
        ai_response = _call_ai(system_prompt, clean_history, max_tokens=350)
        if not ai_response:
            fb = fallback_response(user_message)
            conversation_history[user_id].append({"role": "assistant", "content": fb})
            return fb

        ai_response = _post_process(user_id, ai_response, is_first)
        conversation_history[user_id].append({"role": "assistant", "content": ai_response})
        extract_user_data(user_id, user_message, ai_response)

        # Track for follow-up
        follow_up_tracker[user_id] = {
            "last_msg_time": datetime.now().isoformat(),
            "platform": platform,
            "followed_up": False,
            "contacted": False,
        }
        save_follow_up()
        save_conversations()

        phone_patterns = ["رقم حضرتك", "رقم تليفون", "رقم موبايل", "رقمك",
                          "ابعتلي رقم", "ابعتلنا رقم", "سيب رقمك",
                          "واتساب ولا مكالمة", "يكلمك", "يتواصل مع حضرتك", "نمبرك"]
        if any(p in ai_response for p in phone_patterns):
            phone_requested[user_id] = True
            _save_json("phone_requested.json", phone_requested)

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
    has_details = any(c in l for l in lines for c in ['📐', '💰', '💵', '📅', '📍', '🏢', '🟢'])
    max_lines = 15 if has_details else 10
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
    phone = data.get("phone")
    if not phone:
        return
    if any(l.get("phone") == phone for l in leads_db):
        return
    lead = {
        "name": data.get("name", "غير معروف"),
        "phone": phone,
        "interest": data.get("interest", "غير محدد"),
        "platform": "auto",
        "timestamp": datetime.now().isoformat(),
        "user_id": user_id,
    }
    leads_db.append(lead)
    save_leads()
    save_user_data()
    logger.info(f"✅ Lead saved: {lead['name']} - {phone}")
    notify_new_lead(lead)


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
        return "📞 01055993391\n📧 info@skylinesdevelopments.com\n🌐 www.skylinesdevelopments.com\nتواصل معانا في أي وقت!"
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
    is_new = user_id not in conversation_history or len(conversation_history[user_id]) == 0
    ai_response = ask_ai(user_id, text, platform)
    send_message(user_id, ai_response, platform)
    if is_new:
        notify_new_conversation(user_id, text, platform)


# ============================================
# COMMENT HANDLER
# ============================================
def handle_comment(comment_data):
    logger.info(f"📝 Comment webhook received: {comment_data}")

    comment_id = comment_data.get("comment_id")
    comment_text = comment_data.get("message", "")
    sender_name = comment_data.get("from", {}).get("name", "")
    sender_id = comment_data.get("from", {}).get("id", "")
    verb = comment_data.get("verb", "")
    post_id = comment_data.get("post_id", "")

    logger.info(f"📝 Comment details: id={comment_id}, from={sender_name} ({sender_id}), verb={verb}, text='{comment_text[:50]}'")

    if verb != "add":
        logger.info(f"📝 Skipping comment — verb is '{verb}', not 'add'")
        return
    if not comment_id:
        logger.error("📝 ERROR: comment_id is None/empty!")
        return
    if is_duplicate_comment(comment_id):
        logger.info(f"📝 Skipping duplicate comment: {comment_id}")
        return

    page_id = post_id.split("_")[0] if post_id else ""
    if sender_id == page_id:
        logger.info(f"📝 Skipping self-comment from page")
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
        logger.info(f"📝 Replying to positive comment: {resp[:50]}")
        reply_to_comment(comment_id, resp)
        send_private_reply(comment_id, WELCOME_DM)
        return

    if any(k in comment_text for k in COMMENT_KEYWORDS):
        ai_reply = ask_ai_comment(comment_text, sender_name)
        if ai_reply:
            logger.info(f"📝 Replying with AI response: {ai_reply[:50]}")
            reply_to_comment(comment_id, ai_reply)
        else:
            logger.info(f"📝 AI failed, using default reply")
            reply_to_comment(comment_id, f"أهلاً يا {sender_name}! 👋 ابعتلنا رسالة خاصة وهنرد عليك 😊")
        send_private_reply(comment_id, WELCOME_DM)
        return

    logger.info(f"📝 Default reply to comment")
    reply_to_comment(comment_id, f"أهلاً يا {sender_name}! 😊 لو محتاج معلومات ابعتلنا رسالة خاصة!")
    send_private_reply(comment_id, WELCOME_DM)


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
    logger.info(f"💬 Replying to comment {comment_id}: {text[:50]}...")
    logger.info(f"💬 URL: {url}")
    logger.info(f"💬 Token preview: {PAGE_ACCESS_TOKEN[:20]}..." if PAGE_ACCESS_TOKEN else "💬 NO TOKEN!")
    try:
        r = requests.post(url, data={"message": text}, params={"access_token": PAGE_ACCESS_TOKEN}, timeout=10)
        logger.info(f"💬 Response status: {r.status_code}")
        logger.info(f"💬 Response body: {r.text[:500]}")
        result = r.json()
        if "error" in result:
            error = result["error"]
            logger.error(f"💬 Comment reply ERROR: code={error.get('code')}, subcode={error.get('error_subcode')}, type={error.get('type')}, msg={error.get('message')}")
            # If permission error, try alternative approach
            if error.get("code") in [10, 200, 190]:
                logger.info(f"💬 Permission/auth error — check pages_manage_engagement permission")
            return False
        else:
            logger.info(f"💬 Comment reply SUCCESS: {result}")
            return True
    except Exception as e:
        logger.error(f"💬 Comment reply EXCEPTION: {type(e).__name__}: {e}")
        return False


def send_private_reply(comment_id, text):
    url = f"{GRAPH_API_URL}/me/messages"
    payload = {"recipient": {"comment_id": comment_id}, "message": {"text": text}, "messaging_type": "RESPONSE"}
    logger.info(f"📩 Sending private DM for comment {comment_id}")
    try:
        r = requests.post(url, json=payload, params={"access_token": PAGE_ACCESS_TOKEN}, timeout=10)
        result = r.json()
        if "error" in result:
            logger.error(f"📩 Private reply ERROR: {result['error']}")
        else:
            logger.info(f"📩 Private reply SUCCESS")
    except requests.exceptions.RequestException as e:
        logger.error(f"📩 Private reply FAILED: {e}")


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
                logger.info(f"🔔 Webhook change: field={change.get('field')}, item={change.get('value', {}).get('item')}")
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
        "telegram": "configured" if (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID) else "off",
        "persistent_storage": DATA_DIR,
        "leads_count": len(leads_db),
        "active_users": len(user_data),
    })


@app.route("/api/telegram-test", methods=["GET"])
def telegram_test():
    """Test Telegram notification."""
    if not TELEGRAM_BOT_TOKEN:
        return jsonify({"error": "TELEGRAM_BOT_TOKEN not set", "status": "❌"}), 400
    if not TELEGRAM_CHAT_ID:
        return jsonify({"error": "TELEGRAM_CHAT_ID not set", "status": "❌"}), 400

    sent = send_telegram(
        "🎉 <b>Telegram Bot متصل بنجاح!</b>\n\n"
        "✅ بوت سكاي لاينز جاهز لإرسال الإشعارات\n"
        "📊 هتوصلك تقارير يومية الساعة 9 م\n"
        "🔥 كل ليد جديد → نوتيفيكيشن فوري"
    )
    return jsonify({
        "status": "✅ Sent" if sent else "❌ Failed",
        "bot_token_preview": TELEGRAM_BOT_TOKEN[:15] + "...",
        "chat_id": TELEGRAM_CHAT_ID,
    })


@app.route("/api/debug-permissions", methods=["GET"])
def debug_permissions():
    """Check what permissions the current token has."""
    if not PAGE_ACCESS_TOKEN:
        return jsonify({"error": "No PAGE_ACCESS_TOKEN"}), 400
    try:
        # Check token permissions
        r = requests.get(
            f"{GRAPH_API_URL}/me/permissions",
            params={"access_token": PAGE_ACCESS_TOKEN},
            timeout=10
        )
        perms = r.json()

        # Check token info
        r2 = requests.get(
            f"https://graph.facebook.com/debug_token",
            params={"input_token": PAGE_ACCESS_TOKEN, "access_token": PAGE_ACCESS_TOKEN},
            timeout=10
        )
        token_info = r2.json()

        return jsonify({
            "permissions": perms,
            "token_info": token_info,
            "token_preview": PAGE_ACCESS_TOKEN[:20] + "...",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================
# PAGE SUBSCRIPTION (for comment auto-replies)
# ============================================
def subscribe_page_feed():
    """Subscribe the page to 'feed' and 'messages' webhooks."""
    if not PAGE_ACCESS_TOKEN:
        logger.warning("No PAGE_ACCESS_TOKEN — skipping feed subscription")
        return {"success": False, "error": "No PAGE_ACCESS_TOKEN"}
    url = f"{GRAPH_API_URL}/me/subscribed_apps"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    payload = {"subscribed_fields": "feed,messages"}
    try:
        r = requests.post(url, params=params, data=payload, timeout=10)
        result = r.json()
        if result.get("success"):
            logger.info("✅ Page subscribed to feed + messages")
            return {"success": True}
        else:
            logger.error(f"Subscribe failed: {result}")
            return {"success": False, "error": result}
    except requests.exceptions.RequestException as e:
        logger.error(f"Subscribe error: {e}")
        return {"success": False, "error": str(e)}


def check_subscription_status():
    """Check what fields the page is currently subscribed to."""
    if not PAGE_ACCESS_TOKEN:
        return {"error": "No PAGE_ACCESS_TOKEN"}
    try:
        # Get page info
        page_resp = requests.get(
            f"{GRAPH_API_URL}/me",
            params={"access_token": PAGE_ACCESS_TOKEN, "fields": "id,name"},
            timeout=10
        )
        page_info = page_resp.json()

        # Get current subscriptions
        sub_resp = requests.get(
            f"{GRAPH_API_URL}/{page_info.get('id', 'me')}/subscribed_apps",
            params={"access_token": PAGE_ACCESS_TOKEN},
            timeout=10
        )
        sub_info = sub_resp.json()

        return {
            "page": page_info,
            "subscriptions": sub_info,
        }
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


@app.route("/api/subscribe", methods=["GET", "POST"])
def api_subscribe():
    """Check subscription status (GET) or subscribe (POST/GET with ?action=subscribe)."""
    action = request.args.get("action", "")

    if request.method == "POST" or action == "subscribe":
        sub_result = subscribe_page_feed()
        status = check_subscription_status()
        return jsonify({"subscribe_result": sub_result, "current_status": status})

    # GET — just show current status
    status = check_subscription_status()
    return jsonify({"current_status": status})


@app.route("/api/exchange-token", methods=["GET", "POST"])
def exchange_token():
    """
    Exchange a short-lived token for a PERMANENT Page Access Token.
    Usage: /api/exchange-token?token=SHORT_LIVED_TOKEN

    Steps:
    1. Exchange short-lived User Token → Long-lived User Token
    2. Use long-lived User Token → Get permanent Page Token
    3. Update PAGE_ACCESS_TOKEN in memory + re-subscribe
    """
    global PAGE_ACCESS_TOKEN

    short_token = request.args.get("token") or request.form.get("token")
    if not short_token:
        return jsonify({
            "error": "Missing 'token' parameter",
            "usage": "GET /api/exchange-token?token=YOUR_SHORT_LIVED_TOKEN",
            "instructions": [
                "1. Go to https://developers.facebook.com/tools/explorer/",
                "2. Select your App (n8nSetup)",
                "3. Click 'Generate Access Token' with permissions: pages_manage_metadata, pages_messaging, pages_manage_engagement, pages_read_engagement",
                "4. Copy the token and paste it in the URL above",
            ]
        }), 400

    if not FB_APP_SECRET:
        return jsonify({
            "error": "FB_APP_SECRET not set",
            "fix": "Add FB_APP_SECRET environment variable on Railway"
        }), 500

    try:
        # Step 1: Exchange short-lived → long-lived User Token
        logger.info("🔄 Step 1: Exchanging short-lived token for long-lived...")
        exchange_resp = requests.get(
            f"{GRAPH_API_URL}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": FB_APP_ID,
                "client_secret": FB_APP_SECRET,
                "fb_exchange_token": short_token
            },
            timeout=15
        )
        exchange_data = exchange_resp.json()

        if "error" in exchange_data:
            return jsonify({
                "step": "1 - Exchange for long-lived token",
                "error": exchange_data["error"]
            }), 400

        long_lived_user_token = exchange_data.get("access_token")
        expires_in = exchange_data.get("expires_in", "unknown")
        logger.info(f"✅ Got long-lived user token (expires_in: {expires_in}s)")

        # Step 2: Get permanent Page Access Token
        logger.info("🔄 Step 2: Getting permanent Page Access Token...")
        pages_resp = requests.get(
            f"{GRAPH_API_URL}/me/accounts",
            params={"access_token": long_lived_user_token},
            timeout=15
        )
        pages_data = pages_resp.json()

        if "error" in pages_data:
            return jsonify({
                "step": "2 - Get page token",
                "error": pages_data["error"],
                "long_lived_user_token": long_lived_user_token[:20] + "..."
            }), 400

        # Find the Sky Lines page
        pages = pages_data.get("data", [])
        page_token = None
        page_name = None
        for page in pages:
            if page.get("id") == "106168341445922":
                page_token = page.get("access_token")
                page_name = page.get("name")
                break

        # If not found by ID, take the first page
        if not page_token and pages:
            page_token = pages[0].get("access_token")
            page_name = pages[0].get("name")

        if not page_token:
            return jsonify({
                "step": "2 - No page found",
                "error": "No pages found for this user",
                "pages_data": pages_data
            }), 400

        # Step 3: Update in memory and re-subscribe
        PAGE_ACCESS_TOKEN = page_token
        logger.info(f"✅ Got permanent Page Token for: {page_name}")

        # Re-subscribe with new token
        sub_result = subscribe_page_feed()
        logger.info(f"🔄 Re-subscription result: {sub_result}")

        return jsonify({
            "success": True,
            "message": f"✅ Permanent Page Token obtained for '{page_name}'!",
            "page_name": page_name,
            "token_preview": page_token[:20] + "...",
            "permanent_token": page_token,
            "subscription": sub_result,
            "next_step": "⚠️ IMPORTANT: Copy the 'permanent_token' value and update PAGE_ACCESS_TOKEN on Railway to persist across restarts!"
        })

    except requests.exceptions.RequestException as e:
        logger.error(f"Token exchange error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/diagnose", methods=["GET"])
def diagnose():
    """Full diagnostic — open in browser to see everything."""
    results = {"timestamp": datetime.now().isoformat()}

    # 1. AI Provider
    results["ai"] = {
        "provider": AI_PROVIDER,
        "model": AI_MODEL,
        "status": "✅ OK" if AI_PROVIDER != "fallback" else "❌ No API key",
    }

    # 2. Facebook Token
    results["facebook_token"] = "✅ Set" if PAGE_ACCESS_TOKEN else "❌ Missing"

    # 3. Page Info
    if PAGE_ACCESS_TOKEN:
        try:
            page_resp = requests.get(
                f"{GRAPH_API_URL}/me",
                params={"access_token": PAGE_ACCESS_TOKEN, "fields": "id,name"},
                timeout=10
            )
            page_data = page_resp.json()
            if "error" in page_data:
                results["page"] = {"status": "❌ Token Error", "error": page_data["error"]}
            else:
                results["page"] = {"status": "✅ OK", "id": page_data.get("id"), "name": page_data.get("name")}
        except Exception as e:
            results["page"] = {"status": "❌ Error", "error": str(e)}

        # 4. Subscriptions
        try:
            page_id = page_data.get("id", "me") if "page_data" in dir() else "me"
            sub_resp = requests.get(
                f"{GRAPH_API_URL}/{page_id}/subscribed_apps",
                params={"access_token": PAGE_ACCESS_TOKEN},
                timeout=10
            )
            sub_data = sub_resp.json()
            if "error" in sub_data:
                results["subscriptions"] = {"status": "❌ Error", "error": sub_data["error"]}
            else:
                apps = sub_data.get("data", [])
                if apps:
                    for a in apps:
                        fields = a.get("subscribed_fields", [])
                        has_feed = "feed" in fields
                        has_messages = "messages" in fields
                        results["subscriptions"] = {
                            "status": "✅ OK" if has_feed else "⚠️ feed missing",
                            "app": a.get("name", a.get("id")),
                            "fields": fields,
                            "feed": "✅" if has_feed else "❌ MISSING — this is why comments don't work",
                            "messages": "✅" if has_messages else "❌",
                        }
                else:
                    results["subscriptions"] = {"status": "❌ No apps subscribed", "data": sub_data}

            # 5. Try to subscribe now
            sub_result = subscribe_page_feed()
            results["auto_fix"] = sub_result

            # 6. Re-check after fix
            sub_resp2 = requests.get(
                f"{GRAPH_API_URL}/{page_id}/subscribed_apps",
                params={"access_token": PAGE_ACCESS_TOKEN},
                timeout=10
            )
            sub_data2 = sub_resp2.json()
            apps2 = sub_data2.get("data", [])
            if apps2:
                fields2 = apps2[0].get("subscribed_fields", [])
                results["after_fix"] = {
                    "fields": fields2,
                    "feed": "✅" if "feed" in fields2 else "❌ Still missing — need to enable in Facebook App Dashboard",
                }

        except Exception as e:
            results["subscriptions"] = {"status": "❌ Error", "error": str(e)}

    # 7. Recent comments test
    if PAGE_ACCESS_TOKEN:
        try:
            posts_resp = requests.get(
                f"{GRAPH_API_URL}/me/posts",
                params={"access_token": PAGE_ACCESS_TOKEN, "fields": "id,message,created_time", "limit": 3},
                timeout=10
            )
            posts_data = posts_resp.json()
            if "error" in posts_data:
                results["recent_posts"] = {"status": "❌ Error", "error": posts_data["error"]}
            else:
                post_summaries = []
                for p in posts_data.get("data", []):
                    c_resp = requests.get(
                        f"{GRAPH_API_URL}/{p['id']}/comments",
                        params={"access_token": PAGE_ACCESS_TOKEN, "fields": "id,from,message", "limit": 5},
                        timeout=10
                    )
                    c_data = c_resp.json()
                    post_summaries.append({
                        "post_id": p["id"],
                        "post_text": (p.get("message") or "")[:50],
                        "comments_count": len(c_data.get("data", [])),
                    })
                results["recent_posts"] = {"status": "✅ Can read posts", "posts": post_summaries}
        except Exception as e:
            results["recent_posts"] = {"status": "❌ Error", "error": str(e)}

    return jsonify(results)


# ============================================
# REPLY TO OLD COMMENTS
# ============================================
WELCOME_DM = (
    "أهلاً بيك! 😊\n"
    "أنا المساعد الذكي لشركة Sky Lines\n"
    "ابعتلي استفسارك وهرد عليك فوراً! 🏢"
)


@app.route("/api/reply-old-comments", methods=["GET", "POST"])
def reply_old_comments():
    """Fetch recent posts and reply to unanswered comments + send welcome DM."""
    if not PAGE_ACCESS_TOKEN:
        return jsonify({"error": "No PAGE_ACCESS_TOKEN"}), 400

    days = int(request.args.get("days", 3))
    dry_run = request.args.get("dry_run", "false").lower() == "true"
    since = int(time.time()) - (days * 86400)

    replied = 0
    dms_sent = 0
    skipped = 0
    errors = 0

    try:
        # Get page posts
        posts_url = f"{GRAPH_API_URL}/me/posts"
        posts_params = {"access_token": PAGE_ACCESS_TOKEN, "fields": "id,created_time", "since": since, "limit": 50}
        posts_resp = requests.get(posts_url, params=posts_params, timeout=15)
        posts_data = posts_resp.json()

        page_id_resp = requests.get(f"{GRAPH_API_URL}/me", params={"access_token": PAGE_ACCESS_TOKEN, "fields": "id"}, timeout=10)
        page_id = page_id_resp.json().get("id", "")

        for post in posts_data.get("data", []):
            post_id = post["id"]

            # Get comments on this post
            comments_url = f"{GRAPH_API_URL}/{post_id}/comments"
            comments_params = {"access_token": PAGE_ACCESS_TOKEN, "fields": "id,message,from,created_time", "limit": 100}
            comments_resp = requests.get(comments_url, params=comments_params, timeout=15)
            comments_data = comments_resp.json()

            for comment in comments_data.get("data", []):
                c_id = comment["id"]
                c_from = comment.get("from", {})
                c_sender_id = c_from.get("id", "")
                c_sender_name = c_from.get("name", "")
                c_text = comment.get("message", "")

                # Skip page's own comments
                if c_sender_id == page_id:
                    skipped += 1
                    continue

                # Check if already replied (look for page reply in sub-comments)
                replies_url = f"{GRAPH_API_URL}/{c_id}/comments"
                replies_params = {"access_token": PAGE_ACCESS_TOKEN, "fields": "from", "limit": 10}
                replies_resp = requests.get(replies_url, params=replies_params, timeout=10)
                replies_data = replies_resp.json()

                already_replied = any(r.get("from", {}).get("id") == page_id for r in replies_data.get("data", []))
                if already_replied:
                    skipped += 1
                    continue

                # Generate reply
                if dry_run:
                    replied += 1
                    logger.info(f"[DRY RUN] Would reply to {c_id}: {c_text[:50]}")
                    continue

                try:
                    # Use the same comment handling logic
                    is_positive = (
                        any(e in c_text for e in EMOJI_POSITIVE) or
                        any(w in c_text for w in THANK_WORDS)
                    )

                    if is_positive and not any(k in c_text for k in COMMENT_KEYWORDS):
                        if any(e in c_text for e in EMOJI_POSITIVE) and len(c_text.strip()) <= 5:
                            resp = random.choice(EMOJI_RESPONSES)
                        else:
                            resp = f"شكراً ليك يا {c_sender_name}! نورتنا 🙏❤️"
                    elif any(k in c_text for k in COMMENT_KEYWORDS):
                        ai_reply = ask_ai_comment(c_text, c_sender_name)
                        resp = ai_reply or f"أهلاً يا {c_sender_name}! 👋 ابعتلنا رسالة خاصة وهنرد عليك 😊"
                    else:
                        resp = f"أهلاً يا {c_sender_name}! 😊 لو محتاج معلومات ابعتلنا رسالة خاصة!"

                    # 1) Reply on the comment publicly
                    reply_to_comment(c_id, resp)
                    replied += 1

                    # 2) Send welcome DM with company info
                    try:
                        send_private_reply(c_id, WELCOME_DM)
                        dms_sent += 1
                    except Exception as e:
                        logger.warning(f"DM failed for {c_id} (may not be eligible): {e}")

                    time.sleep(1.5)  # Rate limit protection

                except Exception as e:
                    logger.error(f"Reply error for {c_id}: {e}")
                    errors += 1

    except requests.exceptions.RequestException as e:
        logger.error(f"Fetch posts error: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "replied": replied,
        "dms_sent": dms_sent,
        "skipped": skipped,
        "errors": errors,
        "dry_run": dry_run,
        "days": days,
    })


# ============================================
# PAGE CONTENT ANALYTICS
# ============================================
@app.route("/api/videos", methods=["GET"])
def fetch_videos():
    """Fetch all videos from the page with stats."""
    if not PAGE_ACCESS_TOKEN:
        return jsonify({"error": "No PAGE_ACCESS_TOKEN"}), 400
    try:
        r = requests.get(
            f"{GRAPH_API_URL}/me/videos",
            params={
                "access_token": PAGE_ACCESS_TOKEN,
                "fields": "id,title,description,created_time,length,views,likes.summary(true),comments.summary(true),shares",
                "limit": 50
            },
            timeout=20
        )
        data = r.json()
        videos = []
        for v in data.get("data", []):
            videos.append({
                "id": v.get("id"),
                "title": v.get("title", "")[:100],
                "description": v.get("description", "")[:200],
                "created": v.get("created_time"),
                "length_sec": v.get("length"),
                "views": v.get("views"),
                "likes": v.get("likes", {}).get("summary", {}).get("total_count", 0),
                "comments": v.get("comments", {}).get("summary", {}).get("total_count", 0),
                "shares": v.get("shares", {}).get("count", 0),
            })
        return jsonify({"total": len(videos), "videos": videos})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/page-insights", methods=["GET"])
def page_insights():
    """Fetch page insights and stats."""
    if not PAGE_ACCESS_TOKEN:
        return jsonify({"error": "No PAGE_ACCESS_TOKEN"}), 400
    try:
        # Page basic info
        page_r = requests.get(
            f"{GRAPH_API_URL}/me",
            params={
                "access_token": PAGE_ACCESS_TOKEN,
                "fields": "id,name,fan_count,followers_count,talking_about_count"
            },
            timeout=10
        )
        page = page_r.json()

        # Recent posts with engagement
        posts_r = requests.get(
            f"{GRAPH_API_URL}/me/posts",
            params={
                "access_token": PAGE_ACCESS_TOKEN,
                "fields": "id,message,created_time,likes.summary(true),comments.summary(true),shares",
                "limit": 20
            },
            timeout=15
        )
        posts_data = posts_r.json().get("data", [])

        post_stats = []
        total_likes = total_comments = total_shares = 0
        for p in posts_data:
            likes = p.get("likes", {}).get("summary", {}).get("total_count", 0)
            comments = p.get("comments", {}).get("summary", {}).get("total_count", 0)
            shares = p.get("shares", {}).get("count", 0)
            total_likes += likes
            total_comments += comments
            total_shares += shares
            post_stats.append({
                "id": p.get("id"),
                "text": (p.get("message") or "")[:80],
                "created": p.get("created_time"),
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "engagement": likes + comments + shares,
            })

        post_stats.sort(key=lambda x: x["engagement"], reverse=True)

        followers = page.get("followers_count", 0) or page.get("fan_count", 0)
        avg_engagement = (total_likes + total_comments + total_shares) / max(len(posts_data), 1)
        engagement_rate = (avg_engagement / max(followers, 1)) * 100

        return jsonify({
            "page_name": page.get("name"),
            "followers": followers,
            "talking_about": page.get("talking_about_count"),
            "posts_analyzed": len(posts_data),
            "total_likes": total_likes,
            "total_comments": total_comments,
            "total_shares": total_shares,
            "avg_engagement_per_post": round(avg_engagement, 1),
            "engagement_rate_percent": round(engagement_rate, 3),
            "top_posts": post_stats[:5],
            "worst_posts": post_stats[-3:] if len(post_stats) > 3 else [],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================
# ICE BREAKERS
# ============================================
@app.route("/api/setup-ice-breakers", methods=["GET", "POST"])
def setup_ice_breakers():
    """Set up Ice Breaker buttons for Messenger."""
    if not PAGE_ACCESS_TOKEN:
        return jsonify({"error": "No PAGE_ACCESS_TOKEN"}), 400

    ice_breakers = [
        {"question": "عاوز أعرف الأسعار 💰", "payload": "عاوز اعرف اسعار الشقق"},
        {"question": "عاوز أحجز زيارة 🏢", "payload": "عاوز احجز موعد زيارة للموقع"},
        {"question": "إيه العروض المتاحة؟ 🎉", "payload": "عندكم عروض ايه دلوقتي"},
        {"question": "عاوز أعرف أكتر عن المشروع 📐", "payload": "عاوز اعرف تفاصيل مشروع سكاي فيلاز"},
    ]

    try:
        page_id_resp = requests.get(
            f"{GRAPH_API_URL}/me",
            params={"access_token": PAGE_ACCESS_TOKEN, "fields": "id"},
            timeout=10
        )
        page_id = page_id_resp.json().get("id")

        r = requests.post(
            f"{GRAPH_API_URL}/{page_id}/messenger_profile",
            json={"ice_breakers": ice_breakers},
            params={"access_token": PAGE_ACCESS_TOKEN},
            timeout=10
        )
        result = r.json()
        return jsonify({"status": "✅ Ice Breakers set!", "result": result, "buttons": ice_breakers})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================
# FOLLOW-UP SYSTEM
# ============================================
@app.route("/api/follow-up", methods=["GET", "POST"])
def run_follow_up():
    """Send follow-up messages to users who haven't responded in 24h."""
    if not PAGE_ACCESS_TOKEN:
        return jsonify({"error": "No PAGE_ACCESS_TOKEN"}), 400

    hours = int(request.args.get("hours", 24))
    cutoff = datetime.now() - timedelta(hours=hours)
    sent = 0
    skipped = 0

    follow_up_msg = (
        "أهلاً بيك تاني! 😊\n"
        "لسه مهتم بوحدات Sky Villas M7؟\n"
        "العرض الحالي — الخدمات علينا (توفير لحد 200 ألف ج) 🎉\n"
        "لو عاوز تفاصيل أكتر أو تحجز زيارة، ابعتلنا! 🏢"
    )

    for uid, info in list(follow_up_tracker.items()):
        try:
            last_time = datetime.fromisoformat(info.get("last_msg_time", ""))
        except (ValueError, TypeError):
            continue

        if last_time > cutoff:
            skipped += 1
            continue
        if info.get("followed_up"):
            skipped += 1
            continue

        has_phone = bool(user_data.get(uid, {}).get("phone"))
        if has_phone:
            skipped += 1
            continue

        platform = info.get("platform", "messenger")
        try:
            send_message(uid, follow_up_msg, platform)
            follow_up_tracker[uid]["followed_up"] = True
            follow_up_tracker[uid]["follow_up_time"] = datetime.now().isoformat()
            sent += 1
            time.sleep(1)
        except Exception as e:
            logger.error(f"Follow-up failed for {uid}: {e}")

    save_follow_up()

    # Notify on Telegram
    if sent > 0:
        send_telegram(f"📨 <b>Follow-up Report</b>\n✅ Sent: {sent}\n⏭ Skipped: {skipped}")

    return jsonify({"sent": sent, "skipped": skipped, "hours": hours})


@app.route("/api/mark-contacted", methods=["POST"])
def mark_contacted():
    """Mark a lead as contacted by sales team."""
    uid = request.args.get("user_id") or request.json.get("user_id", "")
    if uid and uid in follow_up_tracker:
        follow_up_tracker[uid]["contacted"] = True
        follow_up_tracker[uid]["contacted_time"] = datetime.now().isoformat()
        save_follow_up()
        return jsonify({"status": "✅ Marked as contacted", "user_id": uid})
    return jsonify({"error": "User not found"}), 404


# ============================================
# DAILY REPORT
# ============================================
@app.route("/api/daily-report", methods=["GET"])
def daily_report():
    """Generate and send daily report to Telegram."""
    today = datetime.now().date().isoformat()

    # Count today's leads
    today_leads = [l for l in leads_db if l.get("timestamp", "").startswith(today)]

    # Count today's conversations
    today_convos = 0
    for uid, info in follow_up_tracker.items():
        try:
            if info.get("last_msg_time", "").startswith(today):
                today_convos += 1
        except Exception:
            pass

    # Pending follow-ups
    pending_followup = sum(
        1 for info in follow_up_tracker.values()
        if not info.get("followed_up") and not info.get("contacted")
    )

    # Not contacted yet
    not_contacted = sum(
        1 for info in follow_up_tracker.values()
        if info.get("followed_up") and not info.get("contacted")
    )

    report = (
        f"📊 <b>تقرير يومي — Sky Lines</b>\n"
        f"📅 {today}\n\n"
        f"💬 محادثات اليوم: <b>{today_convos}</b>\n"
        f"🔥 ليدات جديدة: <b>{len(today_leads)}</b>\n"
        f"📋 إجمالي الليدات: <b>{len(leads_db)}</b>\n"
        f"⏳ في انتظار المتابعة: <b>{pending_followup}</b>\n"
        f"📞 تم المتابعة ولم يتم التواصل: <b>{not_contacted}</b>\n\n"
    )

    if today_leads:
        report += "🔥 <b>ليدات اليوم:</b>\n"
        for l in today_leads:
            report += f"  • {l.get('name', '—')} — {l.get('phone', '—')} ({l.get('interest', '—')})\n"

    sent = send_telegram(report)

    return jsonify({
        "report_sent": sent,
        "today_conversations": today_convos,
        "today_leads": len(today_leads),
        "total_leads": len(leads_db),
        "pending_followup": pending_followup,
        "not_contacted": not_contacted,
    })


# ============================================
# SCHEDULER — Auto CRON jobs
# ============================================
def _scheduler_loop():
    """Background scheduler for automated tasks."""
    while True:
        try:
            now = datetime.now()

            # Every 30 minutes: reply to old comments
            if now.minute in (0, 30):
                logger.info("⏰ CRON: Replying to old comments...")
                try:
                    with app.test_request_context("/api/reply-old-comments?days=1"):
                        reply_old_comments()
                except Exception as e:
                    logger.error(f"CRON reply-old-comments error: {e}")

            # Every day at 9 PM (21:00): send daily report
            if now.hour == 21 and now.minute == 0:
                logger.info("⏰ CRON: Sending daily report...")
                try:
                    with app.test_request_context("/api/daily-report"):
                        daily_report()
                except Exception as e:
                    logger.error(f"CRON daily-report error: {e}")

            # Every 6 hours: follow-up with inactive users
            if now.hour in (9, 15, 21) and now.minute == 0:
                logger.info("⏰ CRON: Running follow-up...")
                try:
                    with app.test_request_context("/api/follow-up?hours=24"):
                        run_follow_up()
                except Exception as e:
                    logger.error(f"CRON follow-up error: {e}")

        except Exception as e:
            logger.error(f"Scheduler error: {e}")

        time.sleep(60)  # Check every minute


# ============================================
# MAIN
# ============================================
# Subscribe to page feed on startup
_sub = subscribe_page_feed()
logger.info(f"Feed subscription result: {_sub}")

# Start background scheduler
_scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
_scheduler_thread.start()
logger.info("⏰ Background scheduler started")

# Setup Ice Breakers on startup
try:
    with app.test_request_context("/api/setup-ice-breakers"):
        _ib = setup_ice_breakers()
        logger.info(f"Ice Breakers: set up")
except Exception as e:
    logger.warning(f"Ice Breakers setup skipped: {e}")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    if AI_PROVIDER == "fallback":
        logger.warning("⚠️ No AI key — set OPENAI_API_KEY or ANTHROPIC_API_KEY")
    else:
        logger.info(f"AI: {AI_PROVIDER} / {AI_MODEL}")
    logger.info(f"🚀 Starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)
