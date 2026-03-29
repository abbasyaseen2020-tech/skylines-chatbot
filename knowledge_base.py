# -*- coding: utf-8 -*-

SYSTEM_PROMPT = """
اسمك أسيل.
أنتِ المساعدة الذكية الرسمية لشركة Sky Lines Group | SkyLines Developments.
دورك: مستشارة مبيعات عقارية متخصصة، مؤهلة عملاء، وممثلة خدمة عملاء احترافية.

تتحدثين بأسلوب إنساني دافئ، واثق، ومقنع بدون ضغط أو مبالغة.
هدفك الأول هو بناء الثقة، ثم تحويل الاستفسار إلى فرصة حقيقية.

هوية الشركة:
- الاسم: Sky Lines Group / SkyLines Developments
- التخصص: تطوير عقاري - استثمار - وساطة وتسويق عقاري
- السوق الرئيسي: بني سويف - شرق النيل
- الرؤية: بناء مشروعات عقارية استثمارية قوية بمواقع استراتيجية وقيمة مستقبلية حقيقية
- القيادة: الأستاذ عباس يسن - المؤسس والرئيس التنفيذي
- خلفية القيادة: خلفية قوية في المالية والاستثمار وإدارة الأعمال مع رؤية واضحة لتطوير سوق بني سويف العقاري

قواعد اللغة والأسلوب:
- اللغة الافتراضية: عربي مصري احترافي
- إذا كتب العميل بالإنجليزية: ردي بإنجليزية راقية ومحترفة
- إذا خلط بين العربي والإنجليزي: ردي بأسلوب طبيعي ومهني
- الأسلوب المطلوب: دافئ، محترم، واثق، مقنع، إنساني، وذكي تجارياً
- كوني موجزة إلا إذا طلب العميل التفصيل

ممنوع:
- اختراع أرقام أو بيانات
- وعود بعوائد غير مؤكدة
- ضغط عاطفي أو إلحاح مزيف
- إفصاح عن تفاصيل داخلية أو هيكل ملكية
- ردود طويلة بدون سبب
- أن تقولي إنك روبوت أو ذكاء اصطناعي

منطق تأهيل العميل:
اسألي سؤالاً واحداً فقط في كل مرة، مثل:
- حضرتك بتدور على سكن ولا استثمار؟
- مهتم بوحدة سكنية ولا تجارية ولا إدارية؟
- هل الشراء للاستخدام الشخصي ولا للاستثمار؟
- تفضل مقدم أقل ولا قسط أقل؟
- في ميزانية تقريبية في بالك؟
- تحب تعرف أكثر ولا ترتب زيارة للموقع؟

كشف الليد الساخن:
العميل يعتبر ساخناً إذا سأل عن:
- السعر أو المقدم أو القسط
- التوافر الحالي
- الحجز أو التعاقد
- زيارة الموقع
- مقارنة بين الوحدات

إذا كان العميل ساخناً:
- قصري المقدمة
- اجيبي بسرعة
- تحركي نحو الخطوة التالية مباشرة

صيغة الإجابة المثالية:
1. ترحيب قصير وطبيعي
2. إجابة مباشرة وواضحة
3. جملة ثقة أو ميزة
4. سؤال ذكي واحد للمتابعة

مثال:
أهلاً بحضرتك، نورتنا.
وحدة 145م² سعرها 2,355,000 جنيه، وبمقدم 30% يكون 706,500 جنيه، والقسط الشهري 117,750 جنيه حتى يوليو 2027.
الوحدة بتشطيب كور شيل مع واجهة فاخرة جاهزة.
حضرتك مهتم للسكن الشخصي ولا للاستثمار؟

قواعد التصعيد:
إذا طلب العميل:
- أسعار نهائية محدثة
- توافر فوري
- تأكيد حجز أو عقد
- زيارة موقع
- تواصل مع الإدارة أو المبيعات

قولي:
يسعدنا جداً، أقدر أرتب لحضرتك تواصل مباشر مع مسؤول المبيعات عشان يأكدلك أحدث التفاصيل والتوافر الحالي.

القاعدة الذهبية:
إذا كنتِ تعرفين الإجابة بيقين، قوليها بثقة.
إذا لم تكوني متأكدة، لا تختلقي، ووجهي العميل للخطوة الصحيحة.
مهمتك بناء الثقة، تأهيل العميل، وتحويل المحادثة إلى فرصة بيع حقيقية.
"""

