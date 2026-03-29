"""
Sky Lines Real Estate - AI Agent
=================================
Facebook Messenger + WhatsApp + Facebook Comments
Powered by Flask + OpenAI GPT API + Facebook Graph API + WhatsApp Business API

هذا البوت يستخدم AI حقيقي (GPT) للرد على العملاء كموظف مبيعات محترف.
يفهم السياق، يتذكر المحادثة، ويتعامل مع أي سؤال بذكاء.

Setup:
1. pip install -r requirements.txt
2. Set environment variables (see .env.example)
3. Configure Facebook App + WhatsApp Business API
4. Run: python bot.py
"""

import os
import json
import logging
import time
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

# Environment Variables
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "skylines_bot_verify_2026")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4.1-mini")

GRAPH_API_URL = "https://graph.facebook.com/v19.0"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

# Import knowledge base
from knowledge_base import (
    get_system_prompt, COMMENT_KEYWORDS, COMPANY_INFO,
    format_projects_for_search
)

# ============================================
# DATA STORES
# ============================================

leads_db = []  # In production, use a real database
conversation_history = defaultdict(list)  # user_id -> list of messages
user_data = {}  # user_id -> collected data (name, phone, etc.)
MAX_HISTORY = 20  # Max messages to keep per conversation


# ============================================
# AI AGENT - CORE INTELLIGENCE
# ============================================

def sanitize_history(history):
    """
    تنظيف تاريخ المحادثة لضمان تناوب صحيح بين user و assistant.
    Claude API يتطلب أن تبدأ الرسائل بـ user وتتناوب بين user و assistant.
    """
    if not history:
        return []

    sanitized = []
    for msg in history:
        role = msg.get("role")
        content = msg.get("content", "").strip()

        if not content:
            continue

        if not sanitized:
            # أول رسالة لازم تكون user
            if role == "user":
                sanitized.append(msg)
            # لو أول رسالة assistant، تجاهلها
            continue

        last_role = sanitized[-1]["role"]

        if role == last_role:
            # لو نفس الدور متكرر، ادمج المحتوى
            if role == "user":
                sanitized[-1] = {
                    "role": "user",
                    "content": sanitized[-1]["content"] + "\n" + content
                }
            else:
                # لو assistant متكرر، استبدل بالأحدث
                sanitized[-1] = msg
        else:
            sanitized.append(msg)

    # لازم آخر رسالة تكون user (لأن Claude يرد على آخر رسالة user)
    if sanitized and sanitized[-1]["role"] != "user":
        sanitized.pop()

    return sanitized


def ask_ai(user_id, user_message, platform="messenger"):
    """
    إرسال رسالة العميل إلى OpenAI API والحصول على رد ذكي
    يحتفظ بسياق المحادثة لكل عميل
    """
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set - falling back to basic responses")
        return fallback_response(user_message)

    # إضافة رسالة العميل للتاريخ
    conversation_history[user_id].append({
        "role": "user",
        "content": user_message
    })

    # الاحتفاظ بآخر MAX_HISTORY رسالة فقط
    if len(conversation_history[user_id]) > MAX_HISTORY:
        conversation_history[user_id] = conversation_history[user_id][-MAX_HISTORY:]

    # تنظيف التاريخ لضمان تناوب صحيح
    clean_history = sanitize_history(conversation_history[user_id])

    if not clean_history:
        clean_history = [{"role": "user", "content": user_message}]

    # تجهيز context إضافي عن العميل
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

    system_prompt += f"\n\n## المنصة الحالية: {platform}"
    if platform == "whatsapp":
        system_prompt += "\n(العميل على واتساب - الردود لازم تكون أقصر شوية)"

    # إرسال الطلب لـ OpenAI API
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    # OpenAI يستخدم system message داخل الـ messages array
    messages = [{"role": "system", "content": system_prompt}] + clean_history

    payload = {
        "model": AI_MODEL,
        "max_tokens": 500,
        "messages": messages,
    }

    try:
        response = requests.post(
            OPENAI_API_URL, headers=headers, json=payload, timeout=30
        )

        # تسجيل تفاصيل الخطأ قبل raise_for_status
        if response.status_code != 200:
            logger.error(f"OpenAI API HTTP {response.status_code}: {response.text[:500]}")

        response.raise_for_status()
        result = response.json()
        ai_response = result["choices"][0]["message"]["content"]

        # حفظ رد الـ AI في التاريخ
        conversation_history[user_id].append({
            "role": "assistant",
            "content": ai_response
        })

        # محاولة استخراج بيانات العميل من المحادثة
        extract_user_data(user_id, user_message, ai_response)

        logger.info(f"AI response for {user_id}: {ai_response[:100]}...")
        return ai_response

    except requests.exceptions.Timeout:
        logger.error("OpenAI API timeout")
        fb_response = "عذراً، حصل تأخير بسيط. ممكن تبعت رسالتك تاني؟ 🙏"
        # إضافة رد الـ fallback للتاريخ لمنع تكرار دور user
        conversation_history[user_id].append({
            "role": "assistant",
            "content": fb_response
        })
        return fb_response

    except requests.exceptions.RequestException as e:
        logger.error(f"OpenAI API error: {e}")
        fb_response = fallback_response(user_message)
        # إضافة رد الـ fallback للتاريخ لمنع تكرار دور user
        conversation_history[user_id].append({
            "role": "assistant",
            "content": fb_response
        })
        return fb_response

    except (KeyError, IndexError) as e:
        logger.error(f"Unexpected API response format: {e}")
        fb_response = fallback_response(user_message)
        # إضافة رد الـ fallback للتاريخ لمنع تكرار دور user
        conversation_history[user_id].append({
            "role": "assistant",
            "content": fb_response
        })
        return fb_response


