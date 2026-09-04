"""File storage service for isolated temporary workspaces, safe paths, and retention management."""

import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config.settings import Settings, get_settings
from app.domain.exceptions import SecurityError


class FileService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def generate_job_id(self) -> str:
        """Generate a random UUID4 job ID."""
        return str(uuid.uuid4())

    def generate_export_id(self) -> str:
        """Generate a random UUID4 export ID."""
        return str(uuid.uuid4())

    def get_isolated_tmp_dir(self, job_id: str) -> Path:
        """Create and return an isolated temporary directory for a specific job."""
        self._validate_identifier(job_id)
        path = self.settings.tmp_dir / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cleanup_tmp_dir(self, job_id: str) -> None:
        """Safely remove the temporary directory for a specific job."""
        try:
            self._validate_identifier(job_id)
            path = self.settings.tmp_dir / job_id
            if path.exists() and path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass

    def get_original_path(self, job_id: str, extension: str = "jpg") -> Path:
        """Get the safe path for an original uploaded image."""
        self._validate_identifier(job_id)
        ext = extension.lstrip(".").lower()
        if ext not in {"jpg", "jpeg", "png", "webp"}:
            ext = "jpg"
        return self.settings.originals_dir / f"{job_id}.{ext}"

    def get_processed_path(self, job_id: str) -> Path:
        """Get the safe path for a rendered processed image."""
        self._validate_identifier(job_id)
        return self.settings.processed_dir / f"{job_id}.png"

    def get_export_path(self, export_id: str, extension: str) -> Path:
        """Get the safe path for an export file."""
        self._validate_identifier(export_id)
        ext = extension.lstrip(".").lower()
        return self.settings.exports_dir / f"{export_id}.{ext}"

    def safe_resolve(self, target_path: Path | str, base_dir: Path | None = None) -> Path:
        """Ensure the target path resolves strictly inside the allowed base storage directory."""
        base = (base_dir or self.settings.STORAGE_PATH).resolve()
        resolved = Path(target_path).resolve()
        try:
            resolved.relative_to(base)
        except ValueError:
            raise SecurityError(f"Path traversal detected: {target_path} is outside {base}")
        return resolved

    def cleanup_expired_files(self) -> dict[str, int]:
        """Enforce retention policies on original images, processed images, and exports."""
        now = datetime.now(timezone.utc)
        image_cutoff = now - timedelta(days=self.settings.IMAGE_RETENTION_DAYS)
        export_cutoff = now - timedelta(days=self.settings.EXPORT_RETENTION_DAYS)

        deleted_originals = self._clean_dir_older_than(self.settings.originals_dir, image_cutoff)
        deleted_processed = self._clean_dir_older_than(self.settings.processed_dir, image_cutoff)
        deleted_exports = self._clean_dir_older_than(self.settings.exports_dir, export_cutoff)

        return {
            "originals_cleaned": deleted_originals,
            "processed_cleaned": deleted_processed,
            "exports_cleaned": deleted_exports,
        }

    def _clean_dir_older_than(self, directory: Path, cutoff: datetime) -> int:
        count = 0
        if not directory.exists():
            return count
        for file in directory.iterdir():
            if file.is_file():
                try:
                    mtime = datetime.fromtimestamp(file.stat().st_mtime, tz=timezone.utc)
                    if mtime < cutoff:
                        file.unlink()
                        count += 1
                except Exception:
                    continue
        return count

    def _validate_identifier(self, identifier: str) -> None:
        """Ensure an identifier only contains alphanumeric characters or dashes/underscores."""
        if not identifier or any(c in identifier for c in r"/\..:?*|\"<>"):
            raise SecurityError(f"Invalid identifier format: {identifier}")
