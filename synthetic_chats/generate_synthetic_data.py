"""
Generates synthetic WhatsApp export data for OWI testing and demonstration.
Includes 100+ realistic messages in Arabic, English, and Franco-Arab,
along with sample attachments (audio, images, PDF) packaged into a valid WhatsApp ZIP export.
"""

import os
import zipfile
from pathlib import Path
from datetime import datetime, timedelta
from PIL import Image, ImageDraw
from pypdf import PdfWriter

DATA_DIR = Path(__file__).resolve().parent
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Generate 110 realistic messages spanning multiple days
MESSAGES_TEMPLATES = [
    # Day 1: Kickoff & Property requirements
    ("14/09/2026, 09:15 - Omar: صباح الخير يا شباب، محتاجين نبدأ ندور على مقر جديد للشركة في التجمع الخامس."),
    ("14/09/2026, 09:16 - Ahmed El-Sayed: صباح النور يا عمر. إيه المواصفات المطلوبة للمقر الجديد؟"),
    ("14/09/2026, 09:18 - Omar: محتاجين مساحة حوالي 450 إلى 500 متر مربع، ويكون تشطيب الترا سوبر لوكس."),
    ("14/09/2026, 09:20 - Tarek Mansour: هل ضروري يكون فيه رخصة إداري رسمي ولا تجاري ينفع؟"),
    ("14/09/2026, 09:21 - Omar: لازم رخصة إداري معتمدة عشان التراخيص والتسجيل الضريبي."),
    ("14/09/2026, 09:23 - Sarah Hassan: What is our target budget for monthly rent or total purchase?"),
    ("14/09/2026, 09:25 - Omar: الحد الأقصى للإيجار 300,000 جنيه شهرياً، أو شراء في حدود 18 إلى 20 مليون جنيه."),
    ("14/09/2026, 09:28 - Karim Fayed: عندي مكتب ممتاز 500 متر في التسعين الشمالي، دور ثالث."),
    ("14/09/2026, 09:30 - Ahmed El-Sayed: هبعتلك تفاصيل المقر ده بكرة الصبح يا عمر."),
    ("14/09/2026, 09:35 - Omar: ممتاز يا أحمد. مستني أحمد يبعت تفاصيل المقر ورخصة الإداري."),
    ("14/09/2026, 09:40 - Tarek Mansour: Voice note omitted"),
    ("14/09/2026, 09:41 - Tarek Mansour: AUD-20260914-WA0001.opus (file attached)"),
    ("14/09/2026, 09:45 - Sarah Hassan: I will prepare the financial comparison sheet by Thursday."),
    ("14/09/2026, 09:50 - Omar: Please send the legal requirements to Tarek."),
    ("14/09/2026, 10:00 - Tarek Mansour: كلمت المالك، وموافق على 280,000 جنيه شهرياً."),
    ("14/09/2026, 10:05 - Omar: اتفقنا على تقديم عرض مبدئي بـ 280,000 جنيه."),
    ("14/09/2026, 10:10 - Ahmed El-Sayed: IMG-20260914-WA0002.jpg (file attached)"),
    ("14/09/2026, 10:11 - Ahmed El-Sayed: دي صورة الواجهة وموقف السيارات تحت الأرض."),
    ("14/09/2026, 10:15 - Karim Fayed: فكرة: إيه رأيكم لو نعمل مساحة خضراء في الروف للموظفين؟"),
    ("14/09/2026, 10:20 - Omar: فكرة ممتازة يا كريم، خلينا ندرس التكلفة."),

    # Day 2: Quotations & Documents
    ("15/09/2026, 11:00 - Sarah Hassan: DOC-20260915-WA0003.pdf (file attached)"),
    ("15/09/2026, 11:02 - Sarah Hassan: Here is the official quotation and pricing breakdown from the developer."),
    ("15/09/2026, 11:05 - Omar: راجعوا ملف الأسعار وأكدوا لي الملاحظات خلال يومين."),
    ("15/09/2026, 11:10 - Tarek Mansour: مستني المالك يبعت صورة السجل التجاري والتوكيل الرسمي."),
    ("15/09/2026, 11:15 - Ahmed El-Sayed: كلمت شركة التشطيبات وطلبوا معاينة يوم الأربعاء."),
    ("15/09/2026, 11:20 - Omar: قررنا نعتمد شركة الأهرام للديكور والأعمال الهندسية."),
    ("15/09/2026, 11:25 - Karim Fayed: سأقوم بإرسال المواصفات الفنية للشبكات والإنترنت بكرة."),
    ("15/09/2026, 11:30 - Sarah Hassan: Need to verify fiber optic availability in the building."),
    ("15/09/2026, 11:35 - Omar: برجاء تجهيز الدفعة المقدمة 10% قبل نهاية الأسبوع."),
    ("15/09/2026, 11:40 - Tarek Mansour: تمام، هخلص إجراءات البنك والشيكات المصرفية."),

    # Day 3: Technical details & follow-ups
    ("16/09/2026, 13:00 - Omar: إيه الأخبار يا شباب في موضوع فايبر الإنترنت؟"),
    ("16/09/2026, 13:05 - Karim Fayed: أكدت مع شركة المصرية للاتصالات، الفايبر متوفر بسرعة 200 ميجا."),
    ("16/09/2026, 13:10 - Ahmed El-Sayed: المبنى مجهز بمولد ديزل للطوارئ ومصعدين حمولة 8 أفراد."),
    ("16/09/2026, 13:15 - Sarah Hassan: That is crucial for our server rooms uptime."),
    ("16/09/2026, 13:20 - Omar: ممتاز. لازم نحجز 4 أماكن في الجراج للسيارات."),
    ("16/09/2026, 13:25 - Tarek Mansour: المالك خصص 5 أماكن باركينج مش 4 كمان."),
    ("16/09/2026, 13:30 - Omar: تمام جداً. قررنا توقيع العقد النهائي يوم الخميس القادم."),
    ("16/09/2026, 13:35 - Sarah Hassan: I will bring the contract stamps and company seal."),
    ("16/09/2026, 13:40 - Ahmed El-Sayed: هكون متواجد مع المحامي لمراجعة البنود القانونية."),
    ("16/09/2026, 13:45 - Karim Fayed: مستني استلام المفاتيح لبدء تمديد كابلات الشبكة."),
]

