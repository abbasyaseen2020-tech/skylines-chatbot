# -*- coding: utf-8 -*-
"""
Conversation Store - Persistent Memory for Sky Lines Chatbot
=============================================================
Uses Google Sheets for persistent conversation history + follow-up reminders.
- Saves every message to Google Sheets (survives Railway redeploys)
- Loads conversation history when a returning customer messages
- Background thread checks for inactive users and sends follow-up reminders
"""

import os
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

# ============================================
# GOOGLE SHEETS SETUP
# ============================================
_sheets_client = None
_chat_sheet = None
_activity_sheet = None
SHEET_NAME = "SkyLines_ChatMemory"

def _get_gspread_client():
    """Get or create gspread client using service account credentials."""
    global _sheets_client
    if _sheets_client:
        return _sheets_client
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
        if not creds_json:
            logger.warning("GOOGLE_CREDENTIALS_JSON not set - conversation memory disabled")
            return None

        creds_data = json.loads(creds_json)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        credentials = Credentials.from_service_account_info(creds_data, scopes=scopes)
        _sheets_client = gspread.authorize(credentials)
        logger.info("Google Sheets client initialized for conversation memory")
        return _sheets_client
    except Exception as e:
        logger.error(f"Failed to init Google Sheets client: {e}")
        return None


def _get_or_create_spreadsheet():
    """Get or create the chat memory spreadsheet."""
    global _chat_sheet, _activity_sheet
    if _chat_sheet and _activity_sheet:
        return _chat_sheet, _activity_sheet

    client = _get_gspread_client()
    if not client:
        return None, None

    try:
        try:
            spreadsheet = client.open(SHEET_NAME)
            logger.info(f"Opened existing spreadsheet: {SHEET_NAME}")
        except Exception:
            spreadsheet = client.create(SHEET_NAME)
            logger.info(f"Created new spreadsheet: {SHEET_NAME}")

        try:
            _chat_sheet = spreadsheet.worksheet("messages")
        except Exception:
            _chat_sheet = spreadsheet.add_worksheet(title="messages", rows=10000, cols=6)
            _chat_sheet.update('A1:F1', [["user_id", "platform", "role", "message", "timestamp", "user_name"]])
            logger.info("Created 'messages' worksheet")

        try:
            _activity_sheet = spreadsheet.worksheet("activity")
        except Exception:
            _activity_sheet = spreadsheet.add_worksheet(title="activity", rows=5000, cols=7)
            _activity_sheet.update('A1:G1', [[
                "user_id", "platform", "last_msg_time", "user_name",
                "last_topic", "follow_up_sent", "follow_up_time"
            ]])
            logger.info("Created 'activity' worksheet")

        try:
            default = spreadsheet.worksheet("Sheet1")
            spreadsheet.del_worksheet(default)
        except Exception:
            pass

        return _chat_sheet, _activity_sheet

    except Exception as e:
        logger.error(f"Failed to setup spreadsheet: {e}")
        return None, None


# ============================================
# SAVE & LOAD CONVERSATIONS
# ============================================
def save_message(user_id, platform, role, message, user_name=""):
    """Save a single message to Google Sheets."""
    try:
        chat_sheet, activity_sheet = _get_or_create_spreadsheet()
        if not chat_sheet:
            return False

        now = datetime.now().isoformat()

        chat_sheet.append_row([
            str(user_id), platform, role, message, now, user_name
        ])

        if role == "user":
            _update_activity(activity_sheet, user_id, platform, now, user_name, message)

        return True
    except Exception as e:
        logger.error(f"Failed to save message: {e}")
        return False


def _update_activity(activity_sheet, user_id, platform, timestamp, user_name, message):
    """Update the activity tracker for follow-up reminders."""
    try:
        if not activity_sheet:
            return

        try:
            cell = activity_sheet.find(str(user_id), in_column=1)
            row = cell.row
            activity_sheet.update(f'C{row}:E{row}', [[timestamp, user_name, message[:100]]])
            activity_sheet.update(f'F{row}', [["no"]])
        except Exception:
            activity_sheet.append_row([
                str(user_id), platform, timestamp, user_name,
                message[:100], "no", ""
            ])

    except Exception as e:
        logger.error(f"Failed to update activity: {e}")


def load_history(user_id, max_messages=10):
    """Load conversation history for a returning user from Google Sheets."""
    try:
        chat_sheet, _ = _get_or_create_spreadsheet()
        if not chat_sheet:
            return []

        all_records = chat_sheet.get_all_records()

        user_messages = [
            r for r in all_records
            if str(r.get("user_id", "")) == str(user_id)
        ]

        recent = user_messages[-max_messages:] if len(user_messages) > max_messages else user_messages

        history = []
        for msg in recent:
            role = msg.get("role", "user")
            content = msg.get("message", "")
            if role in ("user", "assistant") and content:
                history.append({"role": role, "content": content})

        if history:
            logger.info(f"Loaded {len(history)} messages from history for user {user_id}")

        return history

    except Exception as e:
        logger.error(f"Failed to load history: {e}")
        return []


