# -*- coding: utf-8 -*-
"""
Sky Lines - Knowledge Base & System Prompt (Updated)
====================================================
Contains: System prompt, company info, comment keywords,
project details, Google Sheets integration, and helper functions.

التحديثات:
- إضافة Google Sheets integration لقراءة بيانات المشاريع مباشرة
- تحسين SYSTEM_PROMPT لحل 6 مشاكل رئيسية
- إضافة تعريف مختصر عن المشروع قبل التفاصيل
- تحسين طلب رقم الهاتف
- اهتمام خاص بالعملاء من خارج مصر
"""

import os
import json
import logging
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

logger = logging.getLogger(__name__)

# ==============================================
# GOOGLE SHEETS INTEGRATION
# ==============================================

GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "17KQ-K40_j92vhQmJSeJJZMzChr-MdXdCoCyjegHRqlU")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")

_sheets_cache = {
    "data": None,
    "last_fetch": None,
    "cache_ttl": 300  # 5 minutes cache
}

def get_sheets_client():
    """Get authenticated Google Sheets client"""
    if not GOOGLE_CREDENTIALS_JSON:
        logger.warning("GOOGLE_CREDENTIALS_JSON not set - using hardcoded data")
        return None

    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly"
        ]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(credentials)
        return client
    except Exception as e:
        logger.error(f"Failed to create Sheets client: {e}")
        return None

def fetch_projects_from_sheet():
    """Fetch all project data from Google Sheet"""
    now = datetime.now()

    # Check cache
    if (_sheets_cache["data"] is not None and
        _sheets_cache["last_fetch"] is not None and
        (now - _sheets_cache["last_fetch"]).seconds < _sheets_cache["cache_ttl"]):
        return _sheets_cache["data"]

    client = get_sheets_client()
    if not client:
        return None

    try:
        spreadsheet = client.open_by_key(GOOGLE_SHEETS_ID)
        projects = {}

        for worksheet in spreadsheet.worksheets():
            title = worksheet.title
            # Skip non-project sheets
            if title in ["ملخص المشاريع", "إعدادات البوت", "تعليمات الاستخدام"]:
                continue

            all_values = worksheet.get_all_values()
            if not all_values:
                continue

            project = parse_project_sheet(all_values, title)
            if project:
                projects[title] = project

        # Update cache
        _sheets_cache["data"] = projects
        _sheets_cache["last_fetch"] = now

        logger.info(f"Fetched {len(projects)} projects from Google Sheet")
        return projects

    except Exception as e:
        logger.error(f"Failed to fetch from Google Sheet: {e}")
        return _sheets_cache.get("data")  # Return stale cache if available

def parse_project_sheet(values, sheet_name):
    """Parse a project sheet into structured data"""
    project = {
        "name": sheet_name,
        "info": {},
        "offers": [],
        "units": []
    }

    # Parse project info (rows 2-12, columns A-B)
    info_keys = [
        "اسم المشروع", "المطور", "الموقع", "أقرب معلم / منطقة",
        "وصف المشروع", "نوع المشروع", "حالة المشروع",
        "تاريخ التسليم المتوقع", "رقم مبيعات المشروع",
        "رابط موقع المشروع", "ملاحظات عامة"
    ]

    for i, key in enumerate(info_keys):
        row_idx = i + 1  # Row 2 onwards (0-indexed: row 1)
        if row_idx < len(values) and len(values[row_idx]) > 1:
            project["info"][key] = values[row_idx][1]

    # Parse offers (rows 16-20)
    for i in range(15, min(20, len(values))):
        row = values[i]
        if len(row) >= 2 and row[1]:  # Has description
            project["offers"].append({
                "number": row[0] if row[0] else "",
                "description": row[1] if len(row) > 1 else "",
                "start_date": row[2] if len(row) > 2 else "",
                "end_date": row[3] if len(row) > 3 else "",
                "applies_to": row[4] if len(row) > 4 else "",
                "notes": row[5] if len(row) > 5 else ""
            })

    # Parse units (rows 25 onwards)
    for i in range(24, len(values)):
        row = values[i]
        if len(row) < 5 or not row[0]:  # Skip empty rows
            continue

        unit = {
            "number": row[0],
            "type": row[1] if len(row) > 1 else "",
            "floor": row[2] if len(row) > 2 else "",
            "area": row[3] if len(row) > 3 else "",
            "price_per_meter": row[4] if len(row) > 4 else "",
            "total_price": row[5] if len(row) > 5 else "",
            "down_payment_pct": row[6] if len(row) > 6 else "",
            "down_payment_amount": row[7] if len(row) > 7 else "",
            "installment_months": row[8] if len(row) > 8 else "",
            "monthly_installment": row[9] if len(row) > 9 else "",
            "status": row[10] if len(row) > 10 else "",
            "special_offer": row[11] if len(row) > 11 else "",
            "bedrooms": row[12] if len(row) > 12 else "",
            "notes": row[13] if len(row) > 13 else ""
        }
        project["units"].append(unit)

    return project