# Expand to reach 105 messages with realistic operational dialogue
for i in range(1, 66):
    day = 16 + (i // 15)
    hour = 9 + (i % 8)
    minute = 10 + (i % 45)
    speaker = ["Omar", "Ahmed El-Sayed", "Tarek Mansour", "Sarah Hassan", "Karim Fayed"][i % 5]
    
    if i % 8 == 0:
        content = f"متابعة بخصوص بند رقم {i} من التجهيزات الفنية."
    elif i % 7 == 0:
        content = f"Please check the update on item {i} regarding office partitioning."
    elif i % 6 == 0:
        content = f"اتفقنا على خطة العمل للأسبوع القادم للبند {i}."
    elif i % 5 == 0:
        content = f"هبعتلك التقرير المالي المحدث بكرة يا عمر بخصوص الدفعة {i}."
    elif i % 4 == 0:
        content = f"مستني موافقة الإدارة على اعتماد الميزانية الإضافية {i * 1000} جنيه."
    elif i % 3 == 0:
        content = f"برجاء مراجعة العقد والملحقات الفنية رقم {i}."
    else:
        content = f"تم تأكيد استلام الدفعة والجدول الزمني متوافق مع المخطط لليوم {day}."
        
    MESSAGES_TEMPLATES.append(f"{day:02d}/09/2026, {hour:02d}:{minute:02d} - {speaker}: {content}")

def create_sample_media(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    
    # 1. Create dummy opus/audio file
    audio_file = folder / "AUD-20260914-WA0001.opus"
    with open(audio_file, "wb") as f:
        # Simple valid header or binary filler
        f.write(b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" + b"\x00" * 2048)

    # 2. Create sample JPEG image
    img_file = folder / "IMG-20260914-WA0002.jpg"
    im = Image.new("RGB", (600, 400), color=(41, 128, 185))
    draw = ImageDraw.Draw(im)
    draw.text((50, 180), "Office Building - New Cairo", fill=(255, 255, 255))
    im.save(img_file, "JPEG")

    # 3. Create sample PDF document
    pdf_file = folder / "DOC-20260915-WA0003.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    with open(pdf_file, "wb") as f:
        writer.write(f)

def generate_dataset():
    chat_file = DATA_DIR / "omar_team_chat.txt"
    with open(chat_file, "w", encoding="utf-8") as f:
        f.write("\n".join(MESSAGES_TEMPLATES))
    
    print(f"Generated {len(MESSAGES_TEMPLATES)} messages in {chat_file}")

    # Build ZIP archive with chat and media
    zip_path = DATA_DIR / "WhatsApp Chat - Omar Team Office.zip"
    create_sample_media(DATA_DIR)
    
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(chat_file, arcname="_chat.txt")
        z.write(DATA_DIR / "AUD-20260914-WA0001.opus", arcname="AUD-20260914-WA0001.opus")
        z.write(DATA_DIR / "IMG-20260914-WA0002.jpg", arcname="IMG-20260914-WA0002.jpg")
        z.write(DATA_DIR / "DOC-20260915-WA0003.pdf", arcname="DOC-20260915-WA0003.pdf")

    print(f"Created ZIP archive: {zip_path} with chat text and 3 attachments.")

if __name__ == "__main__":
    generate_dataset()
