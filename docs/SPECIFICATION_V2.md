<USER_REQUEST>
# Omar WhatsApp Intelligence (OWI)

## Revised implementation specification and AI execution brief — v2.0

Prepared for Omar • 23 September 2026

Status: proposed implementation specification. No implementation, hardware benchmark, model accuracy, or security test is claimed to have passed by this document.

## 1. Instructions to the implementing AI

Build OWI according to this specification, in the phases and acceptance gates below. Deliver working vertical slices with evidence. This document defines the full product direction and the smaller initial release.

Before modifying code, inspect the selected project, applicable repository instructions, existing implementation, and uncommitted changes. Reuse valid work and preserve unrelated files. If the destination project is unknown, resolve that location with Omar before creating an application in an arbitrary directory. Work within the authorized local project; this specification does not authorize cloud deployment, purchases, uploading private conversations, sending messages, or modifying other applications.

Proceed autonomously on routine, reversible implementation decisions within scope. Ask only when a missing fact materially affects data interpretation, privacy, cost, or an irreversible action. Record assumptions and decisions. Do not repeatedly seek approval for ordinary coding and testing.

Required working documents:

- `docs/implementation-status.md`: phase, completed work, evidence, failures, and remaining work.
- `docs/decisions.md`: important choices, alternatives, and consequences.
- `docs/compatibility.md`: exact tested OS, Python, package, model, and accelerator versions.
- `docs/data-model.md`, `docs/security.md`, and `docs/acceptance-report.md`.
- A task list with dependency order, clear completion criteria, and links to evidence.

Do not claim completion from successful installation, application startup, passing mocks, or screenshots alone. Distinguish implemented, tested on fixtures, tested on real data, and release-verified. Never invent benchmark results. Do not replace difficult features with decorative controls or hard-coded demo output.

If real evaluation data is unavailable, continue using clearly labeled synthetic fixtures and report the real-data evaluation gap. Do not claim production accuracy or interrupt independent development unnecessarily.

## 2. Product purpose and boundaries

OWI is a local application for turning user-supplied WhatsApp exports and associated files into a searchable archive, reviewed tasks, commitments, decisions, and source-grounded answers. Omar works in Arabic and English, including Egyptian Arabic and mixed-language conversations.

The primary workflow is:

**Import → inspect original conversation → search → review suggested knowledge → follow up using verified evidence.**

Non-negotiable requirements:

1. No mandatory paid APIs, cloud subscriptions, paid vector services, credit cards, or recurring software-service charges.
2. Private content, embeddings, transcripts, and derived knowledge remain local by default.
3. After dependencies and chosen models are installed, all enabled core functions operate without internet access.
4. Every extracted fact and factual answer claim has traceable evidence, or is explicitly marked as uncertain/inferred.
5. User corrections survive reprocessing, model changes, and repeated imports.
6. No silent loss, guessed identity merges, invented deadlines, or hidden network fallback.
7. Arabic RTL and English LTR are first-class requirements.
8. SQLite is the authoritative data store. Search indexes and model outputs are replaceable derivatives.

“No recurring software-service charges” does not mean no electricity, hardware, storage, maintenance, or initial download requirements. Explain these honestly.

WhatsApp and Notion describe the workflow inspiration. This plan does not include live WhatsApp synchronization or Notion integration. OWI reads supplied exports; it must not imply access to messages missing from those exports. External synchronization requires a separate scope decision.

## 3. Release scope

### Initial usable release: phases 0–2

- TXT/ZIP WhatsApp import with preview, locale clarification, source preservation, and overlap handling.
- Conversation timeline, participant mapping, original message inspection, and attachment status.
- Arabic/English full-text search with conversation, person, date, and file filters.
- Manual tasks plus conservative rule-generated suggestions that require review.
- Task editing, dismissing, status changes, and evidence navigation.
- Recoverable jobs, local security controls, backup/restore, export, and a Windows launcher.

### Subsequent releases

- Phase 3: audio transcription and synchronized playback.
- Phase 4: multilingual semantic search, local LLM extraction, summaries, and grounded Q&A.
- Phase 5: OCR, documents, and video processing.
- Phase 6: property/research workflows, richer relationships, optional folder watcher and browser companion.
- Phase 7: full-scope release hardening and distribution verification.

Security, recovery, provenance, and basic packaging start early and remain acceptance requirements in every phase. Phase 7 does not defer those responsibilities.

## 4. Architecture and technology decisions

```text
Browser UI opened by a Windows launcher
React + TypeScript + Vite + Tailwind CSS + Lucide
                      |
        Same-origin HTTP API + authenticated SSE
                      |
            FastAPI application process
    Auth/session | validation | queries | job submission
                      |
      SQLite: records, provenance, FTS5, durable jobs
                      |
       Separate supervised worker process
  Import | transcription | OCR | embeddings | extraction
                      |
       Managed local originals and derived assets
                      |
 Optional local model runtime through restricted loopback
```

