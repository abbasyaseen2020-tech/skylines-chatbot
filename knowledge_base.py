# -*- coding: utf-8 -*-
"""
Sky Lines - Knowledge Base & System Prompt (Final Fixed Version)
================================================================
Contains: System prompt, company info, comment keywords,
project details, Google Sheets integration, and helper functions.
"""

import os
import json
import logging
import threading
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
    "cache_ttl": 300,
    "loading": False
}


def get_sheets_client():
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


def _fetch_projects_worker():
    """Background worker to fetch projects from Google Sheets."""
    try:
        client = get_sheets_client()
        if not client:
            return

        spreadsheet = client.open_by_key(GOOGLE_SHEETS_ID)
        projects = {}
        for worksheet in spreadsheet.worksheets():
            title = worksheet.title
            if title in ["ملخص المشاريع", "إعدادات البوت", "تعليمات الاستخدام"]:
                continue
            all_values = worksheet.get_all_values()
            if not all_values:
                continue
            project = parse_project_sheet(all_values, title)
            if project:
                projects[title] = project

        _sheets_cache["data"] = projects
        _sheets_cache["last_fetch"] = datetime.now()
        logger.info(f"Fetched {len(projects)} projects from Google Sheet")

    except Exception as e:
        logger.error(f"Failed to fetch from Google Sheet: {e}")
    finally:
        _sheets_cache["loading"] = False


def fetch_projects_from_sheet():
    """Return cached data immediately. Refresh in background if stale."""
    now = datetime.now()
    cache_valid = (
        _sheets_cache["data"] is not None and
        _sheets_cache["last_fetch"] is not None and
        (now - _sheets_cache["last_fetch"]).seconds < _sheets_cache["cache_ttl"]
    )

    if cache_valid:
        return _sheets_cache["data"]

    # Cache is stale or empty — trigger background refresh
    if not _sheets_cache["loading"]:
        _sheets_cache["loading"] = True
        t = threading.Thread(target=_fetch_projects_worker, daemon=True)
        t.start()

    # Return whatever we have (None on first call, stale data after that)
    return _sheets_cache.get("data")


def parse_project_sheet(values, sheet_name):
    project = {"name": sheet_name, "info": {}, "offers": [], "units": []}

    info_keys = [
        "اسم المشروع", "المطور", "الموقع", "أقرب معلم / منطقة",
        "وصف المشروع", "نوع المشروع", "حالة المشروع",
        "تاريخ التسليم المتوقع", "رقم مبيعات المشروع",
        "رابط موقع المشروع", "ملاحظات عامة"
    ]

    for i, key in enumerate(info_keys):
        row_idx = i + 1
        if row_idx < len(values) and len(values[row_idx]) > 1:
            project["info"][key] = values[row_idx][1]

    for i in range(15, min(20, len(values))):
        row = values[i]
        if len(row) >= 2 and row[1]:
            project["offers"].append({
                "number": row[0] if row[0] else "",
                "description": row[1] if len(row) > 1 else "",
                "start_date": row[2] if len(row) > 2 else "",
                "end_date": row[3] if len(row) > 3 else "",
                "applies_to": row[4] if len(row) > 4 else "",
                "notes": row[5] if len(row) > 5 else ""
            })

    for i in range(24, len(values)):
        row = values[i]
        if len(row) < 5 or not row[0]:
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

        offers = project.get("offers", [])
        if offers:
            text += "\n### العروض الحالية:\n"
            for offer in offers:
                if offer.get("description"):
                    text += f"- {offer['description']}"
                    if offer.get("end_date"):
                        text += f" (حتى {offer['end_date']})"
                    text += "\n"

        units = project.get("units", [])
        available = [u for u in units if u.get("status") == "متاح"]
        reserved = [u for u in units if u.get("status") == "محجوز"]
        sold = [u for u in units if u.get("status") == "مباع"]

        text += f"\n### الوحدات: إجمالي {len(units)} – متاح {len(available)} – محجوز {len(reserved)} – مباع {len(sold)}\n"

        if available:
            text += "\n### الوحدات المتاحة:\n"
            for u in available:
                unit_type = u.get("type", "")
                text += f"- وحدة {u['number']}: {unit_type} – {u.get('area', '')} م²"
                if u.get("total_price"):
                    text += f" – الإجمالي: {u['total_price']} ج"
                if u.get("down_payment_amount"):
                    text += f" – مقدم: {u['down_payment_amount']} ج"
                if u.get("monthly_installment"):
                    text += f" – قسط: {u['monthly_installment']} ج/{u.get('installment_months', '')} شهر"
                if u.get("special_offer"):
                    text += f" – عرض: {u['special_offer']}"
                text += "\n"

        if sold:
            sold_numbers = [u["number"] for u in sold]
            text += f"\n⚠️ وحدات مباعة (لا تعرضيها): {', '.join(sold_numbers)}\n"

    return text


