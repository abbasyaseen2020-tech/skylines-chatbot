# -*- coding: utf-8 -*-
"""
Conversation Store - Persistent Memory for Sky Lines Chatbot
=============================================================
Uses Google Sheets for persistent conversation history + follow-up reminders + leads.
- Saves every message to Google Sheets (survives Railway redeploys)
- Loads conversation history when a returning customer messages
- Background thread checks for inactive users and sends follow-up reminders
- Saves leads persistently to Google Sheets
- Rate limiting protection for Google Sheets API
"""

import os
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from collections import defaultdict
from functools import wraps

logger = logging.getLogger(__name__)


# ============================================
# RATE LIMITING / RETRY FOR GOOGLE SHEETS
# ============================================
_last_api_call = 0
MIN_API_INTERVAL = 1.0  # Minimum seconds between API calls


def rate_limited_retry(max_retries=3, base_delay=2):
    """Decorator: retry with exponential backoff on Google Sheets API errors."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            global _last_api_call
            for attempt in range(max_retries):
                try:
                    # Rate limiting: ensure minimum interval between calls
                    now = time.time()
                    elapsed = now - _last_api_call
                    if elapsed < MIN_API_INTERVAL:
                        time.sleep(MIN_API_INTERVAL - elapsed)
                    _last_api_call = time.time()
                    return func(*args, **kwargs)
                except Exception as e:
                    error_str = str(e).lower()
                    if "quota" in error_str or "rate" in error_str or "429" in error_str:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Rate limited on {func.__name__}, retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(delay)
                    else:
                        raise
            return func(*args, **kwargs)  # Final attempt
        return wrapper
    return decorator

# ============================================
# GOOGLE SHEETS SETUP
# ============================================
_sheets_client = None
_chat_sheet = None
_activity_sheet = None
_leads_sheet = None
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
    global _chat_sheet, _activity_sheet, _leads_sheet
    if _chat_sheet and _activity_sheet and _leads_sheet:
        return _chat_sheet, _activity_sheet, _leads_sheet

    client = _get_gspread_client()
    if not client:
        return None, None, None

    try:
        # Try to open existing spreadsheet
        try:
            spreadsheet = client.open(SHEET_NAME)
            logger.info(f"Opened existing spreadsheet: {SHEET_NAME}")
        except Exception:
            # Create new spreadsheet (owned by service account)
            spreadsheet = client.create(SHEET_NAME)
            logger.info(f"Created new spreadsheet: {SHEET_NAME}")

        # Get or create "messages" worksheet
        try:
            _chat_sheet = spreadsheet.worksheet("messages")
        except Exception:
            _chat_sheet = spreadsheet.add_worksheet(title="messages", rows=10000, cols=6)
            _chat_sheet.update('A1:F1', [["user_id", "platform", "role", "message", "timestamp", "user_name"]])
            logger.info("Created 'messages' worksheet")

        # Get or create "activity" worksheet (for tracking follow-ups)
        try:
            _activity_sheet = spreadsheet.worksheet("activity")
        except Exception:
            _activity_sheet = spreadsheet.add_worksheet(title="activity", rows=5000, cols=7)
            _activity_sheet.update('A1:G1', [[
                "user_id", "platform", "last_msg_time", "user_name",
                "last_topic", "follow_up_sent", "follow_up_time"
            ]])
            logger.info("Created 'activity' worksheet")

        # Get or create "leads" worksheet (persistent lead storage)
        try:
            _leads_sheet = spreadsheet.worksheet("leads")
        except Exception:
            _leads_sheet = spreadsheet.add_worksheet(title="leads", rows=5000, cols=8)
            _leads_sheet.update('A1:H1', [[
                "name", "phone", "interest", "platform",
                "user_id", "timestamp", "source", "status"
            ]])
            logger.info("Created 'leads' worksheet")

        # Remove default Sheet1 if it exists
        try:
            default = spreadsheet.worksheet("Sheet1")
            spreadsheet.del_worksheet(default)
        except Exception:
            pass

        return _chat_sheet, _activity_sheet, _leads_sheet

    except Exception as e:
        logger.error(f"Failed to setup spreadsheet: {e}")
        return None, None, None


# ============================================
# SAVE & LOAD CONVERSATIONS
# ============================================
@rate_limited_retry(max_retries=3)
def save_message(user_id, platform, role, message, user_name=""):
    """Save a single message to Google Sheets."""
    try:
        chat_sheet, activity_sheet, _ = _get_or_create_spreadsheet()
        if not chat_sheet:
            return False

        now = datetime.now().isoformat()

        # Save to messages sheet
        chat_sheet.append_row([
            str(user_id), platform, role, message, now, user_name
        ])

        # Update activity tracking (only for user messages)
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

        # Search for existing user row
        try:
            cell = activity_sheet.find(str(user_id), in_column=1)
            row = cell.row
            # Update existing row
            activity_sheet.update(f'C{row}:E{row}', [[timestamp, user_name, message[:100]]])
            # Reset follow-up sent flag
            activity_sheet.update(f'F{row}', [["no"]])
        except Exception:
            # New user - add row
            activity_sheet.append_row([
                str(user_id), platform, timestamp, user_name,
                message[:100], "no", ""
            ])

    except Exception as e:
        logger.error(f"Failed to update activity: {e}")


@rate_limited_retry(max_retries=3)
def load_history(user_id, max_messages=10):
    """Load conversation history for a returning user from Google Sheets."""
    try:
        chat_sheet, _, _ = _get_or_create_spreadsheet()
        if not chat_sheet:
            return []

        # Get all records
        all_records = chat_sheet.get_all_records()

        # Filter for this user
        user_messages = [
            r for r in all_records
            if str(r.get("user_id", "")) == str(user_id)
        ]

        # Get last N messages
        recent = user_messages[-max_messages:] if len(user_messages) > max_messages else user_messages

        # Convert to Claude conversation format
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

        # Build a summary string for the AI
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
        _, activity_sheet, _ = _get_or_create_spreadsheet()
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

                # Send follow-up between 2-72 hours of inactivity
                hours_inactive = diff.total_seconds() / 3600
                if hours_inactive >= 2 and hours_inactive < 72:
                    inactive.append({
                        "user_id": user_id,
                        "platform": platform,
                        "user_name": record.get("user_name", ""),
                        "last_topic": record.get("last_topic", ""),
                        "hours_inactive": round(hours_inactive, 1)
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
        _, activity_sheet, _ = _get_or_create_spreadsheet()
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

    # Default follow-up
    return f"أهلاً {name_part} 👋\nتواصلنا قبل كده وحبيت أتأكد إنك لقيت كل المعلومات اللي محتاجها. لو عندك أي سؤال أنا موجود 😊"


# ============================================
# PERSISTENT LEADS STORAGE
# ============================================
@rate_limited_retry(max_retries=3)
def save_lead_to_sheets(lead):
    """Save a lead persistently to Google Sheets."""
    try:
        _, _, leads_sheet = _get_or_create_spreadsheet()
        if not leads_sheet:
            logger.warning("Leads sheet not available - lead not persisted")
            return False

        # Check for duplicate by phone number
        try:
            existing = leads_sheet.find(str(lead.get("phone", "")), in_column=2)
            if existing:
                logger.info(f"Lead already exists for phone {lead.get('phone')} - updating")
                row = existing.row
                leads_sheet.update(f'A{row}:H{row}', [[
                    lead.get("name", ""),
                    lead.get("phone", ""),
                    lead.get("interest", "غير محدد"),
                    lead.get("platform", ""),
                    lead.get("user_id", ""),
                    lead.get("timestamp", datetime.now().isoformat()),
                    lead.get("source", "auto"),
                    lead.get("status", "new")
                ]])
                return True
        except Exception:
            pass  # Not found — will add new row

        # Add new lead
        leads_sheet.append_row([
            lead.get("name", ""),
            lead.get("phone", ""),
            lead.get("interest", "غير محدد"),
            lead.get("platform", ""),
            lead.get("user_id", ""),
            lead.get("timestamp", datetime.now().isoformat()),
            lead.get("source", "auto"),
            lead.get("status", "new")
        ])
        logger.info(f"Lead saved to Sheets: {lead.get('name', 'Unknown')} - {lead.get('phone', 'N/A')}")
        return True

    except Exception as e:
        logger.error(f"Failed to save lead to Sheets: {e}")
        return False


@rate_limited_retry(max_retries=3)
def get_all_leads():
    """Get all leads from Google Sheets."""
    try:
        _, _, leads_sheet = _get_or_create_spreadsheet()
        if not leads_sheet:
            return []
        return leads_sheet.get_all_records()
    except Exception as e:
        logger.error(f"Failed to get leads: {e}")
        return []


# ============================================
# BACKGROUND REMINDER THREAD
# ============================================
_reminder_thread = None
_reminder_running = False


def start_reminder_thread(send_message_func, interval_seconds=3600):
    """
    Start a background thread that checks for inactive users every hour
    and sends follow-up messages.

    Args:
        send_message_func: function(user_id, text, platform) to send messages
        interval_seconds: how often to check (default: 1 hour)
    """
    global _reminder_thread, _reminder_running

    if _reminder_thread and _reminder_thread.is_alive():
        logger.info("Reminder thread already running")
        return

    _reminder_running = True

    def _reminder_loop():
        logger.info("Follow-up reminder thread started")
        # Wait 5 minutes after startup before first check
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

                        platform = user["platform"]
                        hours = user["hours_inactive"]

                        # Messenger: 24h messaging window for regular messages
                        # WhatsApp: 24h window for regular, templates after that
                        if hours <= 23.5:
                            # Within messaging window — send regular message
                            send_message_func(
                                user["user_id"],
                                msg,
                                platform
                            )
                            mark_follow_up_sent(user["user_id"])
                            logger.info(f"Follow-up sent to {user['user_id']} ({platform}, {hours}h inactive)")
                        elif platform == "whatsapp" and hours <= 72:
                            # WhatsApp outside 24h — use template instead
                            try:
                                from bot import send_whatsapp_template
                                send_whatsapp_template(
                                    user["user_id"],
                                    "follow_up_reminder",
                                    [user.get("user_name", "")]
                                )
                                mark_follow_up_sent(user["user_id"])
                                logger.info(f"WhatsApp template follow-up sent to {user['user_id']} ({hours}h)")
                            except Exception as tmpl_err:
                                logger.warning(f"Template send failed for {user['user_id']}: {tmpl_err}")
                                mark_follow_up_sent(user["user_id"])
                        else:
                            # Outside all messaging windows — mark as done
                            logger.info(f"Skipping {user['user_id']} - outside messaging window ({hours}h)")
                            mark_follow_up_sent(user["user_id"])

                        # Small delay between messages to avoid rate limits
                        time.sleep(3)

                    except Exception as e:
                        logger.error(f"Failed to send follow-up to {user['user_id']}: {e}")

            except Exception as e:
                logger.error(f"Reminder loop error: {e}")

            # Wait for next check
            time.sleep(interval_seconds)

    _reminder_thread = threading.Thread(target=_reminder_loop, daemon=True)
    _reminder_thread.start()
    logger.info("Follow-up reminder thread launched")


def stop_reminder_thread():
    """Stop the background reminder thread."""
    global _reminder_running
    _reminder_running = False
    logger.info("Reminder thread stopping")