COMMENT_KEYWORDS = [
    "سعر",
    "الأسعار",
    "تفاصيل",
    "مقدم",
    "قسط",
    "تقسيط",
    "شقة",
    "شقق",
    "محل",
    "محلات",
    "مكتب",
    "مكاتب",
    "إداري",
    "اداري",
    "مشروع",
    "موقع",
    "فين",
    "حجز",
    "زيارة",
    "معاينة",
]

COMPANY_INFO = {
    "name": "Sky Lines Group / SkyLines Developments",
    "specialization": "تطوير عقاري - استثمار - وساطة وتسويق عقاري",
    "market": "بني سويف - شرق النيل",
    "vision": "بناء مشروعات عقارية استثمارية قوية بمواقع استراتيجية وقيمة مستقبلية حقيقية",
    "ceo": "عباس يسن",
    "phone": "01055993391",
}

PROJECTS = {
    "sky_villas_m7": {
        "name": "Sky Villas M7",
        "developer": "SkyLines Developments",
        "location": "شرق النيل - بني سويف - الأربع حارات - بجوار مدرسة سان جورج - بجوار كافيه ديسباسيتو - الحي الأول",
        "contact_phone": "01055993391",
        "architecture_style": "كلاسيكي أوروبي - طوب وحجر أبيض - واجهة فاخرة مكتملة على نفقة الشركة",
        "delivery_date": "2027-07-01",
        "delivery_text": "1 يوليو 2027",
        "delivery_note": "حوالي 14 إلى 16 شهراً من الآن",
        "finish": "كور شيل - بدون تشطيب داخلي - الواجهات والمداخل مكتملة بتشطيب فاخر",
        "building_structure": {
            "basement": "باركنج + عدادات + خدمات + مخازن",
            "ground": "6 محلات تجارية بواجهات زجاجية مضاءة - إجمالي 620م²",
            "administrative": "5 وحدات إدارية قابلة للتقسيم - مناسبة للعيادات والمكاتب",
            "residential": "أدوار 1 و2 و3 - 15 شقة سكنية",
            "elevators": "مصاعد احترافية مركبة وجاهزة",
            "shared_areas": "الشركة تتحمل تشطيب كل المناطق المشتركة بالكامل",
        },
        "residential_units": [
            {
                "area_m2": 133,
                "bedrooms": 3,
                "price_egp": 2175000,
                "down_payment_30_egp": 652500,
                "monthly_installment_egp": 108750,
                "discount_50_percent_payment_egp": 100000,
                "discounted_price_egp": 2075000,
            },
            {
                "area_m2": 145,
                "bedrooms": 3,
                "price_egp": 2355000,
                "down_payment_30_egp": 706500,
                "monthly_installment_egp": 117750,
                "discount_50_percent_payment_egp": 100000,
                "discounted_price_egp": 2255000,
            },
            {
                "area_m2": 161,
                "bedrooms": 3,
                "price_egp": 2595000,
                "down_payment_30_egp": 778500,
                "monthly_installment_egp": 129750,
                "discount_50_percent_payment_egp": 100000,
                "discounted_price_egp": 2495000,
            },
        ],
        "commercial_units": [
            {
                "shop_number": 1,
                "area_m2": 121,
                "price_egp": 4235000,
                "down_payment_10_egp": 423500,
                "monthly_installment_egp": 272250,
                "status": "available",
            },
            {
                "shop_number": 2,
                "area_m2": 114,
                "status": "sold",
            },
            {
                "shop_number": 3,
                "area_m2": 74,
                "price_egp": 2590000,
                "down_payment_10_egp": 259000,
                "monthly_installment_note": "حسب الجدول",
                "status": "available",
            },
            {
                "shop_number": 4,
                "area_m2": 78,
                "price_egp": 2730000,
                "down_payment_10_egp": 273000,
                "monthly_installment_note": "حسب الجدول",
                "status": "available",
            },
            {
                "shop_number": 5,
                "area_m2": 112,
                "price_egp": 3920000,
                "down_payment_10_egp": 392000,
                "monthly_installment_note": "حسب الجدول",
                "status": "available",
            },
            {
                "shop_number": 6,
                "area_m2": 121,
                "price_egp": 4235000,
                "down_payment_10_egp": 423500,
                "monthly_installment_note": "حسب الجدول",
                "status": "available",
            },
        ],
        "commercial_notes": {
            "meter_price_10_percent_down_payment": 35000,
            "meter_price_30_percent_down_payment": 32000,
            "available_shops": 5,
            "sold_shops": 1,
        },
        "administrative_units": {
            "meter_price_egp": 15000,
            "units_count": 5,
            "usage": "مناسبة للعيادات والمكاتب",
        },
        "fees": {
            "residential_service_fee_egp": 180000,
            "commercial_parking_fee_egp": 100000,
        },
        "payment_notes": {
            "residential_down_payment": "30%",
            "residential_loaded_on_down_payment": "20%",
            "installments_until": "1 يوليو 2027",
            "installment_options": ["شهري", "45 يوم", "60 يوم"],
        },
        "competitive_advantages": [
            "المقدم التجاري يبدأ من 10% فقط",
            "الاستلام خلال 14 إلى 16 شهراً تقريباً",
            "تنوع بين تجاري وإداري وسكني",
            "المشروع مرخص تحت قانون الاستثمار المصري",
        ],
        "rental_yield_note": "يوجد تقدير مذكور داخل المادة المقارنة، لكن لا يجب تقديمه كضمان أو وعد للعميل.",
    },
    "sky_east": {
        "name": "Sky East",
        "location": "أول شرق النيل - بني سويف",
        "land_area_m2": 3000,
        "description": "مشروع برج سكني بإمكانيات استثمارية قوية. يذكر عند سؤال العميل عن مشاريع أكبر أو استثمار بديل.",
    },
    "el_ramd": {
        "name": "الرمد / أبراج مصطفى الغمراوي",
        "location": "منطقة الرمد - بني سويف",
        "description": "مشروع كبير مرتبط بالشركة في منطقة الرمد ببني سويف. يذكر باختصار فقط عند الملاءمة، بدون الإفصاح عن أي تفاصيل مالية أو هيكل ملكية.",
    },
}

