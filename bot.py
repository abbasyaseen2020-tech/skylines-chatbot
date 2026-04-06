# -*- coding: utf-8 -*-
"""
Sky Lines Real Estate - AI Agent (v2.0)
========================================
Facebook Messenger + WhatsApp + Facebook Comments
Powered by Flask + Anthropic Claude API + Facebook Graph API + WhatsApp Business API

الميزات:
- رد ذكي بالـ AI على الماسنجر + واتساب + تعليقات فيسبوك
- ذاكرة محادثات دائمة (Google Sheets)
- حفظ الليدز تلقائياً في Google Sheets
- رسائل متابعة تلقائية للعملاء الخاملين
- حماية من تكرار الرسائل
- Rate limiting لـ Google Sheets API
- استخراج بيانات العميل تلقائياً (اسم + تليفون + اهتمامات)
"""

import os
import json
import logging
import time
import requests
from datetime import datetime
from collections import defaultdict
from flask import Flask, request, jsonify

# Conversation memory
import conversation_store

# ============================================
# CONFIGURATION
# ============================================
app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment Variables
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "skylines_bot_verify_2026")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-sonnet-4-20250514")
ANTHROPIC_VERSION = "2025-01-01"
GRAPH_API_URL = "https://graph.facebook.com/v19.0"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

# Import knowledge base
from knowledge_base import (
    get_system_prompt, COMMENT_KEYWORDS, COMPANY_INFO,
    format_projects_for_search,
    EMOJI_POSITIVE, EMOJI_RESPONSES, THANK_WORDS
)

# ============================================
# DATA STORES
# ============================================
leads_db = []
conversation_history = defaultdict(list)
user_data = {}
phone_requested = {}  # Track if phone was already requested per user
MAX_HISTORY = 20

# ============================================
# DUPLICATE MESSAGE PREVENTION
# ============================================
_processed_messages = {}
_processed_comments = {}
MESSAGE_DEDUP_TTL = 60


def is_duplicate_message(msg_id):
    now = time.time()
    expired = [k for k, v in _processed_messages.items() if now - v > MESSAGE_DEDUP_TTL]
    for k in expired:
        del _processed_messages[k]
    if msg_id in _processed_messages:
        logger.info(f"Duplicate message ignored: {msg_id}")
        return True
    _processed_messages[msg_id] = now
    return False


def is_duplicate_comment(comment_id):
    now = time.time()
    expired = [k for k, v in _processed_comments.items() if now - v > MESSAGE_DEDUP_TTL]
    for k in expired:
        del _processed_comments[k]
    if comment_id in _processed_comments:
        logger.info(f"Duplicate comment ignored: {comment_id}")
        return True
    _processed_comments[comment_id] = now
    return False