def format_sheet_data_for_prompt():
    """Format Google Sheet data as text for the AI prompt"""
    projects = fetch_projects_from_sheet()
    if not projects:
        return ""

    text = "\n\n# بيانات المشاريع المحدثة من Google Sheet\n"

    for name, project in projects.items():
        info = project.get("info", {})
        text += f"\n## مشروع: {info.get('اسم المشروع', name)}\n"

        if info.get("الموقع"):
            text += f"الموقع: {info['الموقع']}\n"
        if info.get("وصف المشروع"):
            text += f"الوصف: {info['وصف المشروع']}\n"
        if info.get("نوع المشروع"):
            text += f"النوع: {info['نوع المشروع']}\n"
        if info.get("حالة المشروع"):
            text += f"الحالة: {info['حالة المشروع']}\n"
        if info.get("تاريخ التسليم المتوقع"):
            text += f"التسليم: {info['تاريخ التسليم المتوقع']}\n"

        # Offers
        offers = project.get("offers", [])
        if offers:
            text += "\n### العروض الحالية:\n"
            for offer in offers:
                if offer.get("description"):
                    text += f"- {offer['description']}"
                    if offer.get("end_date"):
                        text += f" (حتى {offer['end_date']})"
                    text += "\n"

        # Available units
        units = project.get("units", [])
        available = [u for u in units if u.get("status") == "متاح"]
        reserved = [u for u in units if u.get("status") == "محجوز"]
        sold = [u for u in units if u.get("status") == "مباع"]

        text += f"\n### الوحدات: إجمالي {len(units)} — متاح {len(available)} — محجوز {len(reserved)} — مباع {len(sold)}\n"

        if available:
            text += "\n### الوحدات المتاحة:\n"
            for u in available:
                unit_type = u.get("type", "")
                text += f"- وحدة {u['number']}: {unit_type} — {u.get('area', '')} م²"
                if u.get("total_price"):
                    text += f" — الإجمالي: {u['total_price']} ج"
                if u.get("down_payment_amount"):
                    text += f" — مقدم: {u['down_payment_amount']} ج"
                if u.get("monthly_installment"):
                    text += f" — قسط: {u['monthly_installment']} ج/{u.get('installment_months', '')} شهر"
                if u.get("special_offer"):
                    text += f" — عرض: {u['special_offer']}"
                text += "\n"

        # Sold units (just mention they're sold, no details)
        if sold:
            sold_numbers = [u["number"] for u in sold]
            text += f"\n⚠️ وحدات مباعة (لا تعرضيها): {', '.join(sold_numbers)}\n"

    return text


