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

  return {
    cleanBidi,
    normalizeArabicDigits,
    normalizeAmPm,
    parseWhatsAppTimestamp
  };
});
