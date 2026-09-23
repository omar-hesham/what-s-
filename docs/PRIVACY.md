# OWI Privacy & Data Sovereignty Architecture

Personal and commercial WhatsApp conversations contain sensitive financial figures, private voice messages, confidential documents, and personal contact details. **OWI is built from the ground up to guarantee 100% data sovereignty.**

---

## 1. Core Privacy Commitments

1. **On-Device Storage Only**: All databases, message contents, audio files, images, OCR texts, and derived knowledge records remain strictly on your local disk (`data/`).
2. **Zero Cloud Telemetry**: OWI sends zero analytics, zero usage pings, and zero tracking metrics to any external server.
3. **No Automatic AI Uploads**: Default NLP, transcription, OCR, and search run entirely on local CPUs/GPUs using local models and algorithms.
4. **Complete Data Deletion**: Users can delete individual conversations, clear temporary derived caches, or wipe the entire database directly from the application.

---

## 2. Optional Cloud Services Policy

If optional cloud AI models (e.g. OpenAI or Gemini) are integrated by developers in future extensions:
- They must remain **disabled by default**.
- The UI must clearly display a warning specifying exactly what text will leave the machine.
- Cloud services must never be activated silently or automatically.
