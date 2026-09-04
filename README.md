# Telegram Educational Question Processing System

A production-grade, highly reliable, secure, and observable Telegram bot system for extracting, standardizing, validating, and delivering educational multiple-choice questions (question + 4 options) from student-submitted images to teachers and administrators.

---

## 1. System Overview

This system automates the ingestion of photographed educational questions from students, runs security verification and OCR preprocessing, parses the question and exactly four options, renders a high-definition Arabic-first standardized canvas, delivers the result to teacher(s), archives historical submissions into a relational database, and exposes an operational 12-section interactive Admin Panel directly inside Telegram with daily automated scheduled exports (DOCX and Excel).

### Key Highlights
- **First-Class Arabic Typography**: Cursive shaping via `arabic-reshaper`, visual RTL bidirectional reordering via `python-bidi`, bundled Arabic fonts, and dynamic text wrapping with automatic font scaling.
- **Untrusted File Hardening**: Magic byte validation, decompression bomb prevention (`Image.MAX_IMAGE_PIXELS = 25,000,000`), isolated per-job temporary workspaces (`storage/tmp/<job_id>/`), and path traversal prevention.
- **Pluggable OCR & 3-Tier Parsing**: Multi-strategy image enhancement (CLAHE, bilateral filter, adaptive thresholding, Otsu), pluggable OCR providers (Tesseract OCR, Gemini Vision, Mock), and 3-tier parsing (deterministic regex -> structural heuristics -> schema-constrained AI fallback).
- **Strict Quality Gate**: Enforces non-empty question text and exactly 4 non-empty, non-duplicate choices. Never fabricates missing text.
- **Persistent Timezone-Aware Daily Scheduler**: Automatically generates daily DOCX and Excel exports (e.g. at 23:00 Asia/Riyadh), handles `SKIP_EMPTY_DAYS`, and ensures idempotent execution across container restarts.
- **12-Section Telegram Admin Panel**: Dashboard metrics, paginated submission browsing, inspection of original vs. processed images, one-click reprocessing and redelivery, student blocking/unblocking, recipient management, export center, error logs, and system diagnostics.

---

## 2. Architecture & Modular Layout

The project follows a clean, layered (hexagonal) architecture with strict separation of concerns, zero circular dependencies, and typed domain interfaces:

