# OWI Multi-Modal AI & Processing Pipeline

OWI features a modular, local-first intelligence pipeline designed to extract structured knowledge from voice notes, images, videos, and documents without requiring cloud APIs.

---

## 1. Voice Note Processing Pipeline

```
+-----------------------------------------------------------------+
| Voice Note (.opus / .mp3 / .m4a / .wav)                         |
+-------------------------------+---------------------------------+
                                |
                                v
+-----------------------------------------------------------------+
| Audio Inspection: FFprobe / FFmpeg Duration & Format Detection  |
+-------------------------------+---------------------------------+
                                |
                                v
+-----------------------------------------------------------------+
| Local Whisper Engine (faster-whisper / Whisper on CPU / CUDA)  |
| - Profiles: LIGHT (Tiny), BALANCED (Base), QUALITY (Small)      |
| - Automatic Language & Dialect Detection (Arabic, English)      |
+-------------------------------+---------------------------------+
                                |
                                v
+-----------------------------------------------------------------+
| Segment Generation: Start, End, Text, Speaker                   |
| -> Database Storage -> Synchronized UI Audio Scrubbing Player   |
+-----------------------------------------------------------------+
```

### Key Audio Features
- **Preserves Original Media**: The original audio file is never modified or compressed destructively.
- **Timestamp Scrubbing**: Clicking any transcript segment in the UI immediately seeks the audio player to that exact second.
- **Dialect Robustness**: Engineered to handle Egyptian, Gulf, Modern Standard Arabic, and mixed Franco-Arab dialogue.

---

## 2. Image & OCR Pipeline
- **Metadata Extraction**: Inspects resolution, dimensions, and format via Pillow (`PIL.Image`).
- **Classification**: Detects screenshots, quotations, floor plans, and photographic evidence.
- **Local OCR**: Connects to locally installed Tesseract OCR (`ara+eng`) or offline optical heuristics.

---

## 3. Video Pipeline
- **Local FFmpeg Integration**: Located automatically on PATH or `C:\AI-Tools\bin\ffmpeg.exe`.
- **Audio Separation**: Extracts audio track into `.mp3` for speech transcription.
- **Intelligent Keyframe Sampling**: Rather than generating thousands of useless frames, intelligently extracts 1 frame every $N$ seconds, capping strictly at 6–10 representative frames.

---

## 4. Grounded Conversational RAG ("Ask Your WhatsApp")

Unlike cloud chatbots that fabricate answers from general web pretraining, OWI grounds all conversational responses strictly in your local database:

1. **Intent Classification**: Identifies specialized queries (e.g. asking for waiting items, tasks, decisions, or property specifications).
2. **Hybrid Retrieval**: Combines SQLite FTS5 BM25 text retrieval with 384-dimensional cosine vector similarity ranking.
3. **Mandatory Citations**: Every generated response includes verifiable citations:
   - Conversation title & ID
   - Sender name
   - Date & timestamp
   - Message text / transcript excerpt
   - Media asset reference
4. **Zero-Hallucination Safe Fallback**: If no relevant local evidence exists, the system states clearly: *"لم يتم العثور على معلومات مطابقة في قاعدة البيانات المحلية"* / *"No matching information found in local records."*
