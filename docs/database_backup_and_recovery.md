# Production Database Operations: Backup, Restore, Cutover & Rollback Strategy

This document provides the standard operating procedures (SOP) for PostgreSQL operations, daily automated backups, disaster recovery, zero-data-loss cutover, and emergency rollback for the Telegram Educational Question OCR system.

---

## 1. PostgreSQL Production Backup Strategy

### 1.1 Backup Formats & Tools
PostgreSQL backups MUST be generated using the native `pg_dump` utility. We use the compressed custom format (`-Fc`), which supports multi-threaded parallel restores, compression, and selective table restoration.

#### Full Database Backup Command
```bash
# Set credentials via environment (never hardcode in command lines)
export PGPASSWORD="your_secure_password"

# Logical backup in custom compressed format
pg_dump -h localhost -p 5433 -U postgres -F c -b -v -f "/backups/postgresql/ocr_bot_$(date +%Y%m%d_%H%M%S).dump" ocr_bot

# Unset credentials after execution
unset PGPASSWORD
```

#### Plain SQL Text Backup (Schema Only / Audit)
```bash
pg_dump -h localhost -p 5433 -U postgres --schema-only -f "/backups/postgresql/ocr_bot_schema_$(date +%Y%m%d).sql" ocr_bot
```

### 1.2 Automated Daily Backup Script (Linux / Cron)
Create `/usr/local/bin/backup_postgres.sh`:

```bash
#!/bin/bash
set -euo pipefail

BACKUP_DIR="/var/backups/ocr_bot"
DATE_TAG=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/ocr_bot_${DATE_TAG}.dump"
LOG_FILE="/var/log/ocr_bot_backup.log"

mkdir -p "${BACKUP_DIR}"

echo "[$(date)] Starting PostgreSQL backup..." >> "${LOG_FILE}"

export PGPASSWORD="${POSTGRES_PASSWORD}"
pg_dump -h "${POSTGRES_HOST:-localhost}" \
        -p "${POSTGRES_PORT:-5432}" \
        -U "${POSTGRES_USER:-postgres}" \
        -F c -b -v \
        -f "${BACKUP_FILE}" \
        "${POSTGRES_DB:-ocr_bot}" >> "${LOG_FILE}" 2>&1

unset PGPASSWORD

echo "[$(date)] Backup completed: ${BACKUP_FILE} (Size: $(du -h "${BACKUP_FILE}" | cut -f1))" >> "${LOG_FILE}"

# Retention cleanup: Keep daily backups for 30 days
find "${BACKUP_DIR}" -name "ocr_bot_*.dump" -mtime +30 -delete
echo "[$(date)] Expired backups purged." >> "${LOG_FILE}"
```

### 1.3 Retention Policy (Grandfather-Father-Son)
| Backup Type | Frequency | Retention Period | Storage Target |
| :--- | :--- | :--- | :--- |
| **Hourly Diff / WAL** | Continuous / 1hr | 7 days | Primary NVMe + Replica |
| **Daily Dump** | Nightly at 02:00 | 30 days | Encrypted Object Storage (S3 / GCS) |
| **Weekly Snapshot** | Sundays | 12 weeks | Off-site Cold Storage |
| **Monthly Archive** | 1st of month | 1 year | Immutable Glacier / Archive Vault |

---

## 2. Restoration & Disaster Recovery Procedure

### 2.1 Restoring to a Fresh Database
```bash
# 1. Create fresh database target
export PGPASSWORD="your_secure_password"
createdb -h localhost -p 5433 -U postgres ocr_bot_restored

# 2. Restore using pg_restore with parallel workers
pg_restore -h localhost -p 5433 -U postgres -d ocr_bot_restored -v -j 4 "/backups/postgresql/ocr_bot_YYYYMMDD_HHMMSS.dump"

# 3. Verify row counts and integrity
psql -h localhost -p 5433 -U postgres -d ocr_bot_restored -c "SELECT 'users', count(*) FROM users UNION ALL SELECT 'submissions', count(*) FROM submissions;"
```

### 2.2 Point-in-Time Recovery (PITR)
For continuous archiving, enable Write-Ahead Logging (WAL) in `postgresql.conf`:
```ini
wal_level = replica
archive_mode = on
archive_command = 'test ! -f /mnt/wal_archive/%f && cp %p /mnt/wal_archive/%f'
```
To recover up to a specific timestamp `recovery_target_time = '2026-09-04 14:00:00+00'`, create `recovery.signal` and start PostgreSQL.

---

## 3. Production Cutover Protocol (SQLite -> PostgreSQL)

Follow this 11-step protocol when switching production traffic from SQLite to PostgreSQL:

1. **Maintenance Window Announcement**: Notify users / schedule maintenance mode.
2. **Stop Ingress Traffic**: Stop the Telegram bot polling process to prevent concurrent writes during cutover:
   ```bash
   # Systemd service or docker container stop
   systemctl stop telegram-ocr-bot
   ```
3. **Backup Source SQLite Database**:
   ```bash
   cp ./storage/app.db ./storage/app.db.bak.$(date +%Y%m%d_%H%M%S)
   chmod 400 ./storage/app.db.bak.* # Mark read-only
   ```
4. **Apply Alembic Migrations on PostgreSQL**:
   ```bash
   alembic upgrade head
   ```
5. **Run Live Data Migration Utility**:
   ```bash
   python scripts/migrate_sqlite_to_postgres.py --sqlite-path ./storage/app.db
   ```
6. **Validate Row Counts and Sequences**:
   Check the output validation table; ensure all 10 tables report `PASS` and diff is 0.
7. **Run Database Integration & Concurrency Test Suite**:
   ```bash
   pytest tests/integration/test_postgres_integration.py -v
   ```
8. **Point Application Configuration to PostgreSQL**:
   Update `.env`:
   ```env
   DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/ocr_bot
   ```
9. **Start Application**:
   ```bash
   systemctl start telegram-ocr-bot
   ```
10. **Perform Live Smoke Tests**:
    - Submit a test question image via Telegram.
    - Check admin dashboard status via `/admin` -> `🟢 حالة النظام`.
    - Generate a sample DOCX export.
11. **Monitor System Logs**:
    ```bash
    journalctl -u telegram-ocr-bot -f
    ```

---

## 4. Emergency Rollback Strategy

If an unrecoverable issue is detected during or immediately after cutover:

1. **Stop Application**:
   ```bash
   systemctl stop telegram-ocr-bot
   ```
2. **Revert Configuration**:
   Change `.env` back to the SQLite connection:
   ```env
   DATABASE_URL=sqlite+aiosqlite:///./storage/app.db
   ```
3. **Restore Pre-Migration SQLite Snapshot (if modified)**:
   ```bash
   cp ./storage/app.db.bak.<TIMESTAMP> ./storage/app.db
   ```
4. **Restart Application on SQLite**:
   ```bash
   systemctl start telegram-ocr-bot
   ```
5. **Verify SQLite Functionality**:
   Run sanity check on `/admin` and confirm bot handles messages normally.
6. **Post-Incident Analysis**:
   Investigate PostgreSQL logs (`/var/log/postgresql/`) without impacting user availability.