def get_conversation_summary(user_id):
    """Get a brief summary of past conversation for the AI context."""
    try:
        history = load_history(user_id, max_messages=6)
        if not history:
            return ""

        summary_parts = []
        for msg in history:
            role_label = "العميل" if msg["role"] == "user" else "أنتِ"
            text = msg["content"][:150]
            summary_parts.append(f"{role_label}: {text}")

        summary = "\n".join(summary_parts)
        return f"""
## ملخص المحادثة السابقة مع العميل ده:
(العميل ده كلمنا قبل كده - راجعي المحادثة السابقة وكملي من حيث وقفتوا)
{summary}

⚠️ مهم: متسأليش العميل أسئلة سألتيها قبل كده. كملي المحادثة بشكل طبيعي.
"""

    except Exception as e:
        logger.error(f"Failed to get conversation summary: {e}")
        return ""


# ============================================
# FOLLOW-UP REMINDERS
# ============================================
def get_inactive_users(hours=24):
    """Get users who haven't responded in X hours and haven't been followed up."""
    try:
        _, activity_sheet = _get_or_create_spreadsheet()
        if not activity_sheet:
            return []

        all_records = activity_sheet.get_all_records()
        now = datetime.now()
        inactive = []

        for record in all_records:
            try:
                last_msg = record.get("last_msg_time", "")
                follow_up_sent = record.get("follow_up_sent", "no")
                user_id = record.get("user_id", "")
                platform = record.get("platform", "")

                if not last_msg or not user_id or follow_up_sent == "yes":
                    continue

                last_time = datetime.fromisoformat(last_msg)
                diff = now - last_time

                if diff >= timedelta(hours=hours) and diff < timedelta(hours=hours * 3):
                    inactive.append({
                        "user_id": user_id,
                        "platform": platform,
                        "user_name": record.get("user_name", ""),
                        "last_topic": record.get("last_topic", ""),
                        "hours_inactive": round(diff.total_seconds() / 3600, 1)
                    })
            except Exception:
                continue

        return inactive

    except Exception as e:
        logger.error(f"Failed to get inactive users: {e}")
        return []


def mark_follow_up_sent(user_id):
    """Mark that a follow-up was sent to this user."""
    try:
        _, activity_sheet = _get_or_create_spreadsheet()
        if not activity_sheet:
            return

        cell = activity_sheet.find(str(user_id), in_column=1)
        if cell:
            now = datetime.now().isoformat()
            activity_sheet.update(f'F{cell.row}:G{cell.row}', [["yes", now]])

    except Exception as e:
        logger.error(f"Failed to mark follow-up: {e}")


def generate_follow_up_message(user_name, last_topic):
    """Generate a natural follow-up message based on context."""
    name_part = f"يا {user_name}" if user_name else ""

    if any(w in last_topic for w in ["سعر", "كام", "تقسيط", "مقدم"]):
        return f"أهلاً {name_part} 👋\nلسه مهتم تعرف تفاصيل الأسعار والتقسيط؟ أنا موجود لو عايز أي معلومة 😊"

    if any(w in last_topic for w in ["شقة", "شقق", "فيلا", "محل", "مكتب"]):
        return f"أهلاً {name_part} 👋\nلسه بتدور على وحدة؟ لو محتاج مساعدة في الاختيار أنا هنا 😊"

    if any(w in last_topic for w in ["حجز", "موعد", "زيارة", "معاينة"]):
        return f"أهلاً {name_part} 👋\nلسه عايز ترتب زيارة للموقع؟ نقدر نحجزلك في أي وقت يناسبك 😊"

    return f"أهلاً {name_part} 👋\nتواصلنا قبل كده وحبيت أتأكد إنك لقيت كل المعلومات اللي محتاجها. لو عندك أي سؤال أنا موجود 😊"


# ============================================
# BACKGROUND REMINDER THREAD
# ============================================
_reminder_thread = None
_reminder_running = False


def start_reminder_thread(send_message_func, interval_seconds=3600):
    """Start background thread that checks for inactive users every hour."""
    global _reminder_thread, _reminder_running

    if _reminder_thread and _reminder_thread.is_alive():
        logger.info("Reminder thread already running")
        return

    _reminder_running = True

    def _reminder_loop():
        logger.info("Follow-up reminder thread started")
        time.sleep(300)

        while _reminder_running:
            try:
                inactive_users = get_inactive_users(hours=24)
                logger.info(f"Found {len(inactive_users)} inactive users for follow-up")

                for user in inactive_users:
                    try:
                        msg = generate_follow_up_message(
                            user["user_name"],
                            user["last_topic"]
                        )

                        if user["hours_inactive"] <= 24:
                            send_message_func(
                                user["user_id"],
                                msg,
                                user["platform"]
                            )
                            mark_follow_up_sent(user["user_id"])
                            logger.info(f"Follow-up sent to {user['user_id']} ({user['platform']})")
                        else:
                            logger.info(f"Skipping {user['user_id']} - outside messaging window ({user['hours_inactive']}h)")
                            mark_follow_up_sent(user["user_id"])

                        time.sleep(2)

                    except Exception as e:
                        logger.error(f"Failed to send follow-up to {user['user_id']}: {e}")

            except Exception as e:
                logger.error(f"Reminder loop error: {e}")

            time.sleep(interval_seconds)

    _reminder_thread = threading.Thread(target=_reminder_loop, daemon=True)
    _reminder_thread.start()
    logger.info("Follow-up reminder thread launched")


def stop_reminder_thread():
    """Stop the background reminder thread."""
    global _reminder_running
    _reminder_running = False
    logger.info("Reminder thread stopping")