Decisions:

- Deliver a browser-based local application launched from a Windows shortcut first. Do not present it as a native desktop installer until distribution testing proves that deliverable. A native shell is optional future scope.
- Serve the built frontend and API from the same origin in release mode. Vite development mode is not the release runtime.
- Use REST plus SSE for progress. Do not add WebSockets unless a demonstrated feature requires bidirectional streaming.
- Use Python 3.12 as the initial compatibility candidate, not a compatibility guarantee. Verify dependency wheels and actual imports on Windows; document a justified alternative if necessary. Do not alter system Python.
- Use supported stable frontend versions, lockfiles, and exact release dependencies. Do not select an old major version merely because the original plan listed it.
- Use SQLAlchemy with migrations, SQLite WAL, enabled foreign keys, bounded busy timeout, and short write transactions.
- Run heavy processing in a separate worker process. Limit concurrent expensive jobs to one initially; raise concurrency only after measurement.
- Use a local managed filesystem for media. Avoid an active database on network shares or synchronized folders.
- Start semantic retrieval with batched exact cosine search over local vectors if the target corpus meets measured latency/memory limits. Add an approximate index only when evidence justifies it. Never require a separate database server.
- Default local LLM adapter: Ollama on loopback with a verified locally executed model. Direct GGUF runtime support is a later adapter, not a second mandatory runtime.
- Transcription: faster-whisper as the initial engine. OCR: locally installed Tesseract with Arabic/English language data as the baseline. Document parsers must be selected for Windows compatibility and license suitability.

Store application data outside the repository in a user-selected local data directory. Keep dependencies and model caches identifiable and account for their disk usage.

## 5. Hardware and first-run capability detection

Inventory the actual device: OS build/architecture, CPU, RAM, available storage, GPU/VRAM, driver/runtime compatibility, and installed dependencies. Do not infer those facts from old notes or from the presence of a GPU alone.

Offer independent capability states:

| Capability | Without downloaded AI models | With compatible local model |
|---|---|---|
| Import, timeline, manual tasks, FTS search | Available | Available |
| Conservative rule suggestions | Available, limited | Available |
| Speech transcription | Unavailable until model installed | Available after smoke test |
| Semantic search | Unavailable until embedding model installed | Available after indexing |
| Open-ended Q&A and advanced extraction | Disabled with explanation | Available after validation |
| OCR | Depends on installed OCR engine/language data | Available if engine/data present |

Show model sizes, download sources, license information, expected storage, and CPU/GPU selection before downloads. Verify hashes where supplied; pin model revisions or digests. No silent download of multi-gigabyte models. Interrupted downloads must be retryable.

Initial speech candidates: tiny/base for speed, small for balance, medium for quality, subject to local measurements. These labels indicate tradeoffs, not guaranteed Arabic accuracy. CPU INT8 is the baseline candidate. GPU execution requires an actual test, not just detection.

Select the local LLM after measuring a quantized multilingual instruction model on Omar's hardware and a labeled Arabic/English extraction sample. Record model family, revision/digest, quantization, context limit, RAM/VRAM, speed, license, and evaluation results. Do not promise a particular large model before that test.

The wizard collects language, data folder, timezone (default Africa/Cairo), date-format policy, identity mappings for “me,” and resource limits. Do not assume the contact named Omar is necessarily the export owner.

## 6. Import and parser contract

### Source preservation and staging

Keep an immutable copy of each imported source, its SHA-256, original filename, byte size, import time, detected encoding, parser version, and import settings. Stage parsing before committing conversation records. Copy inputs; never move or modify the user's originals.

Each import preview displays:

- Detected format, locale, date range, timezone assumption, message/event counts, and warnings.
- Potential conversation matches and new/overlapping/ambiguous record counts.
- Missing media, unsupported files, and unparsed source spans.
- Choices needed to resolve ambiguous dates, conversation identity, or participant mapping.

### Supported parsing behavior

- Explicit adapters/fixtures for Android and iOS text export variants, 12/24-hour times, optional seconds, brackets/dashes, and two-/four-digit years.
- DD/MM/YYYY, MM/DD/YYYY, and ISO-style dates where identifiable.
- Arabic/English AM/PM indicators, Arabic/Persian digits where supported, and directional/nonbreaking spacing characters.
- Multiline text, multiline captions, emoji, URLs, sender names containing punctuation, and message-like text inside message bodies.
- System events, unknown events, and ordinary messages as distinct categories. Unknown content must be preserved, not discarded.
- Conservative handling of malformed headers; report recovery and uncertainty rather than silently assigning a new sender/date.

Preserve the exact original text and line/byte ranges. Apply decoding and normalization to separate derived fields. Never strip bidi characters from the evidence copy just to simplify parsing.

### Ambiguity and time

