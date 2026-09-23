"""
Tests for WhatsApp chat parser across formats, locales, and attachment types.
"""

from datetime import datetime
from owi.ingest.whatsapp_parser import WhatsAppParser, parse_date_time

def test_android_24h_format():
    sample = "14/09/2026, 14:32 - Omar: مرحباً بك في المقر الجديد."
    parsed = WhatsAppParser.parse_chat_text(sample)
    assert len(parsed) == 1
    assert parsed[0].sender_name == "Omar"
    assert parsed[0].content == "مرحباً بك في المقر الجديد."
    assert parsed[0].timestamp == datetime(2026, 9, 14, 14, 32)
    assert parsed[0].message_type == "text"

def test_ios_12h_format():
    sample = "[14/09/2026, 2:32:15 PM] Ahmed: We will meet tomorrow."
    parsed = WhatsAppParser.parse_chat_text(sample)
    assert len(parsed) == 1
    assert parsed[0].sender_name == "Ahmed"
    assert parsed[0].content == "We will meet tomorrow."
    assert parsed[0].timestamp == datetime(2026, 9, 14, 14, 32, 15)

def test_arabic_locale_with_unicode_bidi():
    # Includes \u200e (LTR mark) and Arabic ص (AM)
    sample = "\u200e14/09/2026, 9:15 \u0635 - Omar: صباح الخير"
    parsed = WhatsAppParser.parse_chat_text(sample)
    assert len(parsed) == 1
    assert parsed[0].sender_name == "Omar"
    assert parsed[0].content == "صباح الخير"
    assert parsed[0].timestamp == datetime(2026, 9, 14, 9, 15)

def test_multiline_continuation():
    sample = """14/09/2026, 10:00 - Omar: السطر الأول من الرسالة.
السطر الثاني من نفس الرسالة.
السطر الثالث مع أرقام 12345.
14/09/2026, 10:05 - Ahmed: رسالة جديدة منفصلة."""
    parsed = WhatsAppParser.parse_chat_text(sample)
    assert len(parsed) == 2
    assert "السطر الثاني" in parsed[0].content
    assert "السطر الثالث" in parsed[0].content
    assert parsed[1].sender_name == "Ahmed"

def test_attachment_detection():
    sample = """14/09/2026, 11:00 - Sarah: contract_draft.pdf (file attached)
14/09/2026, 11:05 - Tarek: AUD-20260914-WA0001.opus (file attached)
14/09/2026, 11:10 - Ahmed: IMG-20260914-WA0002.jpg (file attached)
14/09/2026, 11:15 - Karim: video_site_tour.mp4 (file attached)
14/09/2026, 11:20 - Omar: <Media omitted>"""
    parsed = WhatsAppParser.parse_chat_text(sample)
    assert len(parsed) == 5
    assert parsed[0].has_attachment is True
    assert parsed[0].attachment_name == "contract_draft.pdf"
    assert parsed[0].message_type == "document"
    assert parsed[1].message_type == "voice"
    assert parsed[2].message_type == "image"
    assert parsed[3].message_type == "video"
    assert parsed[4].has_attachment is True

def test_system_message_detection():
    sample = "14/09/2026, 09:00 - Messages and calls are end-to-end encrypted. No one outside of this chat can read them."
    parsed = WhatsAppParser.parse_chat_text(sample)
    assert len(parsed) == 1
    assert parsed[0].message_type == "system"
