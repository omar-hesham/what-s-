"""
Relative date resolver anchored strictly to the message timestamp.
Calculates due dates and commitments without mistakenly using the computer's current date.
Supports Arabic (Egyptian, Gulf, MSA) and English expressions.
"""

import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

WEEKDAY_MAP_AR = {
    "الاثنين": 0, "الإثنين": 0,
    "الثلاثاء": 1,
    "الأربعاء": 2, "الاربعاء": 2,
    "الخميس": 3,
    "الجمعة": 4,
    "السبت": 5,
    "الأحد": 6, "الاحد": 6
}

WEEKDAY_MAP_EN = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6
}

def resolve_relative_date(text: str, anchor_date: datetime) -> Optional[datetime]:
    """
    Parse relative date mentions from text anchored to `anchor_date`.
    Returns calculated datetime, or None if no relative date is detected.
    """
    if not text or not anchor_date:
        return None

    clean_text = text.lower().strip()

    # 1. Day after tomorrow (بعد بكرة / بعد غد)
    if any(k in clean_text for k in ["بعد بكرة", "بعد غد", "بعد غدا", "day after tomorrow"]):
        return anchor_date + timedelta(days=2)

    # 2. Tomorrow (بكرة / غدا / غداً)
    if any(k in clean_text for k in ["بكرة", "غدا", "غداً", "غداُ", "tomorrow"]):
        return anchor_date + timedelta(days=1)

    # 3. Next week (الأسبوع الجاي / الأسبوع القادم)
    if any(k in clean_text for k in ["الأسبوع الجاي", "الاسبوع الجاي", "الأسبوع القادم", "الاسبوع القادم", "next week"]):
        return anchor_date + timedelta(days=7)

    # 4. In N days / خلال N أيام
    in_days_ar = re.search(r'(?:خلال|في خلال|بعد)\s+(\d+)\s*(?:أيام|ايام|يوم)', clean_text)
    if in_days_ar:
        days = int(in_days_ar.group(1))
        return anchor_date + timedelta(days=days)

    in_days_en = re.search(r'in\s+(\d+)\s*(?:days|day)', clean_text)
    if in_days_en:
        days = int(in_days_en.group(1))
        return anchor_date + timedelta(days=days)

    # In two days (يومين / خلال يومين)
    if any(k in clean_text for k in ["خلال يومين", "في يومين", "بعد يومين", "in 2 days"]):
        return anchor_date + timedelta(days=2)

    # 5. Arabic Days of week: e.g. "يوم الخميس", "الخميس الجاي"
    for day_name, target_weekday in WEEKDAY_MAP_AR.items():
        if f"يوم {day_name}" in clean_text or f"{day_name} الجاي" in clean_text or f"{day_name} القادم" in clean_text or clean_text == day_name:
            current_weekday = anchor_date.weekday()
            days_ahead = target_weekday - current_weekday
            if days_ahead <= 0:  # Target day already happened this week, move to next week
                days_ahead += 7
            return anchor_date + timedelta(days=days_ahead)

    # 6. English Days of week: e.g. "by Thursday", "next Friday"
    for day_name, target_weekday in WEEKDAY_MAP_EN.items():
        pattern = rf'\b(?:by|on|next)?\s*{day_name}\b'
        if re.search(pattern, clean_text):
            current_weekday = anchor_date.weekday()
            days_ahead = target_weekday - current_weekday
            if days_ahead <= 0:
                days_ahead += 7
            return anchor_date + timedelta(days=days_ahead)

    # 7. Next month (الشهر الجاي / الشهر القادم)
    if any(k in clean_text for k in ["الشهر الجاي", "الشهر القادم", "next month"]):
        return anchor_date + timedelta(days=30)

    return None