# ============================================
# AI AGENT - CORE INTELLIGENCE
# ============================================
def ask_ai(user_id, user_message, platform="messenger"):
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set - falling back to basic responses")
        return fallback_response(user_message)

    # Load persistent history for returning users
    if not conversation_history[user_id]:
        stored_history = conversation_store.load_history(user_id)
        if stored_history:
            conversation_history[user_id] = stored_history
            logger.info(f"Loaded {len(stored_history)} messages from persistent storage for {user_id}")

    conversation_history[user_id].append({
        "role": "user",
        "content": user_message
    })

    # Save user message to persistent storage
    conversation_store.save_message(user_id, platform, "user", user_message)

    if len(conversation_history[user_id]) > MAX_HISTORY:
        conversation_history[user_id] = conversation_history[user_id][-MAX_HISTORY:]

    user_context = ""
    if user_id in user_data:
        data = user_data[user_id]
        if data.get("name"):
            user_context += f"\n[معلومات العميل: الاسم: {data['name']}"
            if data.get("phone"):
                user_context += f"، التليفون: {data['phone']}"
            if data.get("interest"):
                user_context += f"، مهتم بـ: {data['interest']}"
            user_context += "]"

    system_prompt = get_system_prompt()
    if user_context:
        system_prompt += f"\n\n## معلومات العميل الحالي:{user_context}"

    # Detect if this is the first message (new user) or returning user
    is_first_message = len(conversation_history[user_id]) <= 1
    msg_count = len(conversation_history[user_id])

    # Add conversation context note for returning users
    if not is_first_message:
        system_prompt += "\n\n## العميل ده كلمنا قبل كده — كملي المحادثة من حيث ما وقفت. ماتسأليش أسئلة اتسألت قبل كده."

    system_prompt += f"\n\n## المنصة الحالية: {platform}"
    if platform == "whatsapp":
        system_prompt += "\n(العميل على واتساب - الردود لازم تكون أقصر شوية)"

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    if is_first_message:
        system_prompt += "\n\n## ⚠️ ده أول رسالة من العميل — عرّفي نفسك (أسيل من Sky Lines) مرة واحدة بس."
    else:
        system_prompt += "\n\n## ⚠️ المحادثة مكملة — ممنوع نهائياً تقولي اسمك أو تعرّفي نفسك. ردي مباشر ومختصر."

    # Phone request tracking
    already_has_phone = bool(user_data.get(user_id, {}).get("phone"))
    already_asked_phone = phone_requested.get(user_id, False)

    if already_has_phone:
        system_prompt += "\n## ℹ️ العميل ده ساب رقمه بالفعل — ماتطلبيش رقم تاني."
    elif already_asked_phone:
        system_prompt += "\n## ⛔ طلبتي رقم التليفون قبل كده — ممنوع تطلبيه تاني نهائياً. كملي المحادثة عادي."
    elif msg_count < 4:
        system_prompt += f"\n## ⛔ ده لسه رسالة رقم {msg_count} — بدري على طلب رقم التليفون. ماتطلبيش دلوقتي."

    payload = {
        "model": AI_MODEL,
        "max_tokens": 200,
        "temperature": 0.7,
        "system": system_prompt,
        "messages": conversation_history[user_id],
    }

    try:
        response = requests.post(
            ANTHROPIC_API_URL,
            headers=headers,
            json=payload,
            timeout=30
        )
        if response.status_code != 200:
            error_body = response.text[:500]
            logger.error(f"Claude API error {response.status_code}: {error_body}")
        response.raise_for_status()
        result = response.json()

        ai_response = result["content"][0]["text"]

        # Post-process: enforce rules the AI might break
        ai_response = _post_process_response(user_id, ai_response, is_first_message)

        conversation_history[user_id].append({
            "role": "assistant",
            "content": ai_response
        })

        # Save AI response to persistent storage
        conversation_store.save_message(user_id, platform, "assistant", ai_response)

        extract_user_data(user_id, user_message, ai_response)

        # Track if the AI asked for phone number (specific patterns only)
        phone_ask_patterns = [
            "رقم حضرتك", "رقم تليفون", "رقم موبايل", "رقمك",
            "ابعتلي رقم", "ابعتلنا رقم", "سيب رقمك",
            "واتساب ولا مكالمة", "يكلمك", "يتواصل مع حضرتك",
            "يكلم حضرتك", "نمبرك"
        ]
        if any(p in ai_response for p in phone_ask_patterns):
            phone_requested[user_id] = True

        logger.info(f"AI response for {user_id}: {ai_response[:100]}...")
        return ai_response

    except requests.exceptions.Timeout:
        logger.error("Claude API timeout")
        return "عذراً، حصل تأخير بسيط. ممكن تبعت رسالتك تاني؟ 🙏"

    except requests.exceptions.RequestException as e:
        logger.error(f"Claude API error: {e}")
        return fallback_response(user_message)

    except (KeyError, IndexError) as e:
        logger.error(f"Unexpected API response format: {e}")
        return fallback_response(user_message)


def ask_ai_comment(comment_text, sender_name):
    if not ANTHROPIC_API_KEY:
        return None

    system_prompt = get_system_prompt()
    system_prompt += """

## سياق خاص: رد على تعليق فيسبوك (عام — كل الناس بتشوفه)
- سطر واحد بس — 15 كلمة ماكس
- رحبي بالعميل باسمه
- وجهيه يبعتلنا رسالة خاصة: "ابعتلنا رسالة وهنرد عليك 😊"
- ممنوع أسعار أو أرقام في التعليقات
- ممنوع تقولي اسمك "أسيل" نهائياً — ردي كصفحة الشركة
- ممنوع تطلبي رقم تليفون
"""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    messages = [{
        "role": "user",
        "content": f"العميل {sender_name} علّق على بوست الصفحة وقال: \"{comment_text}\"\nرد عليه رد مختصر ومناسب للتعليقات العامة."
    }]

    payload = {
        "model": AI_MODEL,
        "max_tokens": 100,
        "temperature": 0.7,
        "system": system_prompt,
        "messages": messages,
    }

    try:
        response = requests.post(
            ANTHROPIC_API_URL,
            headers=headers,
            json=payload,
            timeout=15
        )
        if response.status_code != 200:
            error_body = response.text[:500]
            logger.error(f"AI comment API error {response.status_code}: {error_body}")
        response.raise_for_status()
        result = response.json()
        return result["content"][0]["text"]
    except Exception as e:
        logger.error(f"AI comment response error: {e}")
        return None


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
        prev_msg = history[-2].get("content", "") if history[-2]["role"] == "assistant" else ""
        if any(word in prev_msg for word in ["اسمك", "اسم حضرتك", "نعرف اسمك"]):
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
    import re
    patterns = [
        r'01[0-9]{9}',
        r'\+201[0-9]{9}',
        r'201[0-9]{9}',
        r'01[0-9]-[0-9]{4}-[0-9]{4}',
        r'01[0-9] [0-9]{4} [0-9]{4}',
    ]
    clean = text.replace("-", "").replace(" ", "")
    for pattern in patterns:
        match = re.search(pattern, clean)
        if match:
            return match.group()
    return None