def extract_user_data(user_id, user_message, ai_response):
    """
    استخراج بيانات العميل تلقائياً من المحادثة
    (اسم، رقم تليفون، اهتمامات)
    """
    if user_id not in user_data:
        user_data[user_id] = {}

    text = user_message.strip()

    # استخراج رقم التليفون
    phone = extract_phone(text)
    if phone:
        user_data[user_id]["phone"] = phone
        # لو عندنا اسم ورقم - نسجل الـ lead
        if user_data[user_id].get("name"):
            auto_save_lead(user_id)

    # استخراج الاسم (لو الرسالة السابقة كانت بتسأل عن الاسم)
    history = conversation_history.get(user_id, [])
    if len(history) >= 2:
        prev_msg = history[-2].get("content", "") if history[-2]["role"] == "assistant" else ""
        if any(word in prev_msg for word in ["اسمك", "اسم حضرتك", "نعرف اسمك"]):
            # الرسالة الحالية ممكن تكون الاسم
            if len(text.split()) <= 4 and not text.startswith("0"):
                user_data[user_id]["name"] = text

    # استخراج الاهتمامات
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
    """استخراج رقم التليفون من النص"""
    import re
    # أنماط أرقام التليفون المصرية
    patterns = [
        r'01[0-9]{9}',               # 01XXXXXXXXX
        r'\+201[0-9]{9}',            # +201XXXXXXXXX
        r'201[0-9]{9}',              # 201XXXXXXXXX
        r'01[0-9]-[0-9]{4}-[0-9]{4}',  # 01X-XXXX-XXXX
        r'01[0-9] [0-9]{4} [0-9]{4}',  # 01X XXXX XXXX
    ]
    clean = text.replace("-", "").replace(" ", "")
    for pattern in patterns:
        match = re.search(pattern, clean)
        if match:
            return match.group()
    return None


def auto_save_lead(user_id):
    """حفظ العميل المحتمل تلقائياً عند جمع البيانات الكافية"""
    data = user_data.get(user_id, {})
    if data.get("name") and data.get("phone"):
        # تأكد إننا ما سجلناش نفس الرقم قبل كده
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