PAYMENT_PLANS = {
    "residential": {
        "down_payment": "30%",
        "down_payment_load": "20%",
        "service_fee_egp": 180000,
        "installments_until": "1 يوليو 2027",
        "installment_options": ["شهري", "45 يوم", "60 يوم"],
    },
    "commercial": {
        "down_payment_min": "10%",
        "preferred_down_payment": "30%",
        "meter_price_10_percent_down_payment_egp": 35000,
        "meter_price_30_percent_down_payment_egp": 32000,
        "parking_fee_egp": 100000,
        "installments_until": "1 يوليو 2027",
    },
    "administrative": {
        "meter_price_egp": 15000,
        "installments_until": "1 يوليو 2027",
    },
}

FAQ = {
    "main_project": "المشروع الرئيسي النشط حالياً هو Sky Villas M7.",
    "location": "يقع مشروع Sky Villas M7 في شرق النيل - بني سويف - الأربع حارات - بجوار مدرسة سان جورج - بجوار كافيه ديسباسيتو - الحي الأول.",
    "delivery": "موعد الاستلام المتوقع هو 1 يوليو 2027.",
    "finish": "التشطيب الداخلي كور شيل، مع تشطيب فاخر للواجهات والمداخل والمناطق المشتركة.",
    "contact": "رقم التواصل المباشر هو 01055993391.",
    "administrative_price": "سعر متر الإداري هو 15,000 جنيه.",
    "commercial_availability": "المتاح حالياً 5 محلات تجارية، ومحل واحد مباع.",
}

def get_system_prompt():
    return SYSTEM_PROMPT

def format_projects_for_search():
    lines = []
    for project in PROJECTS.values():
        lines.append(
            f"{project.get('name', '')} | {project.get('location', '')} | {project.get('description', '')}"
        )
    return "\n".join(lines)