```
bot_telegram_ocr/
├── app/
│   ├── bot/                            # Telegram interface (Aiogram 3.x)
│   │   ├── handlers/
│   │   │   ├── student.py              # /start, image upload, status messages
│   │   │   └── admin.py                # /admin, dashboard, 12 modules, callbacks
│   │   ├── middlewares/
│   │   │   └── rate_limit.py           # Per-user sliding window rate limiting
│   │   ├── keyboards/
│   │   │   └── admin_keyboards.py      # Inline keyboards, pagination, confirmations
│   │   └── bot_instance.py             # Aiogram Bot & Dispatcher setup
│   ├── config/
│   │   └── settings.py                 # Fail-fast Pydantic Settings from .env
│   ├── database/
│   │   ├── base.py                     # SQLAlchemy 2.0 async engine & sessionmaker
│   │   ├── models.py                   # 10 relational tables with indexes and constraints
│   │   └── repositories.py             # Clean async repository patterns
│   ├── domain/
│   │   ├── enums.py                    # ProcessingStatus, DeliveryStatus, AdminAction, etc.
│   │   ├── models.py                   # QuestionPayload, OCRResult, ImageValidationResult
│   │   └── exceptions.py               # Domain errors (OCRError, SecurityError, etc.)
│   ├── services/
│   │   ├── file_service.py             # Workspace isolation, safe pathing, retention cleanup
│   │   ├── image_service.py            # Image validation, security checks, preprocessing
│   │   ├── ocr_service.py              # OCR provider protocol (Tesseract, Gemini, Mock)
│   │   ├── parser_service.py           # Conservative normalizer & 3-tier question parser
│   │   ├── validation_service.py       # Quality gate (4 options, non-empty, coherence)
│   │   ├── rendering_service.py        # Standardized canvas, RTL Arabic, dynamic wrap
│   │   ├── teacher_delivery_service.py # Telegram delivery, status tracking, retries
│   │   ├── export_service.py           # Chronological DOCX & XLSX export builders
│   │   ├── scheduling_service.py       # Persistent daily scheduler with idempotency
│   │   └── admin_service.py            # Dashboard metrics, filtering, student blocking
│   └── main.py                         # Startup bootstrap, DB init, polling, graceful shutdown
├── assets/
│   └── fonts/                          # Bundled TrueType fonts (Arial, Tahoma)
├── storage/                            # Safe local filesystem storage
│   ├── originals/                      # Immutable student uploads (<job_id>.jpg)
│   ├── processed/                      # Rendered standardized templates (<job_id>.png)
│   ├── exports/                        # Generated DOCX and XLSX artifacts
│   └── tmp/                            # Isolated per-job temporary folders
├── tests/
│   ├── conftest.py                     # Pytest fixtures and in-memory test DB
│   ├── unit/                           # Config, parser, normalizer, renderer, validators
│   ├── integration/                    # Repositories, relations, scheduler idempotency
│   ├── e2e/                            # End-to-end full business workflow simulation
│   └── edge_cases/                     # Exhaustive test suite for 35 boundary modes
├── Dockerfile                          # Multi-stage non-root container with Tesseract & Arabic fonts
├── docker-compose.yml                  # Bot + PostgreSQL 16
├── pyproject.toml                      # Modern project specification & tooling config
└── .env.example                        # Template environment variables
```

---

## 3. Business Workflow

```
STUDENT
    ↓
Telegram Bot
    ↓
Receive question image
    ↓
Validate input & Check blocklist / Rate limit
    ↓
Create Job ID & Download image to memory
    ↓
Validate image (Magic bytes, bomb check, dimensions)
    ↓
Preprocess image (Orientation, CLAHE, Denoising, Thresholding)
    ↓
OCR / text extraction (Arabic + English)
    ↓
Conservative text normalization
    ↓
Extract question + exactly 4 options (3-Tier Parser)
    ↓
Validate extracted structure (Quality Gate: PASS / RETRY / FAIL)
    ↓
Render standardized template (Pillow, Arabic RTL, Dynamic wrapping)
    ↓
Validate generated output image
    ↓
Deliver processed result to configured teacher chat
    ↓
Record submission and delivery result in database
    ↓
Notify student of confirmed outcome (✅ or ⚠️)
    ↓
Make record available inside Admin Panel
    ↓
Allow on-demand DOCX / Excel exports
    ↓
Allow scheduled daily exports with multi-recipient delivery
    ↓
Maintain full audit trail
```

---

## 4. Student Workflow
1. Student starts the bot via `/start` and receives instructions in clear Arabic.
2. Student uploads a photo containing a single question and 4 choices.
3. Bot replies with receipt: `📥 تم استلام الصورة.` followed by `⏳ جاري تحليل السؤال وتجهيز القالب...`.
4. If image is unreadable or fails quality gate:
   `❌ لم أتمكن من قراءة السؤال بشكل موثوق. يرجى إرسال صورة أوضح تحتوي على سؤال واحد و4 اختيارات.`
5. If processing succeeds and teacher delivery confirms:
   `✅ تم تجهيز السؤال وإرساله للمعلم بنجاح.`
6. If processing succeeds but delivery encounters a network error:
   `⚠️ تم تجهيز السؤال، لكن تعذر إرساله للمعلم حاليًا.`

---

## 5. Teacher Delivery Workflow
- The teacher receives a formatted message in the designated chat:
  ```
  📚 سؤال جديد

  👤 الطالب: أحمد محمد
  🆔 Student ID: 123456789
  📅 التاريخ: 2026-09-04
  🕐 الوقت: 08:30:15 AM
  🆔 Job: 4f8b2c1a-9e12-4a7b-8c2d-123456789abc
  ```
