"""
Multi-format WhatsApp exported text parser.
Handles Android, iOS, Windows formats, 12h/24h timestamps, Arabic locales,
multiline messages, system messages, and media attachment references.
"""

import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict

# Invisible and directional Unicode markers to strip
BIDI_CHARS = re.compile(r'[\u200e\u200f\u202a-\u202e\u202f\u00a0\ufeff\u061c]')

# WhatsApp timestamp regexes
# 1. iOS style: [14/09/2026, 14:32:10] or [14/9/26, 2:32:10 PM]
IOS_PATTERN = re.compile(
    r"^\[(?P<date>\d{1,4}[/\-\.]\d{1,2}[/\-\.]\d{1,4}),?\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:[APap][Mm]|[\u0635\u0645]))?)\]\s+(?P<rest>.*)$"
)

# 2. Android / Web style: 14/09/2026, 14:32 - Sender: or 14/9/26, 2:32 PM - Sender:
ANDROID_PATTERN = re.compile(
    r"^(?P<date>\d{1,4}[/\-\.]\d{1,2}[/\-\.]\d{1,4}),?\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:[APap][Mm]|[\u0635\u0645]))?)\s+-\s+(?P<rest>.*)$"
)

# System message indicator keywords
SYSTEM_INDICATORS = [
    "end-to-end encrypted", "مشفرة تماماً",
    "created group", "أنشأ المجموعة",
    "added", "أضاف",
    "left", "غادر",
    "removed", "أزال",
    "security code changed", "تغير رمز الأمان",
    "changed the subject", "غير موضوع المجموعة",
    "changed this group's icon", "غير أيقونة المجموعة",
    "you were added", "تمت إضافتك",
    "joined using this group's invite link", "انضم باستخدام رابط الدعوة",
    "disappearing messages", "الرسائل ذاتية الاختفاء"
]

# Attachment regexes
ATTACHMENT_PATTERNS = [
    re.compile(r"^(?P<file>[^\n]+?)\s+\((?:file attached|ملف مرفق)\)", re.IGNORECASE),
    re.compile(r"^<attached:\s*(?P<file>[^\n>]+)>", re.IGNORECASE),
    re.compile(r"^<?(?:image|audio|video|document|voice note|sticker|GIF|media) omitted>?", re.IGNORECASE),
    re.compile(r"^<.*(?:مستبعد|مفقود).*>", re.IGNORECASE),
]

AUDIO_EXTENSIONS = {".opus", ".ogg", ".mp3", ".m4a", ".aac", ".wav"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".3gp"}
DOC_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".csv", ".zip"}

@dataclass
class ParsedMessage:
    source_index: int
    timestamp: datetime
    sender_name: str
    content: str
    message_type: str  # text, voice, image, video, document, system
    raw_text: str
    has_attachment: bool = False
    attachment_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d

def clean_bidi(text: str) -> str:
    """Strip Unicode bidirectional markers and replace narrow spaces."""
    return BIDI_CHARS.sub(" ", text).strip()

def parse_date_time(date_str: str, time_str: str) -> datetime:
    """
    Intelligently parse date and time strings across international formats.
    Handles DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD, 12h and 24h with AM/PM (or Arabic ص/م).
    """
    date_str = clean_bidi(date_str).replace(".", "/").replace("-", "/")
    time_str = clean_bidi(time_str).replace("  ", " ")
    
    # Normalize Arabic AM/PM (ص = AM, م = PM)
    time_str = re.sub(r'[\u0635]\.?$', 'AM', time_str)
    time_str = re.sub(r'[\u0645]\.?$', 'PM', time_str)

    # Date parts
    parts = [int(p) for p in date_str.split("/") if p.isdigit()]
    if len(parts) != 3:
        raise ValueError(f"Invalid date string: {date_str}")
        
    p1, p2, p3 = parts
    
    # Determine year, month, day
    if p1 > 1000:
        # YYYY/MM/DD
        year, month, day = p1, p2, p3
    else:
        # p3 is year
        year = p3 if p3 > 100 else (2000 + p3 if p3 < 70 else 1900 + p3)
        # If p1 > 12, it must be DD/MM/YYYY
        if p1 > 12:
            day, month = p1, p2
        elif p2 > 12:
            month, day = p1, p2
        else:
            # Default to DD/MM/YYYY for international WhatsApp standard
            day, month = p1, p2

    # Clean time string and parse
    time_str = time_str.strip()
    is_pm = "PM" in time_str.upper()
    is_am = "AM" in time_str.upper()
    time_clean = re.sub(r'(?i)\s*(AM|PM)', '', time_str).strip()
    
    t_parts = [int(p) for p in time_clean.split(":") if p.isdigit()]
    hour = t_parts[0]
    minute = t_parts[1] if len(t_parts) > 1 else 0
    second = t_parts[2] if len(t_parts) > 2 else 0

    if is_pm and hour < 12:
        hour += 12
    elif is_am and hour == 12:
        hour = 0

    return datetime(year, month, day, hour, minute, second)

