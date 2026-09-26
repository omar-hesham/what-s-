/**
 * OWI Companion - Date & Time Parser
 * Robust parser for WhatsApp Web DOM timestamps with:
 * - Full Arabic-Indic numeral conversion (٠-٩ -> 0-9)
 * - Arabic AM/PM markers (ص, صباحاً, م, مساءً, Arabic comma ،)
 * - Unicode Bidirectional markers stripping
 * - Egyptian date order (DD/MM/YYYY) as international default with ambiguous date handling
 * - Strict calendar validation (rejects impossible dates like 31/02/2026 or 2026-02-30)
 * - Strict date presence (rejects time-only strings; never fabricates current date)
 * - Python datetime.fromisoformat compliant output (YYYY-MM-DDTHH:MM:SS)
 */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.OWIDateParser = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  const ARABIC_DIGIT_MAP = {
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9"
  };

  const BIDI_REGEX = /[\u200e\u200f\u202a-\u202e\u202f\u00a0\ufeff\u061c]/g;

  function pad(num, size = 2) {
    let s = String(num);
    while (s.length < size) s = "0" + s;
    return s;
  }

  function cleanBidi(text) {
    if (!text) return "";
    return text.replace(BIDI_REGEX, " ").trim();
  }

  function normalizeArabicDigits(text) {
    if (!text) return "";
    return text.replace(/[٠-٩]/g, (d) => ARABIC_DIGIT_MAP[d] || d);
  }

  function normalizeAmPm(text) {
    if (!text) return "";
    let s = text;
    s = s.replace(/صباحاً|صباحا/g, " AM ");
    s = s.replace(/مساءً|مساء/g, " PM ");
    s = s.replace(/[\u0635]\.?([،,\s]|$)/g, " AM $1");
    s = s.replace(/[\u0645]\.?([،,\s]|$)/g, " PM $1");
    return s;
  }

  /**
   * Parse a raw timestamp from WhatsApp Web DOM into a Date and strict ISO string.
   * @param {string} rawString - Timestamp from data-pre-plain-text or msg-meta
   * @param {Object} options - { dateOrder: "DD/MM/YYYY" | "MM/DD/YYYY" }
   * @returns {{ date: Date, iso: string, raw: string } | null}
   */
  function parseWhatsAppTimestamp(rawString, options = {}) {
    if (!rawString || typeof rawString !== "string") return null;

    const dateOrder = options.dateOrder || "DD/MM/YYYY";
    const dayFirst = dateOrder.toUpperCase().startsWith("DD");

    let cleaned = cleanBidi(rawString);
    cleaned = normalizeArabicDigits(cleaned);
    cleaned = normalizeAmPm(cleaned);
    cleaned = cleaned.replace(/[\[\]]/g, "").trim();

    // 1. Check if string is standard ISO format (e.g. 2026-09-25T10:30:00)
    const isoMatch = cleaned.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/);
    if (isoMatch) {
      const year = parseInt(isoMatch[1], 10);
      const month = parseInt(isoMatch[2], 10);
      const day = parseInt(isoMatch[3], 10);
      const hour = parseInt(isoMatch[4], 10);
      const minute = parseInt(isoMatch[5], 10);
      const second = isoMatch[6] ? parseInt(isoMatch[6], 10) : 0;

      const d = new Date(year, month - 1, day, hour, minute, second);
      // Validate that JavaScript didn't roll over impossible dates (e.g. 2026-02-30 -> March 2)
      if (
        d.getFullYear() !== year ||
        d.getMonth() !== month - 1 ||
        d.getDate() !== day ||
        d.getHours() !== hour ||
        d.getMinutes() !== minute ||
        d.getSeconds() !== second
      ) {
        return null;
      }
      const iso = `${pad(year, 4)}-${pad(month, 2)}-${pad(day, 2)}T${pad(hour, 2)}:${pad(minute, 2)}:${pad(second, 2)}`;
      return { date: d, iso: iso, raw: rawString };
    }

    // 2. Match Date component: d/d/d or d-d-d
    const dateMatch = cleaned.match(/(\d{1,4})[/\-\.](\d{1,2})[/\-\.](\d{1,4})/);
    // 3. Match Time component: hh:mm(:ss)? (AM|PM)?
    const timeMatch = cleaned.match(/(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?/i);

    // If there is no date component, DO NOT fabricate today's date
    if (!dateMatch) {
      return null;
    }

    let year = 0;
    let month = 0;
    let day = 0;

    const p1 = parseInt(dateMatch[1], 10);
    const p2 = parseInt(dateMatch[2], 10);
    const p3 = parseInt(dateMatch[3], 10);

    if (p1 > 1000) {
      // YYYY/MM/DD
      year = p1;
      month = p2;
      day = p3;
    } else {
      year = p3 < 70 ? 2000 + p3 : (p3 < 100 ? 1900 + p3 : p3);
      if (p1 > 12) {
        // Unambiguous DD/MM
        day = p1;
        month = p2;
      } else if (p2 > 12) {
        // Unambiguous MM/DD
        month = p1;
        day = p2;
      } else {
        // Ambiguous! Use user preference / Egypt default (DD/MM)
        if (dayFirst) {
          day = p1;
          month = p2;
        } else {
          month = p1;
          day = p2;
        }
      }
    }

    let hour = 0;
    let minute = 0;
    let second = 0;

    if (timeMatch) {
      hour = parseInt(timeMatch[1], 10);
      minute = parseInt(timeMatch[2], 10);
      second = timeMatch[3] ? parseInt(timeMatch[3], 10) : 0;
      const ampm = timeMatch[4] ? timeMatch[4].toUpperCase() : null;

      if (ampm === "PM" && hour < 12) {
        hour += 12;
      } else if (ampm === "AM" && hour === 12) {
        hour = 0;
      }
    }

    // Range checks
    if (month < 1 || month > 12 || day < 1 || day > 31 || hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 || second > 59) {
      return null;
    }

    const d = new Date(year, month - 1, day, hour, minute, second);

    // Strict validation against JS automatic calendar rollover (e.g. 31/02/2026 -> 03/03/2026)
    if (
      d.getFullYear() !== year ||
      d.getMonth() !== month - 1 ||
      d.getDate() !== day ||
      d.getHours() !== hour ||
      d.getMinutes() !== minute ||
      d.getSeconds() !== second
    ) {
      return null;
    }

    const iso = `${pad(year, 4)}-${pad(month, 2)}-${pad(day, 2)}T${pad(hour, 2)}:${pad(minute, 2)}:${pad(second, 2)}`;

    return {
      date: d,
      iso: iso,
      raw: rawString
    };
  }

  const MONTH_MAP = {
    // English
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6,
    "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    // Arabic
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4, "مايو": 5,
    "يونيو": 6, "يوليو": 7, "أغسطس": 8, "اغسطس": 8, "سبتمبر": 9,
    "أكتوبر": 10, "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12
  };

  /**
   * Extract a calendar date (DD/MM/YYYY) from arbitrary text (e.g. date dividers).
   * Supports numeric formats and English/Arabic month names.
   */
  function extractAbsoluteDateFromText(text, options = {}) {
    if (!text || typeof text !== "string") return null;
    const dateOrder = options.dateOrder || "DD/MM/YYYY";
    const dayFirst = dateOrder.toUpperCase().startsWith("DD");

    let cleaned = cleanBidi(text);
    cleaned = normalizeArabicDigits(cleaned).trim();

    // 1. Numeric format: 14/09/2026, 14-09-2026, 14.09.2026, 2026-09-14
    const numMatch = cleaned.match(/(\d{1,4})[/\-\.](\d{1,2})[/\-\.](\d{1,4})/);
    if (numMatch) {
      const p1 = parseInt(numMatch[1], 10);
      const p2 = parseInt(numMatch[2], 10);
      const p3 = parseInt(numMatch[3], 10);
      let year = 0, month = 0, day = 0;
      if (p1 > 1000) {
        year = p1; month = p2; day = p3;
      } else {
        year = p3 < 70 ? 2000 + p3 : (p3 < 100 ? 1900 + p3 : p3);
        if (p1 > 12) {
          day = p1; month = p2;
        } else if (p2 > 12) {
          month = p1; day = p2;
        } else {
          if (dayFirst) { day = p1; month = p2; }
          else { month = p1; day = p2; }
        }
      }
      if (month >= 1 && month <= 12 && day >= 1 && day <= 31) {
        const testD = new Date(year, month - 1, day);
        if (testD.getFullYear() === year && testD.getMonth() === month - 1 && testD.getDate() === day) {
          return `${pad(day, 2)}/${pad(month, 2)}/${pad(year, 4)}`;
        }
      }
    }

    // 2. Month name format: "14 September 2026", "September 14, 2026", "١٤ سبتمبر ٢٠٢٦"
    const words = cleaned.toLowerCase().replace(/[,،]/g, " ").split(/\s+/).filter(Boolean);
    let foundMonth = null;
    let foundDay = null;
    let foundYear = null;

    for (const w of words) {
      if (MONTH_MAP[w]) {
        foundMonth = MONTH_MAP[w];
      } else if (/^\d{4}$/.test(w)) {
        foundYear = parseInt(w, 10);
      } else if (/^\d{1,2}$/.test(w)) {
        const n = parseInt(w, 10);
        if (n >= 1 && n <= 31) {
          foundDay = n;
        }
      }
    }

    if (foundMonth && foundDay && foundYear) {
      const testD = new Date(foundYear, foundMonth - 1, foundDay);
      if (testD.getFullYear() === foundYear && testD.getMonth() === foundMonth - 1 && testD.getDate() === foundDay) {
        return `${pad(foundDay, 2)}/${pad(foundMonth, 2)}/${pad(foundYear, 4)}`;
      }
    }

    return null;
  }

  const WEEKDAY_MAP = {
    "sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4, "friday": 5, "saturday": 6,
    "الأحد": 0, "الاحد": 0,
    "الإثنين": 1, "الاثنين": 1,
    "الثلاثاء": 2,
    "الأربعاء": 3, "الاربعاء": 3,
    "الخميس": 4,
    "الجمعة": 5,
    "السبت": 6
  };

  /**
   * Parse a weekday name in English or Arabic into its 0-6 index (0 = Sunday).
   */
  function parseWeekday(text) {
    if (!text || typeof text !== "string") return null;
    const cleaned = cleanBidi(text).trim().toLowerCase();
    if (Object.prototype.hasOwnProperty.call(WEEKDAY_MAP, cleaned)) {
      return WEEKDAY_MAP[cleaned];
    }
    return null;
  }

  /**
   * Resolve an exact weekday into DD/MM/YYYY given a nearby absolute anchor date.
   * Standalone weekday without absolute anchor remains unresolved (returns null).
   */
  function resolveWeekdayWithAnchor(weekdayText, anchorDate) {
    const targetDay = parseWeekday(weekdayText);
    if (targetDay === null) return null;
    if (!anchorDate) return null;

    let aDate = null;
    if (anchorDate instanceof Date) {
      aDate = new Date(anchorDate.getTime());
    } else if (typeof anchorDate === "string") {
      const m = anchorDate.match(/^(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})$/);
      if (m) {
        aDate = new Date(parseInt(m[3], 10), parseInt(m[2], 10) - 1, parseInt(m[1], 10));
      } else {
        const p = parseWhatsAppTimestamp(anchorDate);
        if (p) aDate = p.date;
      }
    }
    if (!aDate || isNaN(aDate.getTime())) return null;

    const anchorDay = aDate.getDay();
    // Only resolve if anchor matches the weekday exactly (no nearest-weekday arithmetic)
    if (targetDay === anchorDay) {
      return `${pad(aDate.getDate(), 2)}/${pad(aDate.getMonth() + 1, 2)}/${pad(aDate.getFullYear(), 4)}`;
    }

    return null;
  }

  /**
   * Parse a date divider text into DD/MM/YYYY.
   * Handles absolute dates, TODAY / YESTERDAY (and Arabic equivalents),
   * and weekdays with explicit anchor evidence (standalone weekday remains null).
   */
  function parseDateDivider(text, refDate = new Date(), options = {}) {
    if (!text || typeof text !== "string") return null;
    const cleaned = cleanBidi(text).trim().toLowerCase();

    if (cleaned === "today" || cleaned === "اليوم") {
      const d = refDate instanceof Date ? refDate : new Date();
      return `${pad(d.getDate(), 2)}/${pad(d.getMonth() + 1, 2)}/${pad(d.getFullYear(), 4)}`;
    }
    if (cleaned === "yesterday" || cleaned === "أمس") {
      const d = refDate instanceof Date ? new Date(refDate.getTime() - 86400000) : new Date(Date.now() - 86400000);
      return `${pad(d.getDate(), 2)}/${pad(d.getMonth() + 1, 2)}/${pad(d.getFullYear(), 4)}`;
    }

    const anchor = options.anchorDate || null;
    if (anchor && parseWeekday(cleaned) !== null) {
      return resolveWeekdayWithAnchor(cleaned, anchor);
    }

    return extractAbsoluteDateFromText(text, options);
  }

  /**
   * Combine a standalone time string with a defensible date string and parse strictly.
   */
  function combineTimeAndDate(timeStr, dateStr, options = {}) {
    if (!timeStr || !dateStr) return null;
    const combined = `${timeStr}, ${dateStr}`;
    return parseWhatsAppTimestamp(combined, options);
  }

  return {
    cleanBidi,
    normalizeArabicDigits,
    normalizeAmPm,
    parseWhatsAppTimestamp,
    extractAbsoluteDateFromText,
    parseWeekday,
    resolveWeekdayWithAnchor,
    parseDateDivider,
    combineTimeAndDate
  };
});