- Attached is the standardized high-definition processed question image.
- Delivery state is recorded in the database (`DELIVERY_SUCCESS` or `DELIVERY_FAILED`).

---

## 6. Admin Panel Workflow (Inside Telegram)
Administrators (identified strictly by their numeric Telegram User IDs in `ADMIN_USER_IDS`) access the panel via `/admin`.
The panel contains 12 dedicated interactive operational sections:
1. 📊 **الإحصائيات (Dashboard)**: Real-time metrics for today's submissions, success count, failure count, delivery stats, active students, and all-time volume.
2. 📥 **الأسئلة الواردة (Submissions)**: Paginated historical question list (8 per page) with status badges and full question detail drill-down.
3. 🖼️ **الصور والمعالجات (Images)**: Immediate viewing of the original uploaded photo and the rendered template.
4. 📄 **الملفات والتصدير (Exports)**: On-demand generation of DOCX and Excel reports for today, yesterday, or custom date ranges.
5. 📅 **الجدولة (Schedules)**: Inspection, toggling, and management of persistent recurring export schedules.
6. 👥 **الطلاب (Students)**: View student profiles, submission counts, and instant 1-click blocking/unblocking.
7. 📤 **المستلمون (Recipients)**: Manage teacher and archive destination chats.
8. ⚠️ **الأخطاء (Error Center)**: Filter failed submissions, inspect safe error reasons, and trigger 1-click reprocessing.
9. 📦 **الأرشيف (Archive)**: Browse previously generated report files.
10. 🛡️ **سجل الإدارة (Audit Logs)**: Chronological administrative audit logs.
11. 🟢 **حالة النظام (Health)**: Live diagnostic check of the Bot, Database, Storage, and Timezone.
12. ⚙️ **الإعدادات (Settings)**: Operational configuration review.

---

## 7. OCR Strategy
The OCR system is abstracted behind the `OCRProvider` protocol:
- **Tesseract OCR**: Uses local engine with `ara+eng` trained data, configured with PSM 3 (automatic segmentation) and OEM 3 (LSTM).
- **Gemini Vision OCR**: Direct multimodal image-to-text extraction when configured (`OCR_PROVIDER=gemini`).
- **Mock OCR**: Deterministic provider for unit and integration testing without external binaries.
- **Multi-Strategy Preprocessing**: If initial OCR does not yield clean text, the image is re-processed through an alternate pipeline (CLAHE contrast enhancement + sharpening) before retrying.

---

## 8. Parsing Strategy
Uses a 3-tier hybrid question/options extraction architecture:
- **Tier 1 (Deterministic Regex)**: Matches explicit Arabic markers (`أ)`, `ب)`, `ج)`, `د)`), Latin markers (`A)`, `B)`, `C)`, `D)`), and Numeric markers (`1)`, `2)`, `3)`, `4)`). Requires a closing delimiter (e.g. `)`, `.`, `-`, or enclosing brackets `(A)`) to prevent false positives on Arabic words starting with those letters.
- **Tier 2 (Heuristic Structural Segmenter)**: Handles inline multiple options on a single line, multi-line questions, and normalizes OCR artifacts.
- **Tier 3 (AI Structured Fallback)**: Used strictly when deterministic tiers fail and an AI API key is configured. Operates under a rigid Pydantic JSON schema with prompt-injection defense.

---