def auto_save_lead(user_id):
    data = user_data.get(user_id, {})
    if data.get("name") and data.get("phone"):
        existing = [l for l in leads_db if l.get("phone") == data["phone"]]
        if not existing:
            lead = {
                "name": data["name"],
                "phone": data["phone"],
                "interest": data.get("interest", "غير محدد"),
                "platform": "auto",
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
            }
            save_lead(lead)
            logger.info(f"Auto-saved lead: {data['name']} - {data['phone']}")


def _post_process_response(user_id, response, is_first_message):
    """Enforce response rules that the AI might break."""
    import re

    # 1. Remove name mentions if not first message
    if not is_first_message:
        response = re.sub(r'أنا\s*أسيل[^.!؟\n]*[.!؟]?\s*', '', response)
        response = re.sub(r'أسيل\s*هنا[^.!؟\n]*[.!؟]?\s*', '', response)
        response = re.sub(r'أسيل\s*من\s*Sky\s*Lines[^.!؟\n]*[.!؟]?\s*', '', response)
        response = re.sub(r'معاكِ?\s*أسيل[^.!؟\n]*[.!؟]?\s*', '', response)
        response = re.sub(r'أسيل\s*معاك[^.!؟\n]*[.!؟]?\s*', '', response)

    # 2. Remove duplicate greetings after first message
    if not is_first_message:
        response = re.sub(r'^(أهلاً?\s*(بيك|وسهلاً?)?!?\s*🏢?\s*)', '', response)
        response = re.sub(r'^(مرحبا!?\s*)', '', response)

    # 3. Trim excessively long responses
    lines = response.strip().split('\n')
    has_card = any('🟢' in line or '💰' in line or '━' in line for line in lines)
    max_lines = 12 if has_card else 5
    if len(lines) > max_lines:
        response = '\n'.join(lines[:max_lines])

    # 4. Clean up whitespace
    response = re.sub(r'\n{3,}', '\n\n', response)
    response = response.strip()

    return response


def fallback_response(message):
    text = message.lower().strip()

    if any(w in text for w in ["سلام", "هاي", "مرحبا", "صباح", "مساء", "اهلا", "أهلا", "هلو"]):
        return "أهلاً بيك! 🏢 حضرتك بتدور على سكن ولا استثمار؟"

    if any(w in text for w in ["سعر", "كام", "تقسيط", "مقدم", "دفع", "قسط"]):
        return "حضرتك مهتم بأنهي مشروع عشان أقدر أفيدك بالأسعار؟ 😊"

    if any(w in text for w in ["مشاريع", "شقة", "شقق", "فيلا", "فيلات", "محل", "مكتب"]):
        return "عندنا مشاريع في بني سويف — سكني وتجاري وإداري. حضرتك بتدور على إيه بالظبط؟"

    if any(w in text for w in ["حجز", "موعد", "زيارة", "معاينة"]):
        return "تحب التواصل يكون واتساب ولا مكالمة تليفون؟ 😊"

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

    logger.info(f"[{platform}] Message from {user_id}: {text[:100]}")

    ai_response = ask_ai(user_id, text, platform)
    send_message(user_id, ai_response, platform)