- Infer date ordering at file level only when evidence supports it. A file containing only ambiguous dates such as 03/04/2026 requires confirmation or an existing explicit profile.
- Preserve raw timestamps, observed precision, source timezone assumption, and resolved local/UTC values when determinable.
- Do not invent seconds. Retain source order for records sharing the same displayed time.
- For nonexistent or repeated local times at DST boundaries, retain the ambiguity; use timezone rules, not a fixed Cairo UTC offset.
- Unresolved dates block deadline derivation and definitive time ordering for affected records, not preservation of the source itself.
- Define and show the two-digit-year interpretation policy rather than guessing silently.

### ZIP and attachment handling

Reject path traversal, absolute paths, drive-qualified/UNC paths, alternate data stream names, symlink/reparse escapes, and paths resolving outside the extraction root. Validate archive expansion size, entry count, compression ratio, filename length, and case-insensitive collisions before/while extracting. Use bounded temporary directories and cleanup on failure.

Associate media by explicit reference and import context. Represent attachment states as available, omitted, missing, unsupported, ambiguous, or failed. A “Media omitted” marker is not evidence for choosing a nearby file. Shared asset bytes may be deduplicated while every attachment occurrence remains linked to its message.

Support standalone file imports with their own source identity and provenance. Do not fabricate a sender or conversation for them.

## 7. Identity, deduplication, and repeated imports

Separate three concepts:

1. Source-file identity: byte-identical imported files.
2. Asset identity: identical binary media stored once with multiple references.
3. Message identity: the same message observed in overlapping exports.

Use stable internal IDs. TXT exports must not be assumed to contain stable WhatsApp server message IDs.

Conversation titles and display names are not unique identifiers. Require an explicit conversation match when ambiguous. Contacts retain aliases and import-specific participant mappings; never merge people solely because their names match.

Within a confirmed conversation, identify candidate overlapping spans using sender mapping, timestamp precision, content, attachment references, occurrence counts, and ordered neighboring messages. Preserve repeated identical messages as separate occurrences when the source supports them.

Conservative policy: automatically merge only high-confidence aligned observations. Keep uncertain imports staged for review or preserve separate records flagged as potential duplicates. Do not turn a fuzzy similarity threshold into irreversible deletion. Multiple source observations may point to one canonical message.

Acceptance scenarios include identical files with different names, renamed conversations, partial older exports, longer new exports, repeated identical texts within a minute, reordered media, missing attachments, edited/deleted-message representations, and corrected import settings.

Reimport must not reset task statuses, overwrite accepted fields, or duplicate derivative processing needlessly. Changes in parser/model versions create a new processing run and reviewable differences. Import undo removes that import's observations and unreferenced derivatives without deleting records still supported by other imports; user-authored work must be retained or explicitly resolved.

## 8. Data model and provenance

Use relational tables with explicit constraints. Introduce specialized entities when their phase begins, rather than creating unused screens and speculative abstractions.

### Core records

- `ImportBatch`, `SourceFile`, `SourceObservation`, `ParseIssue`.
- `Conversation`, `Contact`, `ParticipantMapping`, `Message`, `MessageObservation`.
- `MediaAsset`, `MessageAttachment`, `Document`, `DocumentChunk`.
- `Transcript`, `TranscriptSegment`, `ProcessingRun`, `Job`.
- `EvidenceRef`, `Suggestion`, `Task`, `TaskEvent`, `FieldOverride`.
- `Commitment`, `Decision`, `Idea`, `WaitingFor`, `Project`.
- Later: `PropertyListing`, `PropertyObservation`, `ResearchTopic`, `ResearchFinding`.
- `Entity` registry and typed `Relationship` records when cross-entity links become necessary.

Use real foreign keys through the entity registry for graph endpoints, with enforceable subtype ownership. Avoid arbitrary unvalidated table-name/ID pairs. Each inferred relationship carries evidence, review status, and extraction version. A relationship table is sufficient initially; a graph server is not required.

### Evidence requirements

An evidence reference can target an original message span, original source range, transcript segment and time range, PDF page, DOCX paragraph/table cell, spreadsheet sheet/cell range, image OCR region, or video time range/frame.

Every derivative stores source IDs, processing-run ID, provider/model version, prompt/rule version, creation time, and relevant extraction settings. Use durable application IDs for citations; do not rely on transient vector-index positions.

Raw sources, extracted observations, and current reviewed records are separate layers. Store proposed and accepted values separately where needed. User-authored fields may legitimately have no imported evidence and must be labeled as user-authored, not AI-extracted.

Updating a transcript or parser invalidates dependent derived results and queues rebuilds. Existing reviewed items retain their state and receive a reviewable change proposal. Retain the evidence revision used to produce earlier results unless the user deletes that source.

### State models