## 9. Database Design
Relational database modeled with SQLAlchemy 2.0 async and indexed for performance:
- `users`: Telegram User ID, display name, username, role, `is_blocked`, timestamps.
- `submissions`: Job ID (UUID), user FK, `submitted_at_utc`, `business_date`, original/processed file paths, question text, 4 options, `processing_status`, `delivery_status`.
- `processing_attempts`: Submission FK, attempt number, stage, status, error type, safe error message, timestamps.
- `recipients`: Telegram chat ID, name, role, `is_active`, timestamps.
- `exports`: UUID PK, type (MANUAL/SCHEDULED), date range, format (DOCX/XLSX), status, file path, creator.
- `export_recipients`: Export FK, recipient FK, delivery status, message ID, delivered at timestamp.
- `schedules`: Schedule type (DAILY), time of day (e.g. "23:00"), timezone ("Asia/Riyadh"), format, `is_active`.
- `schedule_executions`: Schedule FK, business date, start/completion times, status, export FK. Unique constraint on `(schedule_id, business_date)` prevents duplicate executions.
- `admin_audit_logs`: Admin user ID, action, target type, target ID, safe metadata JSON, timestamp.
- `system_settings`: Key-value store for runtime dynamic configurations.

---

## 10. Storage Architecture
Files are strictly segregated from database metadata and isolated in dedicated directories:
- `storage/originals/<job_id>.jpg`: Immutable original student uploads.
- `storage/processed/<job_id>.png`: Standardized rendered templates.
- `storage/exports/<export_id>.<ext>`: Generated Word/Excel documents.
- `storage/tmp/<job_id>/`: Isolated temporary workspace per job, cleaned up in a `finally` block.

---

## 11. Export System (DOCX & Excel)
- **Daily DOCX**:
  - Strict chronological sorting (`submission_datetime ASC`).
  - Right-to-Left (RTL) document direction for Arabic text (`w:bidi`).
  - Question cards with student name, date, time (in business timezone), and Job ID.
  - Formatted options grid.
  - Embedded processed image with controlled dimensions (4.8 inches) to preserve page structure.
- **Daily Excel (XLSX)**:
  - RTL view enabled.
  - Styled dark blue header row, bold white font, centered.
  - Frozen top header pane (`freeze_panes = 'A2'`).
  - Auto-filter enabled on table headers.
  - Auto-fitted column widths with safety bounds and text wrapping.
  - Alternating row zebra striping.

---

## 12. Persistent Daily Scheduler
- Persistent in database: reads active schedules from the `schedules` table.
- Timezone-aware: evaluates trigger time in configured `TIMEZONE` (e.g., `Asia/Riyadh`).
- Idempotent daily execution: checks `schedule_executions` for `(schedule_id, business_date)` to prevent duplicate runs across application restarts.
- Respects `SKIP_EMPTY_DAYS`: if no submissions exist for a date, marks execution as `SKIPPED_EMPTY` without sending empty files.
- Automatically delivers export file to all active recipients and logs the audit trail.

---