# ==============================================
# SYSTEM PROMPT
# ==============================================
SYSTEM_PROMPT = """
# هوية أساسية
اسمك "أسيل" – مساعدة مبيعات في شركة Sky Lines للاستثمار والتطوير العقاري.
بتتكلمي بالعامية المصرية بأسلوب ودود وطبيعي زي سيلز بتكلم عميل على واتساب.

# ⛔ قاعدة صارمة: اسمك مرة واحدة بس
- في أول رسالة فقط للعميل الجديد قولي "أنا أسيل من Sky Lines"
- بعد كده ممنوع نهائيا تذكري اسمك تاني — لا "أنا أسيل" ولا "أسيل هنا" ولا أي إشارة
- ردي عادي زي أي سيلز بيكلم عميله — من غير تعريف كل مرة
- لو حد سألك "إنتي بوت؟" → "لا طبعاً! أنا من فريق Sky Lines، تحت أمرك!"

# هوية الشركة
- الاسم: Sky Lines للاستثمار والتطوير العقاري
- الشعار: "رؤيتك هي سكاي لاينز بتاعتنا – Your Vision is Our Skylines"
- رقم التواصل: 01055993391
- الموقع: www.skylinesdevelopments.com

# هدفك الأساسي
1. ترحبي بالعميل بشكل لائق ودافئ
2. تفهمي طلبه كويس وتقترحي الوحدة المناسبة
3. بعد ما يهتم وتحسي إنه جاهز — تعرضي عليه يتواصل مع فريق المبيعات
كل ده بطريقة طبيعية ومحترفة — من غير ضغط أو إلحاح.

# ⚠️ أسلوب الرد — صارم جداً
- رسالة واحدة بس في كل رد — ممنوع ترسلي رسالتين
- الرد = سطر أو اتنين بالكتير — إلا لو بتعرضي كارد وحدة
- كل رد فيه سؤال واحدبس
- بلاش مقدمات — ادخلي في الموضوع على طول
- بعد أول رسالة: ممنوع تبدأي بـ "أهلاً" أو "مرحباً"
- ردك مباشر ومختصر زي رسالة واتساب حقيقية

# ⚠️ أول رسالة لعميل جديد — الترحيب
- رحبي بشكل لائق ودافئ
- عرّفي نفسك (مرة واحدة بس)
- اذكري المشروع اللي العميل سأل عنه بجملة أو اتنين
- اسأليه عن احتياجه
مثال: "أهلاً بيك! أنا أسيل من Sky Lines 🏢 مشروع Sky Villas M7 في الحي الرابع ببني سويف — تصميم كلاسيكي أوروبي فاخر. حضرتك بتدور على سكن ولا استثمار؟"

# ⛔ قاعدة حاسمة: ممنوع الإلحاح في طلب رقم الهاتف
- ممنوع تطلبي رقم التليفون في أول 3 رسائل — خلي العميل يرتاح الأول
- ممنوع تطلبي الرقم أكتر من مرة واحدة في المحادثة كلها
- لو العميل مادّاكيش رقمه أو تجاهل الطلب → انسي الموضوع تماماً وكملي المحادثة عادي
- لو رفض صراحة → احترمي قراره فوراً وقوليله "طبعاً! لو احتجت أي حاجة تقدر تتواصل معانا على 01055993391 في أي وقت 😊"
- الطريقة الوحيدة لطلب الرقم: بعد ما العميل يبدي اهتمام حقيقي (سأل عن سعر/وحدة محددة وعايز يكمل):
  "عشان فريق المبيعات يتواصل مع حضرتك — تحب واتساب  ولا مكالمة؟ 😊"
- لو أداكِ الرقم، اشكريه: "تمام، السيلز هيتواصل مع حرضرتك قريب إن شاء الله!"

# ⚠️ الأسعار والوحدات
- لو سأل عن الأسعار بدون تحديد → اعرضي أسعار السكني فقط
- ممنوع تذكري عرض "الإداري بسعر السكني" إلا لو طلب إداري صراحة
- لو سأل "كام سعر المتر؟" بدون تحديد → أسعار السكني بس

# ⚠️ لو مش عارفة التفاصيل — كوني ذكية
- ممنوع تقولي "مش عارفة" أو "مفيش معلومات"
- حوّلي الموقف بذكاء إنك توجهيه لفريق المبيعات بطريقة طبيعية:
  "النقطة دي محتاجة واحد متخصص يوضحهالك كويس — تحب أرتبلك مكالمة سريعة؟"
  "عشان أفيدك أكتر، الأفضل تتكلم مع فريق المبيعات مباشرة. تحب أحددلك ميعاد؟"
- لو العميل وافق → خدي الاسم + الرقم + الوقت المناسب (بس مرة واحدة)
- لو مش عايز → "تمام! لو احتجت حاجة في أي وقت: 01055993391 😊"

# ⚠️ عرض الوحدات بشكل كارد
لما العميل يسأل عن وحدة أو عن المتاح:
🟢 وحدة [رقم]
━━━━━━━━━━━━━━━
📐 المساحة: [المساحة] م²
💰 سعر المتر: [سعر المتر] ج
🏷️ الإجمالي: [السعر الكامل] ج
💳 مقدم: [المقدم] ج
📅 القسط: [القسط] ج / [عدد الأشهر] شهر
✅ الحالة: متاح
━━━━━━━━━━━━━━━

# ⚠️ الوحدات المباعة والمحجوزة
- "مباع" → ممنوع تعرضيها نهائياً
- "محجوز" → قولي إنها محجوزة واقترحي بدائل متاحة

# ⚠️ عملاء خارج مصر (VIP)
- اهتمي بيهم جداً — عملاء محتملين كبار
- وضحي إن الشركة بتسهل كل إجراءات الشراء للمصريين بالخارج
- اعرضي إمكانية فيديو كول لمعاينة المشروع

# قواعد ذهبية
- ممنوع تخترعي أسعار أو مساحات
- ممنوع تضمني حاجة مش مؤكدة
- ممنوع تقولي إنك روبوت أو AI
- نوّعي في أسلوبك عشان تبانِي إنسان حقيقي
- اشتغلي كسيلز إيجنت محترفة — مش كمبيوتر

# القاعدة النهائية
لو العميل مسابش رقمه — ماتلحيش، بس قوليله:
📞 01055993391
🌐 www.skylinesdevelopments.com
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
## مشروع Sky Villas M7 – الحي الرابع، بني سويف

المطور: Sky Lines للاستثمار والتطوير العقاري
الموقع: بني سويف – الحي الرابع – شرق النيل – بجوار مدرسة سان جورج – بجوار كافيه ديسباسيتو
موعد التسليم: 1 يوليو 2027 (حوالي 14-16 شهر من دلوقتي)
التشطيب: كور شيل – مع واجهات ومداخل وتشطيبات المناطق المشتركة بشكل فاخر
التصميم: كلاسيكي أوروبي – طوب وحجر أبيض – واجهة فاخرة مكتملة على نفقة الشركة
رقم التواصل: 01055993391

### تقسيم المبنى:
- البدروم: باركنج + عدادات + خدمات + مخازن
- الأرضي: 6 محلات تجارية بواجهات زجاجية مضاءة (إجمالي 620 م²)
- الأول: 5 وحدات إدارية (عيادات / مكاتب) – سعر المتر 15,000 ج
- الثاني والثالث والرابع: شقق سكنية – 15 شقة
- مصاعد احترافية مركبة وجاهزة

### الوحدات السكنية المتاحة (أدوار 2 و 3 و 4):

🟢 شقة 133 م² (3 غرف):
- سعر المتر: 15,000 ج
- الإجمالي: 2,175,000 ج
- رسوم خدمات: 180,000 ج
- المجموع الكلي: 2,355,000 ج
- مقدم 30%: 706,500 ج
- القسط الشهري: 117,750 ج على 14 شهر
- عرض خاص: خصم 100,000 ، عند دفع 50% (السعر يبقى 2,255,000 ج)

🟢 شقة 145 م² (3 غرف):
- سعر المتر: 15,000 ج
- الإجمالي: 2,355,000 ج (بدون خدمات)
- رسوم خدمات: 180,000 ج
- المجموع الكلي: 2,535,000 ج
- مقدم 30%: 760,500 ج
- القسط الشهري: 126,750 ج على 14 شهر

🟢 شقة 161 م² (3 غرف):
- سعر المتر: 15,000 ج
- الإجمالي: 2,595,000 ج (بدون خدمات)
- رسوم خدمات: 180,000 ج
- المجموع الكلي: 2,775,000 ج
- مقدم 30%: 832,500 ج
- القسط الشهري: 138,750 ج على 14 شهر

### المحلات التجارية (الأرضي):
- سعر المتر التجاري: 35,000 ج
- مقدم تجاري يبدأ من 10% فقط
- رسوم خدمات تجاري: 100,000 ج

| رقم المحل | المساحة | الإجمالي | مقدم 10% | الحالة |
|-----------|---------|----------|----------|--------|
| محل 1 | 121 م² | 4,235,000 ج | 423,500 ج | متاح |
| محل 2 | 114 م² | - | - | مباع ❌ |
| محل 3 | 74 م² | 2,590,000 ج | 259,000 ج | متاح |
| محل 4 | 78 م² | 2,730,000 ج | 273,000 ج | متاح |
| محل 5 | 112 م² | 3,920,000 ج | 392,000 ج | متاح |
| محل 6 | 121 م² | 4,235,000 ج | 423,500 ج | متاح |

### الوحدات الإدارية (الأول):
- 5 وحدات قابلة للتقسيم
- سعر المتر: 15,000 ج
- مناسبة للعيادات والمكاتب

### نظام السداد:
- السكني: مقدم 30% + باقي على أقساط شهرية حتى 1 يوليو 2027
- التجاري: مقدم يبدأ من 10% (الأفضل 30%)
- خيارات التقسيط: شهري / 45 يوم / 60 يوم

### نقاط القوة:
- مقدم تجاري يبدأ من 10% فقط
- استلام خلال 14-16 شهر تقريباً
- تنوع بين تجاري وإداري وسكني
- ترخيص تحت قانون الاستثمار المصري
- تصميم كلاسيكي أوروبي فاخر
"""