def detect_attachment_type(filename: str) -> str:
    """Classify media attachment based on filename extension."""
    lower = filename.lower()
    for ext in AUDIO_EXTENSIONS:
        if lower.endswith(ext):
            return "voice"
    for ext in IMAGE_EXTENSIONS:
        if lower.endswith(ext):
            return "image"
    for ext in VIDEO_EXTENSIONS:
        if lower.endswith(ext):
            return "video"
    for ext in DOC_EXTENSIONS:
        if lower.endswith(ext):
            return "document"
    return "document"

class WhatsAppParser:
    """Parser for raw WhatsApp text conversation exports."""

    @classmethod
    def parse_chat_text(cls, chat_text: str) -> List[ParsedMessage]:
        lines = chat_text.splitlines()
        parsed_messages: List[ParsedMessage] = []
        current_msg: Optional[ParsedMessage] = None
        source_idx = 0

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue

            cleaned_line = clean_bidi(line)
            
            # Check for timestamp line match
            match = IOS_PATTERN.match(cleaned_line) or ANDROID_PATTERN.match(cleaned_line)
            
            if match:
                # Save previous message
                if current_msg:
                    parsed_messages.append(current_msg)
                    current_msg = None

                date_part = match.group("date")
                time_part = match.group("time")
                rest_part = match.group("rest").strip()

                try:
                    dt = parse_date_time(date_part, time_part)
                except Exception:
                    # If date parsing fails, treat as multiline continuation
                    if current_msg:
                        current_msg.content += "\n" + line_stripped
                        current_msg.raw_text += "\n" + line
                    continue

                source_idx += 1

                # Check if it's a user message or system message
                # User messages have "Sender: Message"
                sender = "System"
                content = rest_part
                msg_type = "text"
                has_attachment = False
                attachment_name = None

                if ": " in rest_part:
                    sender_candidate, msg_candidate = rest_part.split(": ", 1)
                    # Check if sender_candidate is not actually a system message
                    if not any(kw.lower() in sender_candidate.lower() for kw in SYSTEM_INDICATORS):
                        sender = sender_candidate.strip()
                        content = msg_candidate.strip()
                else:
                    # Check if it's a known system message
                    msg_type = "system"

                # Check for attachments
                for pat in ATTACHMENT_PATTERNS:
                    att_match = pat.search(content)
                    if att_match:
                        has_attachment = True
                        if "file" in att_match.groupdict():
                            attachment_name = att_match.group("file").strip()
                            msg_type = detect_attachment_type(attachment_name)
                        else:
                            # Generic omitted attachment
                            lower_c = content.lower()
                            if "audio" in lower_c or "voice" in lower_c:
                                msg_type = "voice"
                            elif "image" in lower_c:
                                msg_type = "image"
                            elif "video" in lower_c:
                                msg_type = "video"
                            elif "document" in lower_c:
                                msg_type = "document"
                            else:
                                msg_type = "document"
                        break

                current_msg = ParsedMessage(
                    source_index=source_idx,
                    timestamp=dt,
                    sender_name=sender,
                    content=content,
                    message_type=msg_type,
                    raw_text=line,
                    has_attachment=has_attachment,
                    attachment_name=attachment_name
                )
            else:
                # Multiline continuation of current message
                if current_msg:
                    current_msg.content += "\n" + line_stripped
                    current_msg.raw_text += "\n" + line

        if current_msg:
            parsed_messages.append(current_msg)

        return parsed_messages