- Suggestions: pending, accepted, rejected, superseded.
- Tasks: open, waiting, completed, dismissed. Inbox is a view of pending suggestions, not a conflicting task lifecycle state.
- WaitingFor: open or resolved; overdue is computed from a confirmed due date and current time.
- Jobs: queued, running, succeeded, failed, cancelled; include attempt, lease, heartbeat, progress, and error code.

Use optimistic concurrency/version checks for editing. Stale worker output must not overwrite a newer user edit.

## 9. Task, commitment, decision, and date extraction

Start with transparent rules, then add local-model structured extraction. Providers return validated schemas; malformed or unsupported output becomes a failure/review item, not partially trusted database changes.

Extract from bounded conversation windows with surrounding messages, participant information, and visible topic context. Single-message matching is only sufficient for simple explicit cases.

Distinguish:

- A request from an accepted commitment.
- A suggestion from an agreed decision.
- An intention from completed work.
- A cancellation from an active obligation.
- A changed deadline from a second independent task.
- A quoted/forwarded statement from a commitment by the sender.

Example: “Can you send it tomorrow?” → “Thursday works instead” → “Agreed” should yield a reviewable Thursday commitment, with all relevant evidence and the original proposed date retained in history.

Each suggestion includes action, assignee, beneficiary/requester if known, conversation/project, evidence references, proposed due value, uncertainty reasons, and rule/model provenance. Unknown people or dates remain unknown.

Relative-date resolution uses the source message's local calendar date and timezone. Import time and the computer's current date are never substitutes. “Tomorrow” on 2026-09-14 resolves to 2026-09-15 when that source date is confirmed. Weekday phrases, “next Thursday,” “end of the week,” holidays, and vague Arabic expressions require explicit policy or review. Never convert “soon” into a date.

Represent date-only deadlines as dates, not invented midnight appointments. Separate extraction of the due date from the UI policy for showing overdue items.

All extracted work enters review initially. Accept, edit, merge, split, reject, and dismiss are supported. Completing an item requires a user action or a separately reviewed completion suggestion. Do not auto-send reminders or messages to anyone.

Confidence is an explainable ranking signal unless calibrated against labeled data. Show uncertainty reasons. Do not display a generated 0.95 as a verified 95% probability.

## 10. Full-text and semantic search

Maintain original display text and a separate search representation. Define a reversible-to-source mapping for highlighting normalized results.

Arabic search normalization may remove tatweel and optional diacritics, normalize configured alef variants and digit forms, and standardize whitespace. Keep aggressive substitutions configurable and tested because distinct names/words must not be silently conflated. Do not alter original text. Test Arabic/English mixing, transliterated names, and Franco-Arab; unsupported transliteration must be acknowledged.

Use FTS5 BM25 with field weighting and filters for conversation, participant, date range, entity type, attachment type, and review status. Parameterize queries and safely handle malformed user search syntax.

For embeddings, benchmark a multilingual candidate such as `paraphrase-multilingual-MiniLM-L12-v2` against representative Arabic/English retrieval queries. Treat it as a candidate, not an accuracy guarantee. Do not default to the original plan's monolingual-oriented example without Arabic evaluation.

Chunk conversations with overlapping context windows, preserving sender/time boundaries and evidence mapping. Keep documents/transcripts chunked by their own structure. Respect the chosen model's input limit and report truncation.

Fuse lexical and semantic rankings, initially using reciprocal rank fusion. Apply user filters consistently. Optional reranking is justified only by measured quality and resource cost.

Persist model revision, vector dimension, normalization method, chunking version, and source version. Never mix incompatible embeddings in one index. Build replacements separately and switch only after validation. Deletions and revisions invalidate both lexical and semantic derivatives.

When semantic components are unavailable, full-text search remains functional with a clear capability indicator. Vector indexes must be reconstructable from authoritative records.

## 11. Grounded local Q&A and summaries

Pipeline: interpret scope → retrieve/filter → expand relevant context → generate structured claims/citations → validate citation references → display with limitations.

Requirements:

- Each factual answer claim links to evidence that supports that claim. A valid message ID alone is not proof of semantic support.
- Evidence opens the exact message or source location, with surrounding context and original content accessible.
- Preserve superseded statements and explicitly present conflicts or date changes.
- If evidence is missing or insufficient, abstain rather than fill gaps from general model knowledge.
- Label inference separately from direct statements.
- Describe coverage: imported date range, selected conversations, missing media, failed jobs, and other relevant limitations.
- Questions about counts or “all overdue tasks” use deterministic, allowlisted structured queries, not a top-k semantic sample. Do not execute unrestricted SQL generated by the model.
- Summaries are generated per defined scope and tied to source/processing versions; mark them stale when underlying data changes.
- Without a local LLM, offer ordinary search and evidence views instead of pretending to answer open-ended questions.

Conversation and document content is untrusted input. It cannot override system instructions, grant permissions, invoke tools, change settings, access arbitrary paths, or trigger outgoing network calls. Keep model output as data, validate it, and never render generated HTML as trusted UI.

