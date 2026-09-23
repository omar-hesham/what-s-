# OWI Testing & Quality Assurance

OWI is backed by a comprehensive suite of 27 automated tests verifying every aspect of parsing, security, date calculation, NLP extraction, domain templates, and API endpoints.

---

## 1. Test Suite Summary

| Test File | Scope |
| :--- | :--- |
| `tests/test_acceptance_100_msgs.py` | Full end-to-end acceptance test with 105 messages synthetic WhatsApp archive, media linking, NLP, property extraction, and grounded RAG citations. |
| `tests/test_whatsapp_parser.py` | 12h/24h timestamps, iOS and Android formats, Arabic locale timestamps with Unicode bidirectional markers, multiline messages, attachments, system events. |
| `tests/test_security_zip_slip.py` | Verification that Zip Slip directory traversal attacks are completely blocked and harmless filenames are properly sanitized. |
| `tests/test_date_resolver.py` | Anchor-based relative date calculations for Arabic and English ("tomorrow", "in 3 days", "next Thursday") relative strictly to message timestamps. |
| `tests/test_nlp_extraction.py` | Task extraction with confidence scoring, waiting-for items, decisions, commitments, and real estate Stone Mode property extraction. |
| `tests/test_deduplication.py` | SHA-256 fingerprinting and idempotent import behavior ensuring re-importing identical exports never creates duplicate records. |
| `tests/test_search_and_rag.py` | FTS5 full-text indexing, 384-dimensional cosine vector embeddings, and Ask Your WhatsApp grounded conversational search. |
| `tests/test_api_endpoints.py` | FastAPI HTTP endpoints for health, cost audit ($0.00 confirmation), system resources, and storage dashboard. |

---

## 2. Test Execution Commands

To execute all tests with detailed verbose output:
```powershell
.\backend\.venv\Scripts\pytest.exe tests -v
```
All 27 tests pass in ~2.5 seconds on a standard Windows PC.