# ==============================================
# PROJECT 2: ABRAJ AL-RAMAD (Hardcoded fallback)
# ==============================================
ABRAJ_ALRAMAD = """
## مشروع أبراج مصطفى الغمراوي – الرمد، غرب النيل، بني سويف

نوع المشروع: سكني بنظام الأسهم واتحاد الملاك
الموقع: منطقة الرمد – بني سويف – غرب النيل
مساحة المشروع: 20,300 م²

### نظام الأسهم:
- سعر السهم: 250,000 ج كاش
- كل سهم = 5 م² ملكية أرض + 45-50 م² مساحة سكنية تقريبي
- التخصيص بالقرعة بعد انتهاء البناء

### السداد:
1. دفعات الأرض: كاش عند الدخول
2. دفعات المباني: تبدأ لاحقاً ≈ 200,000 ج/سهم (تقديرة)
"""


# ==============================================
# COMPLETE SYSTEM PROMPT FUNCTION
# ==============================================
def get_system_prompt():
    prompt = SYSTEM_PROMPT + "\n\n" + SKY_VILLAS_M7 + "\n\n" + ABRAJ_ALRAMAD

    # Try to get live data from Google Sheets
    try:
        sheet_data = format_sheet_data_for_prompt()
        if sheet_data:
            prompt += "\n\n# ⚠️ البيانات التالية من Google Sheet (محدثة ومُقدَّمة على البيانات الثابتة أعلاه)\n"
            prompt += sheet_data
            prompt += "\n\n⚠️ لو فيه تعارض بين بيانات الشيت والبيانات الثابتة، استخدمي بيانات الشيت لأنها أحدث."
    except Exception as e:
        logger.error(f"Failed to load sheet data: {e}")

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

EMOJI_POSITIVE = ["❤", "👍", "🔥", "😍", "💪", "👏", "💯", "🙏", "😊", "❥", "💕", "💖", "⭐", "🌟", "✨"]
EMOJI_RESPONSES = ["🙏❤️", "❤️🙏", "💪🔥", "😊❤️", "🙏✨", "❤️✨"]
THANK_WORDS = ["شكراً", "شكرا", "شكر", "ممتاز", "جميل", "حلو", "رائع", "تسلم", "الله ينور", "برافو", "ماشاء الله", "احسنت"]


# ==============================================
# HELPER FUNCTIONS
# ==============================================
def format_projects_for_search():
    return {
        "company": COMPANY_INFO,
        "main_project": "Sky Villas M7",
        "other_projects": ["أبراج مصطفى الغمراوي – الرمد"],
    }