Citation validation checks existence, allowed scope, source version, and quoted spans. Evaluate semantic support separately using labeled examples and human review; mechanical citation checks cannot guarantee truth. Do not advertise hallucination-free operation.

## 12. Audio, images, documents, and video

### Audio

Use faster-whisper locally with bounded duration/size limits and configurable voice activity detection. Store original audio, transcript revisions, timestamped segments, language hints, and processing configuration. Allow mixed-language input; evaluate Egyptian/Gulf Arabic and code-switching separately.

Support playback, seek-to-segment, transcript correction, and reprocessing previews. Timestamp precision must match measured alignment; do not claim word-level accuracy from segment-level timestamps. Do not equate the voice speaking inside an attachment with the WhatsApp sender. Diarization/speaker identification is outside baseline scope.

Silence, noise, music, and very short clips belong in tests. Report uncertain transcript content, especially names, amounts, and dates. A transcript citation must allow replaying the supporting audio.

### Images and OCR

Handle orientation, bounded resolution, Arabic/English OCR, bounding boxes, and confidence where actually supplied by the engine. Preserve original images. Receipt/quotation extraction creates reviewable structured proposals with currency/amount uncertainty; OCR output alone is not financial verification.

Screenshot classification and semantic visual understanding are optional later capabilities. Do not label an OCR-only pipeline as general image understanding.

### Documents

- PDF: extract embedded text per page; use OCR for image-only pages when available. Preserve page mapping.
- DOCX: paragraphs and tables with stable location metadata.
- XLSX: sheets/cells, raw values, formulas, and available cached values as distinct fields. Do not execute macros or claim cached values are freshly recalculated.
- TXT/CSV: explicit encoding and delimiter handling; preserve row/column references.
- Handle corrupt, unsupported, encrypted, and password-protected files as visible states; never discard them silently.
- Text and table extraction quality must be tested on Arabic/bidi examples. Preserve uncertain table structure rather than inventing columns.

### Video

Use local FFmpeg to obtain audio and bounded scene/frame samples. Store timecode/frame-to-source mapping. Explain that sampled frames are partial coverage; do not claim exhaustive visual understanding. Apply job cancellation, duration limits, resource caps, and temporary-file cleanup.

Document/media tools must not execute attachments, macros, embedded scripts, or remote linked resources.

## 13. Specialized knowledge workflows

### People and projects

Maintain manual contact aliases and explicit project assignments first. Suggested links are reviewable. Never infer sensitive attributes or claim identity from weak name similarity.

### Properties / Stone Mode

Store listing observations with source date, transaction type, district, area and unit, total/per-unit price, currency, payment terms if explicit, finishing, license claim, amenities, and source contact. Missing values remain null.

Treat license/ownership/availability as source claims, not independently verified facts. Preserve price and availability history. Avoid merging similar listings without sufficient evidence. Listing drafts must exclude unsupported claims and remain unpublished drafts. No external publishing is included.

### Research mode

Store topics, questions, findings, quotations, and citations to imported materials. Separate source statements from synthesis and contradictions. External literature search, live link verification, and academic-rubric evaluation are separate future capabilities, not implicit features of local RAG.

### Relationship exploration

Start with source-linked related-items panels. Add a visual graph only after identity/link quality is demonstrated and it serves a specific navigation need.

## 14. UI and interaction requirements

Initial navigation: Inbox, Chats, Tasks, Search, Files, Settings. Add Today, Waiting For, Decisions, Ideas, People, Projects, Properties, and Research only when their workflows function.

Layout: navigation sidebar, central conversation/content view, and optional evidence/intelligence panel. Support keyboard navigation, accessible controls, large timelines with virtualization, pagination, loading/error/empty states, and readable typography.

Arabic UI uses real document/component direction, logical CSS properties, bidi isolation for numbers/filenames/URLs, and mixed-language content handling. Test selection, copy/paste, keyboard navigation, and source highlighting. English and Arabic strings belong in localization resources.

Required interactions:

- Import wizard with preview, ambiguity resolution, progress, cancel, and final reconciliation report.
- Timeline with stable source links and visible missing-media states.
- Inbox with evidence, uncertainty explanation, edit/accept/reject, and bulk actions only where safe.
- Task history and visible distinction between a suggested value and an accepted value.
- Audio player synchronized to transcript segments when that capability exists.
- Today view based on confirmed tasks/waiting items; optional generated narrative clearly separated.
- Settings for capabilities, model management, privacy, storage, jobs, backup, and deletion.

Replace a decorative “$0 verified” screen with a factual capability/resource screen: enabled local providers, model locations/sizes, runtime addresses, download policy, telemetry state, and what remains untested. Do not display security or cost badges unsupported by actual checks.

No raw stack traces in ordinary workflows. Offer redacted diagnostics for troubleshooting.

## 15. Durable jobs and recovery