def fallback_response(message):
    """
    ردود احتياطية في حالة عدم توفر AI API
    تستخدم نظام كلمات مفتاحية بسيط
    أسيل هي اسم المساعدة
    """
    text = message.lower().strip()

    # تحية
    if any(w in text for w in ["سلام", "هاي", "مرحبا", "صباح", "مساء", "اهلا", "أهلا", "هلو"]):
        return (
            "أهلاً بحضرتك! أنا أسيل من Sky Lines Group 😊\n"
            "يسعدني أساعدك تلاقي الوحدة المناسبة ليك.\n"
            "حضرتك بتدور على سكن ولا استثمار؟"
        )

    # أسعار وتقسيط
    if any(w in text for w in ["سعر", "كام", "تقسيط", "مقدم", "دفع", "قسط"]):
        return (
            "أنظمة السداد في مشروع Sky Villas M7 مرنة جداً:\n"
            "• السكني: مقدم 30% وتقسيط حتى يوليو 2027\n"
            "• التجاري: مقدم يبدأ من 10% فقط!\n"
            "• خصم 100,000 ج عند سداد 50%\n\n"
            "حضرتك مهتم بوحدة سكنية ولا تجارية ولا إدارية؟"
        )

    # مشاريع
    if any(w in text for w in ["مشاريع", "شقة", "شقق", "فيلا", "فيلات", "محل", "مكتب"]):
        return (
            "مشروعنا الرئيسي Sky Villas M7 في شرق النيل - بني سويف 🏢\n"
            "يضم وحدات سكنية وتجارية وإدارية بتصميم كلاسيكي أوروبي فاخر.\n"
            "حضرتك مهتم بأنهي نوع وحدة؟"
        )

    # حجز موعد
    if any(w in text for w in ["حجز", "موعد", "زيارة", "معاينة"]):
        return (
            "يسعدنا جداً نرتب لحضرتك زيارة للموقع!\n"
            "أقدر أرتبلك تواصل مباشر مع مسؤول المبيعات.\n"
            "ممكن أعرف اسم حضرتك ورقم التواصل؟ 📅"
        )

    # مستشار
    if any(w in text for w in ["مستشار", "أتكلم", "حد يكلمني", "تواصل"]):
        return (
            "أكيد! أقدر أرتبلك تواصل مباشر مع مسؤول المبيعات.\n"
            "ممكن أعرف اسم حضرتك ورقم التواصل عشان يرد عليك في أقرب وقت؟ 📞"
        )

    # رد افتراضي
    return (
        "أهلاً بحضرتك! أنا أسيل من Sky Lines Group 😊\n"
        "أقدر أساعدك في معلومات عن مشروعاتنا وأسعارها وأنظمة السداد.\n"
        "حضرتك بتدور على إيه بالظبط؟"
    )


# ============================================
# MESSAGE HANDLER
# ============================================

def handle_message(user_id, message_text, platform="messenger"):
    """
    معالج الرسائل الرئيسي - يرسل كل رسالة للـ AI Agent
    """
    text = message_text.strip()
    if not text:
        return

    logger.info(f"[{platform}] Message from {user_id}: {text[:100]}")

    # الحصول على رد الـ AI
    ai_response = ask_ai(user_id, text, platform)

    # إرسال الرد
    send_message(user_id, ai_response, platform)


# ============================================
# COMMENT HANDLER
# ============================================

def handle_comment(comment_data):
    """معالج تعليقات فيسبوك - يرد على التعليقات ذات الصلة"""
    comment_id = comment_data.get("comment_id")
    comment_text = comment_data.get("message", "")
    sender_name = comment_data.get("from", {}).get("name", "")
    verb = comment_data.get("verb", "")

    if verb != "add":
        return

    # التحقق من الكلمات المفتاحية
    if any(keyword in comment_text for keyword in COMMENT_KEYWORDS):
        # رد عام على التعليق
        public_reply = f"أهلاً {sender_name}! 👋 بعتنالك رسالة خاصة بكل التفاصيل. تابع الماسنجر!"
        reply_to_comment(comment_id, public_reply)

        # رد خاص ذكي عبر الماسنجر
        private_context = f"العميل {sender_name} علّق على بوست وقال: \"{comment_text}\". رد عليه برسالة ترحيبية وأجب على سؤاله."
        ai_response = ask_ai(
            f"comment_{comment_id}",
            private_context,
            "messenger"
        )
        send_private_reply(comment_id, ai_response)
        logger.info(f"AI responded to comment from {sender_name}: {comment_text[:50]}")

    elif any(word in comment_text for word in ["ممتاز", "جميل", "حلو", "رائع", "شكراً", "شكرا", "❤", "👍"]):
        reply_to_comment(comment_id, f"شكراً ليك {sender_name}! نورتنا 🙏")


# ============================================
# SEND FUNCTIONS - MESSENGER
# ============================================

def send_message(user_id, text, platform="messenger"):
    """إرسال رسالة نصية"""
    if platform == "whatsapp":
        send_whatsapp_message(user_id, text)
    else:
        send_messenger_message(user_id, text)


def send_messenger_message(recipient_id, text):
    """إرسال رسالة عبر Messenger"""
    # تقسيم الرسائل الطويلة (حد الماسنجر 2000 حرف)
    if len(text) > 2000:
        chunks = split_message(text, 2000)
        for chunk in chunks:
            _send_messenger_raw(recipient_id, chunk)
            time.sleep(0.5)  # تأخير بسيط بين الرسائل
    else:
        _send_messenger_raw(recipient_id, text)


def _send_messenger_raw(recipient_id, text):
    """إرسال رسالة واحدة عبر Messenger API"""
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
    """إرسال رسالة مع أزرار اختيار سريع عبر Messenger"""
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
    """الرد على تعليق فيسبوك"""
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
    """إرسال رد خاص لصاحب التعليق عبر Messenger"""
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
    """إرسال رسالة عبر WhatsApp Business API"""
    # تقسيم الرسائل الطويلة (حد واتساب 4096 حرف)
    if len(text) > 4000:
        chunks = split_message(text, 4000)
        for chunk in chunks:
            _send_whatsapp_raw(phone_number, chunk)
            time.sleep(0.5)
    else:
        _send_whatsapp_raw(phone_number, text)