# ============================================
# COMMENT HANDLER
# ============================================
def handle_comment(comment_data):
    comment_id = comment_data.get("comment_id")
    comment_text = comment_data.get("message", "")
    sender_name = comment_data.get("from", {}).get("name", "")
    verb = comment_data.get("verb", "")

    if verb != "add":
        return

    if is_duplicate_comment(comment_id):
        return

    is_positive = (
        any(emoji in comment_text for emoji in EMOJI_POSITIVE) or
        any(word in comment_text for word in THANK_WORDS)
    )

    if is_positive and not any(keyword in comment_text for keyword in COMMENT_KEYWORDS):
        import random
        if any(emoji in comment_text for emoji in EMOJI_POSITIVE) and len(comment_text.strip()) <= 5:
            response = random.choice(EMOJI_RESPONSES)
        else:
            response = f"شكراً ليك يا {sender_name}! نورتنا 🙏❤️"
        reply_to_comment(comment_id, response)
        logger.info(f"Positive comment from {sender_name}: {comment_text[:50]}")
        return

    if any(keyword in comment_text for keyword in COMMENT_KEYWORDS):
        ai_reply = ask_ai_comment(comment_text, sender_name)
        if ai_reply:
            reply_to_comment(comment_id, ai_reply)
        else:
            reply_to_comment(
                comment_id,
                f"أهلاً يا {sender_name}! 👋 ابعتلنا رسالة خاصة وهنرد عليك بكل التفاصيل 😊"
            )
        logger.info(f"AI comment reply to {sender_name}: {comment_text[:50]}")
        return

    reply_to_comment(
        comment_id,
        f"أهلاً يا {sender_name}! 😊 لو محتاج أي معلومات عن مشاريعنا ابعتلنا رسالة خاصة وهنساعدك!"
    )
    logger.info(f"Generic comment reply to {sender_name}: {comment_text[:50]}")


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
        chunks = split_message(text, 2000)
        for chunk in chunks:
            _send_messenger_raw(recipient_id, chunk)
            time.sleep(0.5)
    else:
        _send_messenger_raw(recipient_id, text)


def _send_messenger_raw(recipient_id, text):
    url = f"{GRAPH_API_URL}/me/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
        "messaging_type": "RESPONSE"
    }
    params = {"access_token": PAGE_ACCESS_TOKEN}
    try:
        response = requests.post(url, json=payload, params=params, timeout=10)
        response.raise_for_status()
        logger.info(f"Messenger message sent to {recipient_id}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send Messenger message: {e}")


def send_quick_replies(recipient_id, text, buttons):
    url = f"{GRAPH_API_URL}/me/messages"
    quick_replies = [
        {"content_type": "text", "title": btn["title"][:20], "payload": btn["payload"]}
        for btn in buttons[:13]
    ]
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text, "quick_replies": quick_replies},
        "messaging_type": "RESPONSE"
    }
    params = {"access_token": PAGE_ACCESS_TOKEN}
    try:
        response = requests.post(url, json=payload, params=params, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send quick replies: {e}")


def reply_to_comment(comment_id, text):
    url = f"{GRAPH_API_URL}/{comment_id}/comments"
    payload = {"message": text}
    params = {"access_token": PAGE_ACCESS_TOKEN}
    try:
        response = requests.post(url, json=payload, params=params, timeout=10)
        response.raise_for_status()
        logger.info(f"Replied to comment {comment_id}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to reply to comment: {e}")


def send_private_reply(comment_id, text):
    url = f"{GRAPH_API_URL}/me/messages"
    payload = {
        "recipient": {"comment_id": comment_id},
        "message": {"text": text},
        "messaging_type": "RESPONSE"
    }
    params = {"access_token": PAGE_ACCESS_TOKEN}
    try:
        response = requests.post(url, json=payload, params=params, timeout=10)
        response.raise_for_status()
        logger.info(f"Private reply sent for comment {comment_id}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send private reply: {e}")


# ============================================
# SEND FUNCTIONS - WHATSAPP
# ============================================
def send_whatsapp_message(phone_number, text):
    if len(text) > 4000:
        chunks = split_message(text, 4000)
        for chunk in chunks:
            _send_whatsapp_raw(phone_number, chunk)
            time.sleep(0.5)
    else:
        _send_whatsapp_raw(phone_number, text)


def _send_whatsapp_raw(phone_number, text):
    url = f"{GRAPH_API_URL}/{WHATSAPP_PHONE_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "text",
        "text": {"body": text}
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WHATSAPP_TOKEN}"
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        logger.info(f"WhatsApp message sent to {phone_number}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send WhatsApp message: {e}")


def send_whatsapp_buttons(phone_number, text, buttons):
    url = f"{GRAPH_API_URL}/{WHATSAPP_PHONE_ID}/messages"
    rows = [{"id": btn["payload"], "title": btn["title"][:24]} for btn in buttons[:10]]
    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": text},
            "action": {
                "button": "اختر",
                "sections": [{"title": "الخيارات", "rows": rows}]
            }
        }
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WHATSAPP_TOKEN}"
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send WhatsApp buttons: {e}")


def send_whatsapp_template(phone_number, template_name, parameters):
    url = f"{GRAPH_API_URL}/{WHATSAPP_PHONE_ID}/messages"
    components = []
    if parameters:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in parameters]
        })
    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "ar"},
            "components": components
        }
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WHATSAPP_TOKEN}"
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send WhatsApp template: {e}")


