"""Custom domain exceptions."""


class DomainError(Exception):
    """Base exception for all domain errors."""

    def __init__(self, message: str, safe_message: str | None = None):
        super().__init__(message)
        self.safe_message = safe_message or "حدث خطأ غير متوقع أثناء معالجة الطلب."


class SecurityError(DomainError):
    """Raised when an operation violates security constraints."""

    pass


class DecompressionBombError(SecurityError):
    """Raised when an uploaded image exceeds safe pixel limits."""

    pass


class InvalidImageError(DomainError):
    """Raised when an uploaded file is not a valid or decodable image."""

    pass


class OCRError(DomainError):
    """Raised when an OCR engine fails to extract text."""

    pass


class OCRTimeoutError(OCRError):
    """Raised when an OCR extraction operation times out."""

    pass


class ValidationError(DomainError):
    """Raised when question structure or payload fails validation."""

    pass


class QualityGateError(ValidationError):
    """Raised when an extracted question fails the quality gate."""

    pass


class RenderingError(DomainError):
    """Raised when template canvas rendering fails."""

    pass


class DeliveryError(DomainError):
    """Raised when Telegram delivery to teacher or recipient fails."""

    pass


class ExportError(DomainError):
    """Raised when building DOCX or XLSX export files fails."""

    pass


class UnauthorizedError(DomainError):
    """Raised when an unauthorized user attempts an admin action."""

    pass


class RateLimitExceededError(DomainError):
    """Raised when a user sends updates faster than the allowed rate."""

    pass