# ==============================================
# SYSTEM PROMPT (Updated - All 6 issues fixed)
# ==============================================
SYSTEM_PROMPT = """
# هوية أساسية
اسمك "أسيل" — أنتِ مساعدة مبيعات ذكية في شركة Sky Lines للاستثمار والتطوير العقاري.
بتتكلمي بالعامية المصرية بأسلوب ودود وطبيعي.
ممنوع تقولي إنك بوت أو AI أبداً — لو حد سألك قولي "لا طبعاً! أنا أسيل من فريق Sky Lines، تحت أمرك!"

# هوية الشركة
- الاسم: Sky Lines للاستثمار والتطوير العقاري
- الشعار: "رؤيتك هي سكاي لاينز بتاعتنا — Your Vision is Our Skylines"
- رقم التواصل: 01055993391
- الموقع: www.skylinesdevelopments.com

# هدفك الأساسي
1. تفهمي طلب العميل كويس
2. تقترحي الوحدة المناسبة ليه
3. تاخدي رقم تليفونه + تحددي موعد مكالمة أو زيارة
كل ده بطريقة طبيعية ومحترفة — مش تضغطي عليه.

# ⚠️ قاعدة أسلوب الرد — صارمة جداً
- الرد = سطر أو اتنين بالكتير. ممنوع 3 سطور إلا لو بتعرضي كارد وحدة
- كل رد لازم يكون زي رسالة واتساب سريعة
- سؤال واحد بس في كل رد
- بلاش مقدمات طويلة — ادخلي في الموضوع

# ⚠️ أول رسالة لعميل جديد — قاعدة مهمة
ابدأي بتعريف مختصر عن المشروع اللي العميل سأل عنه (جملة أو اتنين) وبعدين اسألي عن احتياجه.
مثال: "مساء الخير! أنا أسيل من Sky Lines. مشروع Sky Villas M7 في الحي الرابع ببني سويف — تصميم كلاسيكي أوروبي فاخر بوحدات سكنية وتجارية وإدارية. حضرتك بتدور على سكن ولا استثمار؟"

# ⚠️ قاعدة مهمة جداً بخصوص الأسعار والوحدات
- عند سؤال العميل عن الأسعار أو الوحدات، افترضي دائماً أنه يسأل عن الوحدات السكنية وأعطيه أسعار السكني فقط.
- لا تذكري أبداً عرض "سعر الإداري بسعر السكني" أو أي عرض خاص بالوحدات الإدارية إلا إذا طلب العميل تحديداً وحدة إدارية.
- الغالبية العظمى من العملاء يسألون عن الوحدات السكنية.
- إذا سأل العميل "كام سعر المتر؟" أو "كام سعر الوحدة؟" بدون تحديد النوع، أجيبي بأسعار السكني فقط.
- فقط إذا قال العميل صراحة "عايز وحدة إدارية" أو "كام سعر الإداري؟"، ساعتها اذكري أسعار الإداري والعرض الخاص.

# ⚠️ طلب رقم الهاتف — بطريقة محترمة
- لما توصلي لمرحلة طلب الرقم، اسألي العميل بطريقة لطيفة واديله اختيار:
  "عشان أوصل حضرتك بفريق المبيعات — تحب التواصل يكون واتساث ولا مكالمة تليفون؟ 😊"
- لو العميل ادّاك رقمه، اشكريه وأكدي إن السيلز هيتواصل معاه قريب.
- لو رفض يسيب رقمه، احترمي قراره وابعتيله بيانات التواصل بالشركة.

# ⚠️ الاهتمام بالعملاء من خار�g مصر (VIP)
- لو لاحظتي إن العميل بيتكلم من خار�g مصر (ذكر بلد تاني، أو رقم دولي، أو لهجة مختلفة):
  - اهتمي بيه جداً — دول عملاء محتملين كبار
  - اسأليه عن البلد اللي هو فيها
  - وضحيله إن الشركة بتسهل كل إجراءات الشراء للمصريين في الخارج
  - اعرضي عليه إمكانية عمل فيديو كول لمعاينة المشروع
  - أكدي إن فريق المبيعات يقدر يتواصل معاه على واتساب الدولي

# ⚠️ التعامل مع اسم العميل
- أول رسالة فقط → "أهلاً بحضرتك" أو اسمه الأول مرة واحدة
- بعد كده → استخدمي "حضرتك" بس

# ⚠️ مراجعة الرسايل القديمة
- قبل ما تردي، راجعي المحادثة القديمة كويس
- لو العميل رجع بعد فترة → كملي من حيث ما وقفتوا

# ⚠️ عرض الوحدات بشكل كارد
لما العميل يسأل عن وحدة أو عن المتاح، اعرضي كل وحدة كده:
🏢 وحدة [رقم]
━━━━━━━━━━━━━━━
📐 المساحة: [المساحة] م²
💰 سعر المتر: [سعر المتر] ج
🏷️ الإجمالي: [السعر الكامل] ج
💳 مقدم: [المقدم] ج
📅 القسط: [القسط] ج / [عدد الأشهر] شهر
✅ الحالة: متاح
━━━━━━━━━━━━━━━

# ⚠️ الوحدات المباعة
- لو وحدة حالتها "مباع" → ممنوع تعرضيها أو تقولي إنها متاحة
- لو وحدة حالتها "محجوز" → قولي إنها محجوزة واقترحي بدائل

# قواعد ذهبية
- ممنوع تخترعي أسعار أو مساحات
- ممنوع تضمني حاجة مش مؤكدة
- لو مش متأكدة → وجهي للسيلز
- ممنوع تقولي إنك روبوت
- نوّعي في أسلوبك عشان تبانِي إنسان
- لازم تشتغلي كسيلز إيجنت محترف — تفهمي طلب العميل وتقترحي الأنسب

# القاعدة النهائية
لو العميل مسابش رقمه:
📞 01055993391
📧 info@skylinesdevelopments.com
🌐 www.skylinesdevelopments.com
"حضرتك تقدر تتواصل معانا في أي وقت، وأنا هنا لو احتجت أي حاجة!"
"""


# ==============================================
# COMPANY INFO
# ==============================================
COMPANY_INFO = {
    "name": "Sky Lines",
    "name_full": "Sky Lines للاستثمار والتطوير العقاري",
    "slogan_ar": "رؤيتك هي سكاي لاينز بتاعتنا",
    "slogan_en": "Your Vision is Our Skylines",
    "phone": "01055993391",
    "website": "www.skylinesdevelopments.com",
    "location": "بني سويف",
}