# ============================================
# UTILITY FUNCTIONS
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
# LEAD MANAGEMENT
# ============================================
def save_lead(lead):
    leads_db.append(lead)
    try:
        conversation_store.save_lead_to_sheets(lead)
    except Exception as e:
        logger.error(f"Failed to persist lead to Sheets: {e}")
    logger.info(f"Lead saved: {lead.get('name', 'Unknown')} - {lead.get('phone', 'N/A')}")


def notify_sales_team(lead):
    logger.info(
        f"New lead: {lead.get('name', '')} ({lead.get('phone', '')}) "
        f"- Interest: {lead.get('interest', 'غير محدد')}"
    )


# ============================================
# WEBHOOK ROUTES
# ============================================
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Facebook webhook verified!")
        return challenge, 200
    return "Verification failed", 403


@app.route("/webhook", methods=["POST"])
def handle_webhook():
    data = request.get_json()

    if data.get("object") == "page":
        for entry in data.get("entry", []):
            for messaging_event in entry.get("messaging", []):
                sender_id = messaging_event["sender"]["id"]
                message_id = None

                if "message" in messaging_event:
                    message = messaging_event["message"]
                    message_id = message.get("mid")

                    if "quick_reply" in message:
                        text = message["quick_reply"]["payload"]
                    else:
                        text = message.get("text", "")

                    if text:
                        handle_message(sender_id, text, "messenger", message_id)

                elif "postback" in messaging_event:
                    payload = messaging_event["postback"]["payload"]
                    handle_message(sender_id, payload, "messenger")

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
                    messages = change["value"].get("messages", [])
                    for msg in messages:
                        phone = msg["from"]
                        msg_id = msg.get("id")

                        if msg["type"] == "text":
                            text = msg["text"]["body"]
                        elif msg["type"] == "interactive":
                            interactive = msg.get("interactive", {})
                            if "list_reply" in interactive:
                                text = interactive["list_reply"]["title"]
                            elif "button_reply" in interactive:
                                text = interactive["button_reply"]["title"]
                            else:
                                text = ""
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
    all_leads = leads_db
    if not all_leads:
        try:
            all_leads = conversation_store.get_all_leads()
        except Exception:
            pass
    return jsonify({"leads": all_leads, "total": len(all_leads)})


@app.route("/api/stats", methods=["GET"])
def get_stats():
    return jsonify({
        "total_leads": len(leads_db),
        "active_conversations": len(conversation_history),
        "users_with_data": len(user_data),
        "platforms": {
            "messenger": len([l for l in leads_db if l.get("platform") == "messenger"]),
            "whatsapp": len([l for l in leads_db if l.get("platform") == "whatsapp"]),
            "auto": len([l for l in leads_db if l.get("platform") == "auto"]),
        }
    })


@app.route("/api/conversations/<user_id>", methods=["GET"])
def get_conversation(user_id):
    return jsonify({
        "user_id": user_id,
        "messages": conversation_history.get(user_id, []),
        "user_data": user_data.get(user_id, {}),
    })


@app.route("/api/health", methods=["GET"])
def health_check():
    ai_status = "configured" if ANTHROPIC_API_KEY else "not configured (using fallback)"
    fb_status = "configured" if PAGE_ACCESS_TOKEN else "not configured"
    wa_status = "configured" if WHATSAPP_TOKEN else "not configured"

    return jsonify({
        "status": "running",
        "ai_engine": ai_status,
        "facebook": fb_status,
        "whatsapp": wa_status,
        "uptime": "OK",
        "model": AI_MODEL,
    })


# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))

    if not ANTHROPIC_API_KEY:
        logger.warning("⚠️ ANTHROPIC_API_KEY not set - AI Agent will use basic fallback responses")
    else:
        logger.info(f"🤖 AI Engine: {AI_MODEL}")

    if not PAGE_ACCESS_TOKEN:
        logger.warning("⚠️ PAGE_ACCESS_TOKEN not set - Messenger won't work")

    if not WHATSAPP_TOKEN:
        logger.warning("⚠️ WHATSAPP_TOKEN not set - WhatsApp won't work")

    conversation_store.start_reminder_thread(send_message)

    logger.info("📋 Conversation memory: enabled (Google Sheets)")
    logger.info("💾 Leads storage: persistent (Google Sheets)")
    logger.info("⏰ Follow-up reminders: enabled (2-72h check)")
    logger.info(f"🚀 Sky Lines AI Agent v2.0 starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)