def _send_whatsapp_raw(phone_number, text):
    """إرسال رسالة واحدة عبر WhatsApp API"""
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
    """إرسال رسالة مع أزرار عبر WhatsApp"""
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
    """إرسال رسالة قالب عبر WhatsApp (لبدء محادثات جديدة)"""
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
    """تقسيم رسالة طويلة إلى أجزاء"""
    chunks = []
    while len(text) > max_length:
        # البحث عن آخر سطر جديد قبل الحد
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
    """حفظ بيانات العميل المحتمل"""
    leads_db.append(lead)
    logger.info(f"Lead saved: {lead.get('name', 'Unknown')} - {lead.get('phone', 'N/A')}")
    # TODO: Uncomment and configure for Google Sheets integration
    # save_to_google_sheets(lead)


def notify_sales_team(lead):
    """إشعار فريق المبيعات بعميل جديد"""
    logger.info(
        f"🔔 New lead: {lead.get('name', '')} ({lead.get('phone', '')}) "
        f"- Interest: {lead.get('interest', 'غير محدد')}"
    )
    # TODO: إضافة إشعارات (بريد إلكتروني، واتساب، إلخ)


# ============================================
# WEBHOOK ROUTES
# ============================================

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """التحقق من Webhook لفيسبوك"""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Facebook webhook verified!")
        return challenge, 200
    return "Verification failed", 403


@app.route("/webhook", methods=["POST"])
def handle_webhook():
    """معالجة الأحداث الواردة من فيسبوك"""
    data = request.get_json()

    if data.get("object") == "page":
        for entry in data.get("entry", []):
            # معالجة رسائل Messenger
            for messaging_event in entry.get("messaging", []):
                sender_id = messaging_event["sender"]["id"]

                if "message" in messaging_event:
                    message = messaging_event["message"]
                    if "quick_reply" in message:
                        text = message["quick_reply"]["payload"]
                    else:
                        text = message.get("text", "")

                    if text:
                        handle_message(sender_id, text, "messenger")

                elif "postback" in messaging_event:
                    payload = messaging_event["postback"]["payload"]
                    handle_message(sender_id, payload, "messenger")

            # معالجة تعليقات فيسبوك
            for change in entry.get("changes", []):
                if change.get("field") == "feed" and change["value"].get("item") == "comment":
                    handle_comment(change["value"])

    return "OK", 200


@app.route("/whatsapp-webhook", methods=["GET"])
def verify_whatsapp_webhook():
    """التحقق من Webhook لواتساب"""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403


@app.route("/whatsapp-webhook", methods=["POST"])
def handle_whatsapp_webhook():
    """معالجة الرسائل الواردة من واتساب"""
    data = request.get_json()

    if data.get("object") == "whatsapp_business_account":
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "messages":
                    messages = change["value"].get("messages", [])
                    for msg in messages:
                        phone = msg["from"]

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
                            handle_message(phone, text, "whatsapp")

    return "OK", 200


# ============================================
# API ENDPOINTS (Dashboard / Admin)
# ============================================

@app.route("/api/leads", methods=["GET"])
def get_leads():
    """عرض كل العملاء المحتملين"""
    return jsonify({"leads": leads_db, "total": len(leads_db)})


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """إحصائيات البوت"""
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
    """عرض محادثة عميل معين"""
    return jsonify({
        "user_id": user_id,
        "messages": conversation_history.get(user_id, []),
        "user_data": user_data.get(user_id, {}),
    })


@app.route("/api/health", methods=["GET"])
def health_check():
    """فحص حالة البوت"""
    ai_status = "configured" if OPENAI_API_KEY else "not configured (using fallback)"
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

    # التحقق من الإعدادات
    if not OPENAI_API_KEY:
        logger.warning("⚠️ OPENAI_API_KEY not set - AI Agent will use basic fallback responses")
    else:
        logger.info(f"🤖 AI Engine: {AI_MODEL}")

    if not PAGE_ACCESS_TOKEN:
        logger.warning("⚠️ PAGE_ACCESS_TOKEN not set - Messenger won't work")

    if not WHATSAPP_TOKEN:
        logger.warning("⚠️ WHATSAPP_TOKEN not set - WhatsApp won't work")

    logger.info(f"🚀 Sky Lines AI Agent starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)