## 13. Security Hardening
- **Untrusted File Hardening**: Magic byte signature verification (`FF D8 FF`, `89 50 4E 47`, `RIFF...WEBP`), PIL `verify()` validation, and strict dimension/size limits.
- **Decompression Bomb Protection**: Hard limit `Image.MAX_IMAGE_PIXELS = 25_000_000`.
- **Path Traversal Protection**: Rejection of any identifier containing path separators or traversal characters (`..`, `/`, `\`). Safe path resolution enforcement.
- **Authorization Security**: Admin privileges are checked against numeric Telegram user IDs. Callbacks and commands verify permissions on every request.
- **Anti-Spam Rate Limiting**: Per-user sliding window limiter (`RATE_LIMIT_REQUESTS` within `RATE_LIMIT_WINDOW_SECONDS`).
- **Prompt Injection Defense**: OCR text passed to AI models is treated strictly as untrusted data under strict Pydantic JSON schemas. No arbitrary code execution or shell access.
- **Zero Information Leakage**: Internal stack traces and database errors are never exposed to students.

---

## 14. Configuration

All configuration is managed via environment variables or a `.env` file:

| Variable | Description | Default |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API Token from @BotFather | **Required** |
| `ADMIN_USER_IDS` | Comma-separated numeric Telegram User IDs of Admins | **Required** |
| `TEACHER_CHAT_ID` | Primary Teacher Telegram Chat ID | **Required** |
| `TIMEZONE` | Business timezone | `Asia/Riyadh` |
| `DATABASE_URL` | SQLAlchemy connection URL (PostgreSQL / SQLite) | `sqlite+aiosqlite:///storage/app.db` |
| `STORAGE_PATH` | Base file storage directory | `./storage` |
| `OCR_PROVIDER` | OCR provider (`tesseract`, `gemini`, `mock`) | `tesseract` |
| `MAX_FILE_SIZE_MB` | Maximum allowed upload size in MB | `20` |
| `MAX_IMAGE_WIDTH` | Maximum image width in pixels | `6000` |
| `MAX_IMAGE_HEIGHT` | Maximum image height in pixels | `6000` |
| `IMAGE_RETENTION_DAYS` | Days to retain original and processed images | `30` |
| `EXPORT_RETENTION_DAYS` | Days to retain generated export files | `30` |
| `DEFAULT_EXPORT_TIME` | Scheduled export time (HH:MM) | `23:00` |
| `SKIP_EMPTY_DAYS` | Skip export delivery on empty days | `true` |
| `RATE_LIMIT_REQUESTS` | Max requests per rate limit window | `5` |
| `RATE_LIMIT_WINDOW_SECONDS` | Rate limit window in seconds | `60` |

---

## 15. Installation & Local Development

### Prerequisites
- Python 3.12+ (tested on Python 3.13)
- Tesseract OCR (with Arabic `tesseract-ocr-ara` and English `tesseract-ocr-eng` packages)

### Setup Steps
```bash
# 1. Clone repository and navigate to directory
cd d:/All_Projects_Organized/projects/telegram_bots/bot_telegram_ocr

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install --upgrade pip
pip install -e .

# 4. Configure environment
cp .env.example .env
# Edit .env with your TELEGRAM_BOT_TOKEN, ADMIN_USER_IDS, and TEACHER_CHAT_ID

# 5. Run the bot
python -m app.main
```

---

## 16. Testing & Quality Verification

Run the comprehensive test suite:
```bash
# Run all unit, integration, and E2E tests
pytest -v

# Run linter and code style checks
ruff check .
ruff format --check .
```

---

## 17. Docker Deployment

### Run with Docker Compose (Recommended for Production)
The included `docker-compose.yml` orchestrates PostgreSQL 16 and the Bot service with automated health checks:

```bash
# 1. Ensure .env is populated with your production secrets
cp .env.example .env

# 2. Build and start containers
docker compose up -d --build

# 3. View logs
docker compose logs -f bot
```

---

## 18. Troubleshooting

- **Bot does not respond to /admin**: Verify that your Telegram User ID is in `ADMIN_USER_IDS`. Send a message to `@userinfobot` on Telegram to check your numeric ID.
- **Tesseract not found**: Ensure Tesseract is installed on your host system or deploy via Docker where Tesseract is pre-installed.
- **Images fail with "أبعاد الصورة صغيرة جدًا"**: The image sent is smaller than 30x30 pixels. Students must submit clear questions.

---

## 19. Retention Policy
The `FileService.cleanup_expired_files()` background task enforces:
- Original uploads and processed images older than `IMAGE_RETENTION_DAYS` (default 30 days) are safely purged from disk.
- Generated export files older than `EXPORT_RETENTION_DAYS` (default 30 days) are safely deleted.
- Database records remain as the canonical audit history.

---

## 20. Scalability Considerations
- **Stateless Handlers**: The Telegram bot handlers are stateless. State is preserved in PostgreSQL.
- **Async Concurrency**: All database operations and I/O tasks are non-blocking via `asyncio`, `aiosqlite`, and `asyncpg`.
- **Database Indexing**: Submissions are indexed on `job_id`, `business_date`, `processing_status`, `delivery_status`, and `user_id`.