Use SQLite-backed jobs claimed atomically with a lease and worker identifier. Keep transactions short; release database locks before decoding media or running models. Supervise the worker and distinguish process health from actual progress.

Each job has an idempotency key derived from source identity/version, operation, configuration, and relevant engine/model version. Output commits are transactional; temporary artifacts use atomic promotion after completion. Filesystem and database consistency requires explicit recovery logic because they do not share one transaction.

Implement bounded retries with backoff for retryable failures. Corrupt inputs, invalid settings, and missing models need actionable failure states, not endless retries. Recover expired leases after crashes. Support cancel and restart, stage checkpoints where useful, and cleanup of abandoned temporary output.

Maintain resource limits for CPU threads, RAM-sensitive batch sizes, GPU work, disk quotas, and temporary files. Foreground queries should remain usable during processing. Never load every heavy model simultaneously by default.

## 16. Security, privacy, backup, and deletion

### Local access boundary

- Bind the application to loopback, not all network interfaces. Do not create firewall exceptions or public tunnels.
- Authenticate application sessions. A random port alone is not authentication.
- Recommended launcher flow: short-lived, one-use bootstrap secret delivered in a URL fragment, exchanged for a local HttpOnly SameSite=Strict session cookie, then removed from browser history/address state. Never place long-lived secrets in query strings, persistent browser storage, logs, or command output. Test the complete bootstrap flow.
- Validate Host and Origin against explicit local values to mitigate DNS rebinding and cross-origin abuse. Do not use wildcard CORS.
- Protect state-changing cookie-authenticated requests with anti-CSRF controls. Protect SSE/media/document endpoints too; test same-origin media access.
- Use separate revocable credentials and narrow permissions for a future companion. Do not reuse the main session secret.
- Restrict local model runtime connections to the configured verified loopback service. Do not silently follow redirects or enable a cloud fallback.

### Content and storage

- Render imported content as inert text; sanitize any allowed markup. Do not execute HTML/SVG/scripts from attachments in the app origin.
- Use opaque asset IDs rather than arbitrary filesystem paths in API requests. Validate every resolved file path against the managed root.
- Run parsers/media tools with limits and timeouts. Pass subprocess arguments safely; never construct shell commands from filenames or message text.
- Keep logs free of message bodies, credentials, and unnecessary personal information. Diagnostics exports are redacted.
- Disable application telemetry and automatic update checks by default. Document dependencies' network behavior and test an offline run.
- Limit Windows file permissions appropriately. State clearly whether data is encrypted at rest. For the first release, rely on a documented user-managed encrypted volume if selected; do not invent custom cryptography or imply ordinary SQLite is encrypted.
- Threat model: reduce exposure to websites, accidental sharing, and untrusted input. Do not claim protection from a compromised OS or administrator.

### Backup and restore

Provide a consistent backup using SQLite's supported backup mechanism and a coordinated immutable-asset snapshot/manifest. Include authoritative records, sources, required settings, schema version, and integrity hashes. Exclude regenerable caches/models by default and list what is excluded.

Do not copy only a live `.db` file while ignoring WAL state. Verify backups, restore into staging, validate database/media integrity, and switch only after success. Require confirmation before replacing an existing active dataset. Test upgrade/restore paths and keep pre-migration recovery options.

### Deletion

Explain separate actions: remove an import, delete a conversation/source, and clear the managed dataset. Show affected derived records and require confirmation for destructive deletion.

Cascade/invalidate transcripts, OCR, embeddings, FTS entries, summaries, suggestions, and relationships as appropriate. Preserve shared assets until no retained source references them. External/manual backups are not silently modified; explain their retention implications. Ordinary deletion is not guaranteed forensic erasure on SSDs or in existing backups.

## 17. Optional ingestion extensions

Folder watching is disabled by default. Users select exact folders; debounce changes, wait for file stability, exclude managed output/model/cache folders, prevent import loops, and apply the same security/deduplication rules as manual import.

Define the browser companion narrowly: import explicitly selected content/files with provenance and user-visible destination. It is not a live WhatsApp account connector. Require pairing, scoped tokens, revocation, exact origin rules, and documented browser permissions. Do not collect cookies, credentials, or background conversation content. Defer implementation until core import/security gates pass.

## 18. Windows distribution and lifecycle

Target Windows 10/11 x64 subject to a documented tested-build matrix. Do not claim OS support that has not been tested. Do not claim ARM64 support implicitly.

Early development: project-local virtual environment and locked frontend dependencies. Release: reproducible installation/bootstrap or a bundled runtime that works on a clean supported machine. Do not depend on tools installed only on the developer's device.

Launcher responsibilities: single-instance detection, dependency/capability checks, safe free-port selection, authenticated startup, hidden background API/worker processes, browser opening, health errors, and clean shutdown. Do not open unnecessary console windows or change machine-wide execution policy.

