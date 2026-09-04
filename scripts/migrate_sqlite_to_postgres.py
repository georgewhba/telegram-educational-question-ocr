"""SQLite to PostgreSQL Data Migration Script.

Transfers all records from the legacy SQLite database to PostgreSQL in proper
foreign-key dependency order, handles data type conversions (timestamps, booleans, JSON),
resets PostgreSQL sequences to prevent ID collisions, and validates 1:1 row counts.

Usage:
    python scripts/migrate_sqlite_to_postgres.py --dry-run
    python scripts/migrate_sqlite_to_postgres.py --sqlite-path ./storage/app.db
"""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Import models and settings from the application
from app.config.settings import get_settings

settings = get_settings()
from app.database.models import (
    AdminAuditLog,
    Export,
    ExportRecipient,
    ProcessingAttempt,
    Recipient,
    Schedule,
    ScheduleExecution,
    Submission,
    SystemSetting,
    User,
)
from app.domain.enums import (
    DeliveryStatus,
    ExportFormat,
    ExportStatus,
    ProcessingStatus,
    ScheduleType,
    UserRole,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("migration")


# Table dependency ordering: Parents before children
TABLE_MIGRATION_ORDER = [
    ("users", User),
    ("recipients", Recipient),
    ("schedules", Schedule),
    ("system_settings", SystemSetting),
    ("submissions", Submission),
    ("processing_attempts", ProcessingAttempt),
    ("exports", Export),
    ("export_recipients", ExportRecipient),
    ("schedule_executions", ScheduleExecution),
    ("admin_audit_logs", AdminAuditLog),
]


def parse_datetime(val: Any) -> datetime | None:
    """Parse SQLite timestamp string or return datetime with UTC timezone."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    if isinstance(val, str):
        # Handle ISO or standard SQL string format
        clean_str = val.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(clean_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(clean_str, fmt)
                    return dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
    raise ValueError(f"Unable to parse datetime: {val!r}")


def parse_date(val: Any) -> date | None:
    """Parse SQLite date string or return date object."""
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        clean_str = val.strip().split("T")[0].split(" ")[0]
        return date.fromisoformat(clean_str)
    raise ValueError(f"Unable to parse date: {val!r}")


def parse_json(val: Any) -> dict[str, Any]:
    """Parse SQLite JSON string to Python dict."""
    if val is None:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        if not val.strip():
            return {}
        try:
            parsed = json.loads(val)
            if isinstance(parsed, dict):
                return parsed
            return {"data": parsed}
        except json.JSONDecodeError:
            return {"raw": val}
    return {}


def parse_bool(val: Any) -> bool:
    """Convert SQLite integer 0/1 or string/bool to boolean."""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes", "t")
    return bool(val)


def transform_user_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "telegram_user_id": int(row["telegram_user_id"]),
        "username": row["username"],
        "display_name": row["display_name"],
        "role": UserRole(row["role"]) if row["role"] else UserRole.STUDENT,
        "is_blocked": parse_bool(row["is_blocked"]),
        "created_at": parse_datetime(row["created_at"]),
        "last_seen_at": parse_datetime(row["last_seen_at"]),
    }


def transform_recipient_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "telegram_chat_id": int(row["telegram_chat_id"]),
        "name": row["name"],
        "role": row["role"],
        "is_active": parse_bool(row["is_active"]),
        "created_at": parse_datetime(row["created_at"]),
        "updated_at": parse_datetime(row["updated_at"]),
    }


def transform_schedule_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "schedule_type": ScheduleType(row["schedule_type"]) if row["schedule_type"] else ScheduleType.DAILY,
        "time_of_day": row["time_of_day"],
        "timezone": row["timezone"],
        "format": ExportFormat(row["format"]) if row["format"] else ExportFormat.DOCX,
        "content_config": parse_json(row["content_config"]),
        "is_active": parse_bool(row["is_active"]),
        "created_by": int(row["created_by"]) if row["created_by"] is not None else None,
        "created_at": parse_datetime(row["created_at"]),
        "updated_at": parse_datetime(row["updated_at"]),
    }


def transform_system_setting_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "key": row["key"],
        "value": row["value"],
        "description": row["description"],
        "updated_at": parse_datetime(row["updated_at"]),
    }


def transform_submission_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "job_id": row["job_id"],
        "user_id": int(row["user_id"]),
        "submitted_at_utc": parse_datetime(row["submitted_at_utc"]),
        "business_date": parse_date(row["business_date"]),
        "original_file_path": row["original_file_path"],
        "processed_file_path": row["processed_file_path"],
        "question_text": row["question_text"],
        "option_a": row["option_a"],
        "option_b": row["option_b"],
        "option_c": row["option_c"],
        "option_d": row["option_d"],
        "processing_status": ProcessingStatus(row["processing_status"])
        if row["processing_status"]
        else ProcessingStatus.RECEIVED,
        "delivery_status": DeliveryStatus(row["delivery_status"])
        if row["delivery_status"]
        else DeliveryStatus.PENDING,
        "created_at": parse_datetime(row["created_at"]),
        "updated_at": parse_datetime(row["updated_at"]),
    }


def transform_processing_attempt_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "submission_id": int(row["submission_id"]),
        "attempt_number": int(row["attempt_number"]),
        "stage": row["stage"],
        "status": row["status"],
        "error_type": row["error_type"],
        "safe_error_message": row["safe_error_message"],
        "started_at": parse_datetime(row["started_at"]),
        "completed_at": parse_datetime(row["completed_at"]) if row["completed_at"] else None,
    }


def transform_export_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "export_type": row["export_type"],
        "date_from": parse_date(row["date_from"]),
        "date_to": parse_date(row["date_to"]),
        "format": ExportFormat(row["format"]) if row["format"] else ExportFormat.DOCX,
        "content_config": parse_json(row["content_config"]),
        "status": ExportStatus(row["status"]) if row["status"] else ExportStatus.PENDING,
        "file_path": row["file_path"],
        "created_by": int(row["created_by"]) if row["created_by"] is not None else None,
        "created_at": parse_datetime(row["created_at"]),
        "completed_at": parse_datetime(row["completed_at"]) if row["completed_at"] else None,
    }


def transform_export_recipient_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "export_id": str(row["export_id"]),
        "recipient_id": int(row["recipient_id"]),
        "delivery_status": DeliveryStatus(row["delivery_status"])
        if row["delivery_status"]
        else DeliveryStatus.PENDING,
        "telegram_message_id": int(row["telegram_message_id"]) if row["telegram_message_id"] is not None else None,
        "delivered_at": parse_datetime(row["delivered_at"]) if row["delivered_at"] else None,
        "error_type": row["error_type"],
    }


def transform_schedule_execution_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "schedule_id": int(row["schedule_id"]),
        "business_date": parse_date(row["business_date"]),
        "started_at": parse_datetime(row["started_at"]),
        "completed_at": parse_datetime(row["completed_at"]) if row["completed_at"] else None,
        "status": row["status"],
        "export_id": str(row["export_id"]) if row["export_id"] is not None else None,
    }


def transform_admin_audit_log_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "admin_user_id": int(row["admin_user_id"]),
        "action": row["action"],
        "target_type": row["target_type"],
        "target_id": str(row["target_id"]) if row["target_id"] is not None else None,
        "metadata_safe": parse_json(row["metadata_safe"]),
        "created_at": parse_datetime(row["created_at"]),
    }


ROW_TRANSFORMERS = {
    "users": transform_user_row,
    "recipients": transform_recipient_row,
    "schedules": transform_schedule_row,
    "system_settings": transform_system_setting_row,
    "submissions": transform_submission_row,
    "processing_attempts": transform_processing_attempt_row,
    "exports": transform_export_row,
    "export_recipients": transform_export_recipient_row,
    "schedule_executions": transform_schedule_execution_row,
    "admin_audit_logs": transform_admin_audit_log_row,
}


async def reset_postgres_sequences(session: AsyncSession) -> None:
    """Reset all SERIAL/IDENTITY sequences in PostgreSQL to max(id) + 1."""
    tables_with_serial_id = [
        "users",
        "recipients",
        "schedules",
        "submissions",
        "processing_attempts",
        "export_recipients",
        "schedule_executions",
        "admin_audit_logs",
    ]
    for table_name in tables_with_serial_id:
        sql = text(
            f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table_name}), 1), "
            f"(SELECT MAX(id) IS NOT NULL FROM {table_name}));"
        )
        try:
            await session.execute(sql)
            logger.info("Reset sequence for table: %s", table_name)
        except Exception as exc:
            logger.warning("Could not reset sequence for table %s: %s", table_name, exc)


async def run_migration(
    sqlite_path: Path,
    database_url: str,
    dry_run: bool = False,
    batch_size: int = 500,
    clean_target: bool = False,
) -> bool:
    if not sqlite_path.exists():
        logger.error("SQLite database file not found at: %s", sqlite_path)
        return False

    logger.info("Starting migration...")
    logger.info("Source SQLite: %s", sqlite_path)
    logger.info("Target Postgres: %s", database_url.split("@")[-1] if "@" in database_url else database_url)
    logger.info("Mode: %s", "DRY-RUN (No writes)" if dry_run else "LIVE MIGRATION")

    # Connect to SQLite
    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()

    # Create Async Engine for PostgreSQL
    engine = create_async_engine(database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    source_counts: dict[str, int] = {}
    dest_counts_before: dict[str, int] = {}
    dest_counts_after: dict[str, int] = {}
    validation_status: dict[str, str] = {}

    try:
        # Check source counts
        for table_name, _ in TABLE_MIGRATION_ORDER:
            try:
                sqlite_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                source_counts[table_name] = sqlite_cursor.fetchone()[0]
            except sqlite3.OperationalError:
                source_counts[table_name] = 0

        # Check existing destination counts
        async with async_session() as session:
            for table_name, model in TABLE_MIGRATION_ORDER:
                res = await session.execute(select(model))
                dest_counts_before[table_name] = len(res.scalars().all())

        if dry_run:
            logger.info("=== DRY RUN AUDIT & VALIDATION REPORT ===")
            print("\n" + "=" * 60)
            print(f"{'Table':<25} | {'SQLite Count':<12} | {'Postgres Before':<15}")
            print("-" * 60)
            transform_errors: list[str] = []
            for table_name, _ in TABLE_MIGRATION_ORDER:
                print(f"{table_name:<25} | {source_counts[table_name]:<12} | {dest_counts_before[table_name]:<15}")
                if source_counts[table_name] > 0:
                    transformer = ROW_TRANSFORMERS[table_name]
                    sqlite_cursor.execute(f"SELECT * FROM {table_name}")
                    rows = sqlite_cursor.fetchall()
                    for idx, r in enumerate(rows):
                        try:
                            transformer(r)
                        except Exception as e:
                            transform_errors.append(f"Table {table_name}, row {idx}: {e}")
            print("=" * 60 + "\n")
            if transform_errors:
                for err in transform_errors:
                    logger.error("Dry run validation error: %s", err)
                return False
            logger.info("Dry run complete: All %d total records validated successfully. No records were modified.", sum(source_counts.values()))
            return True

        # Perform actual migration
        async with async_session() as session:
            if clean_target:
                logger.warning("Cleaning existing target tables in reverse dependency order...")
                for table_name, _ in reversed(TABLE_MIGRATION_ORDER):
                    await session.execute(text(f"TRUNCATE TABLE {table_name} CASCADE;"))
                await session.commit()
                logger.info("Target tables cleaned.")

            for table_name, model in TABLE_MIGRATION_ORDER:
                count = source_counts[table_name]
                if count == 0:
                    logger.info("Table %s is empty in SQLite. Skipping.", table_name)
                    continue

                logger.info("Migrating table %s (%d records)...", table_name, count)
                transformer = ROW_TRANSFORMERS[table_name]

                sqlite_cursor.execute(f"SELECT * FROM {table_name}")
                rows = sqlite_cursor.fetchall()

                # Process in batches
                for i in range(0, len(rows), batch_size):
                    batch_rows = rows[i : i + batch_size]
                    transformed_data = [transformer(r) for r in batch_rows]
                    # Insert using table construct
                    await session.execute(model.__table__.insert(), transformed_data)

                await session.flush()
                logger.info("Migrated %d rows into %s.", len(rows), table_name)

            # Reset PostgreSQL sequences
            await reset_postgres_sequences(session)
            await session.commit()
            logger.info("Database transaction successfully committed.")

        # Post-migration validation
        async with async_session() as session:
            for table_name, model in TABLE_MIGRATION_ORDER:
                res = await session.execute(select(model))
                dest_counts_after[table_name] = len(res.scalars().all())

        # Generate validation report
        all_passed = True
        print("\n" + "=" * 70)
        print("MIGRATION DATA VALIDATION REPORT")
        print("=" * 70)
        print(f"{'Table':<25} | {'SQLite':<8} | {'Postgres':<10} | {'Diff':<6} | {'Status':<8}")
        print("-" * 70)

        for table_name, _ in TABLE_MIGRATION_ORDER:
            s_cnt = source_counts[table_name]
            d_cnt = dest_counts_after[table_name]
            diff = d_cnt - s_cnt
            status = "PASS" if diff == 0 else "FAIL"
            if diff != 0:
                all_passed = False
            validation_status[table_name] = status
            print(f"{table_name:<25} | {s_cnt:<8} | {d_cnt:<10} | {diff:<6} | {status:<8}")

        print("=" * 70 + "\n")

        if all_passed:
            logger.info("Validation SUCCESSFUL: All table counts match 1:1.")
        else:
            logger.error("Validation FAILED: One or more table counts do not match!")

        return all_passed

    except Exception as exc:
        logger.exception("Migration failed with error: %s", exc)
        return False
    finally:
        sqlite_conn.close()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate data from SQLite to PostgreSQL.")
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=Path("storage/app.db"),
        help="Path to SQLite database file",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=settings.DATABASE_URL,
        help="Target PostgreSQL connection URL",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate migration and audit counts without modifying database",
    )
    parser.add_argument(
        "--clean-target",
        action="store_true",
        help="Truncate target tables before migration (use with caution)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for inserts",
    )

    args = parser.parse_args()

    success = asyncio.run(
        run_migration(
            sqlite_path=args.sqlite_path,
            database_url=args.database_url,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            clean_target=args.clean_target,
        )
    )

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
