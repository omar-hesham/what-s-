"""
Property Stone Mode (Real Estate Domain Template).
Extracts real estate parameters from messages, voice transcripts, and documents.
Produces structured property records and listing drafts backed by source evidence.
Never fabricates missing information.
"""

import re
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from owi.core.logging import logger
from owi.db.models import Message, Property, Conversation

# Regular expressions for real estate entity extraction
AREA_PATTERN = re.compile(r'(\d+(?:\.\d+)?)\s*(?:متر|م٢|م2|م\b|sqm|sq\s*m|square\s*meters?)', re.IGNORECASE)
PRICE_PATTERN = re.compile(r'(?:سعر(?:\s+(?:الإيجار|الايجار|المتر|الشراء))?|بـ|مبلغ|price:?|offer:?)\s*(?:حوالي)?\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(ألف|الف|مليون|ملايين|k|m|egp|جنيه|دولار)?', re.IGNORECASE)
ROOMS_PATTERN = re.compile(r'(\d+)\s*(?:غرف|غرفة|نوم|rooms?|beds?)', re.IGNORECASE)
BATHS_PATTERN = re.compile(r'(\d+)\s*(?:حمام|حمامات|baths?|bathrooms?)', re.IGNORECASE)

DISTRICTS = [
    "التجمع الخامس", "التجمع الأول", "التجمع", "القاهرة الجديدة",
    "الشيخ زايد", "أكتوبر", "6 أكتوبر", "العاصمة الإدارية",
    "المعادي", "الزمالك", "المهندسين", "مدينة نصر", "مصر الجديدة",
    "New Cairo", "Sheikh Zayed", "New Capital", "Maadi", "Zamalek"
]

PROPERTY_TYPES = {
    "مكتب": "مكتب إداري",
    "office": "Administrative Office",
    "فيلا": "فيلا مستقلة",
    "villa": "Standalone Villa",
    "شقة": "شقة سكنية",
    "apartment": "Apartment",
    "محل": "محل تجاري",
    "commercial": "Commercial Store",
    "توين هاوس": "Twin House",
    "تاون هاوس": "Townhouse",
    "دوبلكس": "Duplex"
}

class PropertyStoneEngine:
    """Extracts real estate intelligence and builds verified listing drafts."""

    @classmethod
    def extract_from_conversation(cls, conversation_id: int, db: Session) -> Optional[Property]:
        messages = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.timestamp).all()
        if not messages:
            return None

        combined_text = "\n".join(m.content for m in messages)
        evidence_lines: List[str] = []

        # 1. Area extraction
        area_sqm = None
        for m in messages:
            area_match = AREA_PATTERN.search(m.content)
            if area_match:
                area_sqm = float(area_match.group(1))
                evidence_lines.append(f"المساحة: {m.content} ({m.sender_name})")
                break

        # 2. Price extraction
        price_val = None
        currency = "EGP"
        for m in messages:
            price_match = PRICE_PATTERN.search(m.content)
            if price_match:
                raw_num = price_match.group(1).replace(",", "")
                unit = (price_match.group(2) or "").lower()
                val = float(raw_num)
                if unit in ("مليون", "ملايين", "m"):
                    val *= 1_000_000
                elif unit in ("ألف", "الف", "k"):
                    val *= 1_000
                elif "دولار" in unit or "$" in m.content:
                    currency = "USD"
                price_val = val
                evidence_lines.append(f"السعر: {m.content} ({m.sender_name})")
                break

        # 3. Property Type
        prop_type = "عقار"
        for k, v in PROPERTY_TYPES.items():
            if k in combined_text.lower():
                prop_type = v
                break

        # 4. District / Location
        district_found = None
        for d in DISTRICTS:
            if d.lower() in combined_text.lower():
                district_found = d
                break

        # 5. Deal Type (Sale / Rent)
        deal_type = "sale"
        if any(w in combined_text for w in ["إيجار", "ايجار", "rent", "lease"]):
            deal_type = "rent"

        # 6. License & Finishing
        has_admin_license = any(w in combined_text for w in ["إداري", "اداري", "رخصة إداري", "admin license"])
        finishing = None
        if any(w in combined_text for w in ["الترا سوبر لوكس", "الترا لوكس", "ultra lux"]):
            finishing = "Ultra Lux"
        elif any(w in combined_text for w in ["تشطيب كامل", "سوبر لوكس", "fully finished"]):
            finishing = "Fully Finished"
        elif any(w in combined_text for w in ["نصف تشطيب", "semi finished"]):
            finishing = "Semi Finished"
        elif any(w in combined_text for w in ["طوب أحمر", "محارة", "core and shell", "core & shell"]):
            finishing = "Core & Shell"

        # 7. Rooms & Bathrooms
        rooms = None
        baths = None
        for m in messages:
            r_match = ROOMS_PATTERN.search(m.content)
            if r_match:
                rooms = int(r_match.group(1))
            b_match = BATHS_PATTERN.search(m.content)
            if b_match:
                baths = int(b_match.group(1))

        # Do not create property record if neither area nor price nor district found
        if not (area_sqm or price_val or district_found):
            return None

        # Build Title
        title_parts = [prop_type]
        if area_sqm:
            title_parts.append(f"{area_sqm} م²")
        if district_found:
            title_parts.append(f"في {district_found}")
        title = " - ".join(title_parts)

        # Generate Listing Draft
        listing_lines = [
            f"🏢 **{title}**",
            f"• **النوع:** {prop_type} ({'للبيع' if deal_type == 'sale' else 'للإيجار'})",
            f"• **المساحة:** {area_sqm or 'غير محدد'} متر مربع",
            f"• **الموقع:** {district_found or 'غير محدد'}",
            f"• **السعر:** {f'{price_val:,.0f} {currency}' if price_val else 'عند الاستفسار'}",
            f"• **التشطيب:** {finishing or 'حسب المعاينة'}",
            f"• **الترخيص الإداري:** {'نعم (مرخص إداري)' if has_admin_license else 'سكني / تجاري'}",
            f"• **الغرف/التقسيم:** {rooms or '-'} غرف | {baths or '-'} حمامات"
        ]
        listing_draft = "\n".join(listing_lines)
        evidence_str = "\n".join(evidence_lines) if evidence_lines else "مستخرج من سياق المحادثة المكتوبة."

        # Save or update Property record in DB
        prop = db.query(Property).filter(Property.conversation_id == conversation_id).first()
        if not prop:
            prop = Property(conversation_id=conversation_id)
            db.add(prop)

        prop.title = title
        prop.property_type = prop_type
        prop.area_sqm = area_sqm
        prop.location = district_found
        prop.district = district_found
        prop.price = price_val
        prop.currency = currency
        prop.deal_type = deal_type
        prop.finishing = finishing
        prop.has_admin_license = has_admin_license
        prop.rooms = rooms
        prop.bathrooms = baths
        prop.listing_draft = listing_draft
        prop.source_evidence = evidence_str

        db.commit()
        db.refresh(prop)
        return prop