Support paths with spaces and Arabic characters, standard-user installation, model download failures, port conflicts, low disk space, offline relaunch, and upgrade with preserved data. Validate FFmpeg/OCR/runtime redistribution licenses before bundling. Include dependency/model licenses and notices.

Uninstall preserves user data by default and explains how to remove it separately. Model and application updates are explicit; upgrades include migrations and rollback/recovery guidance.

## 19. Testing and measurable acceptance

The following are proposed acceptance targets, not measured claims. Confirm the benchmark hardware/corpus in phase 0. If a target cannot be met, report the observed result and tradeoff; do not silently lower it or claim a pass.

### Evaluation data

- Maintain a versioned parser/security regression corpus with supported real-world format variants and adversarial fixtures.
- Create synthetic end-to-end scenarios including Arabic, English, Franco-Arab, system events, assets, negotiations, cancelled work, deadline changes, and repeated messages.
- When Omar supplies consented examples, create a locally retained, de-identified evaluation set with manually checked expected messages/entities/answers.
- Use a fixed held-out set separate from prompt/rule tuning. Record its composition and denominator in reports. Synthetic success is not evidence of real-world language accuracy.
- Suggested minimum for an initial intelligence evaluation: 100 labeled extraction windows, 50 retrieval questions, and 40 Q&A cases spanning answerable, conflicting, and unanswerable questions. Report gaps and expand coverage as needed.

### Acceptance targets

| Area | Proposed acceptance gate |
|---|---|
| Source accounting | Every source span is retained or explicitly classified as a header/blank/issue; no silent content loss. |
| Supported parser cases | All fixed regression cases pass; at least 99.5% correct message boundaries/field assignments on the labeled supported-format set, with errors listed. |
| Ambiguity | All ambiguous-date and identity fixtures are flagged; no silent resolution without explicit policy/evidence. |
| Deduplication | Byte-identical reimport adds no duplicate canonical records; zero false merges in the held-out overlap/repetition suite. Unresolved overlap is visible. |
| User edits | Reimport, model rerun, migration, and stale-job tests preserve accepted edits and task state. |
| Extraction | Suggested actionable items reach at least 90% precision and 80% recall on the held-out labeled set; report assignee/date errors separately. Human review remains required. |
| Dates | All deterministic relative-date regression cases pass; ambiguous phrases remain unresolved or reviewable. |
| Retrieval | At least 90% of labeled answerable queries retrieve supporting evidence in the top 10; report Arabic, English, and mixed-language subsets. |
| Q&A evidence | Citation references resolve in 100% of test answers; at least 95% of factual claims are judged supported on the held-out set. Unsupported claims remain recorded as failures. |
| Abstention | All fixed insufficient-evidence/conflict regression cases handle limitations correctly; report broader held-out abstention results separately. |
| Audio | Report WER/CER by language and named-entity/date/amount error counts on transcribed reference clips. Set a numeric release threshold after the phase-0 sample; no unsupported dialect-accuracy claim. |
| Recovery | Killing API/worker mid-job and restarting leaves no corrupt/partial visible record, lost accepted edit, or duplicate final job output. |
| Backup | A fresh restore reproduces records, evidence navigation, attachment hashes, and accepted task state. |
| Security | Fixed traversal, archive bomb limits, cross-origin/Host, session, CSRF, malicious-content, and path-access tests pass. |
| Offline | After provisioning, core flows pass with external network blocked; document observed connection attempts separately. |
| Accessibility/RTL | Arabic/English keyboard, mixed-direction, copy/paste, and source-navigation flows pass manual checks. |

Initial performance targets on the recorded target device: p95 FTS query response under 500 ms and first timeline page under 1 second on a 100,000-message benchmark. Measure during an active background job as well as idle. Exclude cold startup explicitly and report it separately. Semantic search, model latency, peak RAM/VRAM, disk usage, and transcription real-time factor are measured and published; targets are set after hardware sampling.

No metrics apply universally beyond the tested hardware/data. Report failed cases and sample counts, not only averages.

### Required end-to-end journeys

1. Import ambiguous-date export → resolve locale → inspect multiline/system messages → verify source counts.
2. Import an overlapping newer export → preserve genuine repetitions → show new records and uncertain matches.
3. Search Arabic text → open exact source → create/edit/accept a task → reprocess → verify edit preserved.
4. Transcribe noisy mixed-language audio → correct transcript → seek audio evidence → review derivative updates.
5. Ask answerable, conflicting, and unanswerable questions → inspect citations and coverage limits.
6. Kill a processing worker → restart → recover safely → cancel another job → confirm cleanup.
7. Backup → restore to a fresh profile → verify content and hashes → delete a source → verify index/derivative removal.
8. Start and use the built application on a clean supported Windows environment with internet disabled after provisioning.

## 20. Ordered implementation phases

### Phase 0 — discovery and feasibility