# ==============================================
# PROJECT 1: SKY VILLAS M7 (Hardcoded fallback)
# ==============================================
SKY_VILLAS_M7 = """
## مشروع Sky Villas M7 — الحي الرابع، بني سويف

المطور: Sky Lines للاستثمار والتطوير العقاري
الموقع: بني سويف — الحي الرابع
موعد التسليم: 1 يوليو 2027
نظام السداد: مقدم 30% والباقى أقساط شهرية على 14 شهر
رقم التواصل: 01055993391

### نظام التسعير:
- سعر الوحدة = سعر المتر × المساحة
- رسوم خدمات (جراج + أسانسير + عدادات) = 180,000 ج (أدوار 1-4)
- رسوم خدمات تجاري (أرضي) = 100,000 ج
- الإجمالي = سعر الوحدة + رسوم الخدمات

### تقسيم الأدوار:
- الأرضي: تجاري — 6 محلات — سعر المتر 35,000 ج
- الأول: إداري — 3 وحدات — سعر المتر 15,000 ج
- الثاني-الرابع: سكني — سعر المتر 15,000 ج
- الروف: سكني

### نقاط القوة:
- موقع مميز في الحي الرابع
- تقسيط مريح على 14 شهر
- تسليم قريب: يوليو 2027
- تصميم كلاسيكي أوروبي فاخر
"""


# ==============================================
# PROJECT 2: ABRAJ AL-RAMAD (Hardcoded fallback)
# ==============================================
ABRAJ_ALRAMAD = """
## مشروع أبراج مصطفى الغمراوي — الرمد، غرب النيل، بني سويف

نوع المشروع: سكني بنظام الأسهم واتحاد الملاك
الموقع: منطقة الرمد — بني سويف — غرب النيل
مساحة المشروع: 20,300 م²

### نظام الأسهم:
- سعر السهم: 250,000 ج كاش
- كل سهم = 5 م² ملكية أرض + 45-50 م² مساحة سكنية تقريبي
- التخصيص بالقرعة بعد انتهاء البناء

### السداد:
1. دفعات الأرض: كاش عند الدخول
2. دفعات المباني: تبدأ لاحقاً ≈ 200,000 ج/سهم (تقديري)
"""


# ==============================================
# COMPLETE SYSTEM PROMPT
# ==============================================
def get_system_prompt():
    """Get the complete system prompt with all project details"""
    prompt = SYSTEM_PROMPT + "\n\n" + SKY_VILLAS_M7 + "\n\n" + ABRAJ_ALRAMAD

    # Try to get live data from Google Sheets
    sheet_data = format_sheet_data_for_prompt()
    if sheet_data:
        prompt += "\n\n# ⚠️ البيانات التالية من Google Sheet (محدثة ومُقدَّمة على البيانات الثابتة أعلاه)\n"
        prompt += sheet_data
        prompt += "\n\n⚠️ لو فيه تعارض بين بيانات الشيت والبيانات الثابتة، استخدمي بيانات الشيت لأنها أحدث."

    return prompt


# ==============================================
# COMMENT KEYWORDS
# ==============================================
COMMENT_KEYWORDS = [
    "سعر", "كام", "تقسيط", "مقدم", "شقة", "شقق", "فيلا", "فيلات",
    "محل", "مكتب", "إداري", "تجاري", "سكني", "مساحة", "متاح",
    "حجز", "موعد", "زيارة", "عنوان", "فين", "موقع", "تسليم",
    "استلام", "رقم", "تواصل", "تليفون", "واتساب",
    "عايز", "عاوز", "محتاج", "استفسار", "معلومات", "تفاصيل",
    "price", "available", "location", "contact",
    "سهم", "أسهم", "ملكية", "قرعة", "رمد",
]

EMOJI_POSITIVE = ["❤", "👍", "🔥", "😍", "💪", "👏", "💯", "🙏", "😊", "♥", "💕", "💖", "⭐", "🌟", "✨"]
EMOJI_RESPONSES = ["🙏❤️", "❤️🙏", "💪🔥", "😊❤️", "🙏✨", "❤️✨"]
THANK_WORDS = ["شكراً", "شكرا", "شكر", "ممتاز", "جميل", "حلو", "رائع", "تسلم", "الله ينور", "برافو", "ماشاء الله", "احسنت"]


# ==============================================
# HELPER FUNCTIONS
# ==============================================
def format_projects_for_search():
    return {
        "company": COMPANY_INFO,
        "main_project": "Sky Villas M7",
        "other_projects": ["أبراج مصطفى الغمراوي — الرمد"],
    }