Inspect the actual project and device. Select dependency candidates, create lockfiles, establish supported export fixtures, sample local-model performance if hardware permits, define the threat model, and document the evaluation plan. Ask for real samples only when needed; continue with labeled synthetic data in the meantime.

Deliverables: compatibility matrix, architecture decisions, scope/task list, benchmark method, and unresolved-risk list. Gate: the CPU import/search foundation is feasible; optional model capabilities and unknowns are explicit.

### Phase 1 — trustworthy archive

Implement migrations, source storage, authenticated local API, durable worker, staging/preview, parser, provenance, attachment mapping, conversation/contact identity, overlap handling, and timeline inspection. Add backup/restore skeleton and functional launcher.

Gate: parser/deduplication/security/source-accounting and crash-recovery cases pass. No intelligence layer compensates for unresolved silent data corruption.

### Phase 2 — initial usable release

Implement Arabic/English FTS, filters, manual tasks, conservative suggestions, review workflow, edit protection, CSV/JSON export, deletion, backup/restore, and polished RTL/LTR flows. CSV export must mitigate spreadsheet formula injection in untrusted text.

Gate: Omar can complete import → find evidence → accept/edit task → reimport → restore backup without developer intervention. Demonstrate the initial release on a clean supported environment. Label rule-only limitations.

### Phase 3 — audio

Implement model provisioning, CPU transcription, optional verified GPU path, transcript revisions, playback/timecode navigation, and resource controls.

Gate: representative audio evaluation and interruption/reprocessing tests pass; playback links are verified and measured limitations documented.

### Phase 4 — semantic intelligence

Implement multilingual embeddings, hybrid search, local LLM capability checks, structured contextual extraction, commitments/decisions/waiting items, source-grounded Q&A, and summaries.

Gate: held-out extraction/retrieval/Q&A results meet declared targets; no-model mode still works; private input never leaves the local boundary.

### Phase 5 — remaining media and documents

Implement OCR, structured document extraction, file provenance, bounded video/audio/frame processing, and source viewers.

Gate: supported formats have extraction/evidence tests, resource limits, corruption handling, and clear partial-coverage indicators.

### Phase 6 — specialized workflows and optional extensions

Implement property/research views, useful relationship exploration, project association, then explicitly enabled folder watching and narrowly scoped browser companion.

Gate: specialized fields retain source/uncertainty/history, no unsupported claims appear in drafts, and extension pairing/permissions/import-loop tests pass.

### Phase 7 — full release verification

Complete reproducible packaging, upgrade/migration checks, license notices, clean-machine installation, full acceptance report, user guide, and troubleshooting guide.

Gate: each advertised feature has evidence on the declared target environment. Any incomplete optional capability is clearly disabled/labeled and recorded; it must not be counted as implemented.

Do not assign a firm delivery date before phase 0. Estimate phases based on measured complexity and available development capacity, then update estimates with evidence.

## 21. Final handoff and definition of done

Deliver source code, locked dependencies, migration files, launcher/distribution package, fixture suite, automated test results, benchmark/evaluation report, licenses, setup/user/backup guides, and a concise known-limitations list.

The final report must state:

- Which release scope/phases are complete and which remain.
- Tested device/OS and exact dependencies/models.
- Measured accuracy/performance with corpus size and language breakdown.
- Offline/network behavior actually tested.
- Security/recovery/backup checks actually passed.
- Any untested clean-machine, real-data, GPU, or OS claims.
- The shortest steps for Omar to launch, import, inspect evidence, and restore a backup.

Never declare the full plan complete when only the initial release has been delivered. A partially implemented optional feature is not a working capability. Prefer a smaller demonstrated release with explicit remaining scope over an unsupported completion claim.

## 22. Reference documentation

These primary sources informed the technical choices. Recheck compatibility, current licenses, and exact versions when implementing; this specification deliberately avoids freezing unverified package-version combinations.

- [SQLite FTS5](https://www.sqlite.org/fts5.html): tokenizers, full-text querying, and ranking.
- [SQLite WAL](https://www.sqlite.org/wal.html): local concurrency, single-writer behavior, and WAL lifecycle.
- [Sentence Transformers pretrained models](https://www.sbert.net/docs/sentence_transformer/pretrained_models.html): multilingual embedding candidates including Arabic.
- [faster-whisper requirements and benchmarks](https://github.com/SYSTRAN/faster-whisper#requirements): CPU/GPU dependencies and configuration. Published benchmark results are not benchmarks of Omar's device.
- [OWASP CSRF prevention guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html): authenticated browser requests, origin restrictions, and anti-CSRF controls.

---

Implementation priority: preserve the source, resolve uncertainty visibly, protect user corrections, and prove the workflow before expanding the feature set.

</USER_REQUEST>
<ADDITIONAL_METADATA>
The current local time is: 2026-09-23T22:05:23+03:00.
</ADDITIONAL_METADATA>