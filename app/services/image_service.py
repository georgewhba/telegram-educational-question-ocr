"""Image validation and preprocessing service."""

import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from app.config.settings import Settings, get_settings
from app.domain.exceptions import DecompressionBombError
from app.domain.models import ImageValidationResult

# Hard limit on uncompressed pixels to defend against decompression bombs
Image.MAX_IMAGE_PIXELS = 25_000_000

# Recognized binary magic bytes
MAGIC_NUMBERS = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"RIFF": "image/webp",  # WebP files begin with RIFF and contain WEBP
}


class ImageService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def validate_image_bytes(self, data: bytes) -> ImageValidationResult:
        """Validate raw bytes of an uploaded image before writing or processing."""
        # 1. Size check
        size = len(data)
        if size == 0:
            return ImageValidationResult(is_valid=False, error_message="الملف فارغ.")
        if size > self.settings.max_file_size_bytes:
            return ImageValidationResult(
                is_valid=False,
                file_size_bytes=size,
                error_message=f"حجم الملف ({size // (1024 * 1024)}MB) يتجاوز الحد المسموح ({self.settings.MAX_FILE_SIZE_MB}MB).",
            )

        # 2. Magic byte check
        mime_type = self._detect_mime(data)
        if not mime_type:
            return ImageValidationResult(
                is_valid=False,
                file_size_bytes=size,
                error_message="نوع الملف غير مدعوم أو غير صالح. يرجى إرسال صورة بصيغة JPG أو PNG.",
            )

        # 3. PIL verify & Decompression Bomb protection
        try:
            bio = io.BytesIO(data)
            with Image.open(bio) as img:
                # verify checks header and structural integrity
                img.verify()

            # Re-open to read dimensions and mode
            bio.seek(0)
            with Image.open(bio) as img:
                w, h = img.size
                total_pixels = w * h

                if total_pixels > (self.settings.MAX_IMAGE_WIDTH * self.settings.MAX_IMAGE_HEIGHT):
                    raise DecompressionBombError(f"أبعاد الصورة ({w}x{h}) تتجاوز الحد الآمن المسموح به للملفات.")

                if w < 30 or h < 30:
                    return ImageValidationResult(
                        is_valid=False,
                        width=w,
                        height=h,
                        mime_type=mime_type,
                        file_size_bytes=size,
                        error_message="أبعاد الصورة صغيرة جدًا ولا يمكن قراءتها بوضوح.",
                    )

                if w > self.settings.MAX_IMAGE_WIDTH or h > self.settings.MAX_IMAGE_HEIGHT:
                    return ImageValidationResult(
                        is_valid=False,
                        width=w,
                        height=h,
                        mime_type=mime_type,
                        file_size_bytes=size,
                        error_message=f"أبعاد الصورة ({w}x{h}) تتجاوز الحد الأقصى المسموح ({self.settings.MAX_IMAGE_WIDTH}x{self.settings.MAX_IMAGE_HEIGHT}).",
                    )

                return ImageValidationResult(
                    is_valid=True,
                    width=w,
                    height=h,
                    mime_type=mime_type,
                    file_size_bytes=size,
                )

        except DecompressionBombError as e:
            return ImageValidationResult(
                is_valid=False,
                file_size_bytes=size,
                error_message=str(e),
            )
        except Exception as e:
            return ImageValidationResult(
                is_valid=False,
                file_size_bytes=size,
                error_message=f"الصورة تالفة أو غير قابلة للقراءة: {str(e)}",
            )

    def validate_image_file(self, file_path: Path) -> ImageValidationResult:
        """Validate an image file from disk."""
        if not file_path.exists():
            return ImageValidationResult(is_valid=False, error_message="ملف الصورة غير موجود.")
        data = file_path.read_bytes()
        return self.validate_image_bytes(data)

    def preprocess_image(
        self,
        image_path: Path,
        output_path: Path,
        strategy: str = "standard",
    ) -> Path:
        """Preprocess an image for OCR using configurable strategies."""
        # Step 1: Open with PIL and handle EXIF orientation
        with Image.open(image_path) as pil_img:
            pil_img = ImageOps.exif_transpose(pil_img)
            # Ensure RGB
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")

            # Scale down if excessively large (e.g. phone camera 4000x3000 -> max 2400)
            max_dim = 2400
            w, h = pil_img.size
            if max(w, h) > max_dim:
                scale = max_dim / max(w, h)
                new_w, new_h = int(w * scale), int(h * scale)
                pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            # Convert to numpy array for OpenCV
            img_np = np.array(pil_img)
            # RGB to BGR for cv2
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

        # Step 2: Apply strategy
        processed_bgr = self._apply_strategy(img_bgr, strategy)

        # Step 3: Save to output path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output_path), processed_bgr)
        return output_path

    def _apply_strategy(self, img_bgr: np.ndarray, strategy: str) -> np.ndarray:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

        if strategy == "raw_grayscale":
            return gray

        elif strategy == "enhanced_contrast":
            # CLAHE on grayscale
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            # Mild unsharp mask
            gaussian = cv2.GaussianBlur(enhanced, (0, 0), 2.0)
            sharpened = cv2.addWeighted(enhanced, 1.5, gaussian, -0.5, 0)
            return sharpened

        elif strategy == "adaptive_threshold":
            # Bilateral filter for edge-preserving smoothing
            denoised = cv2.bilateralFilter(gray, 9, 75, 75)
            # Adaptive Gaussian thresholding
            thresh = cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 10)
            return thresh

        else:  # "standard"
            # Denoise
            denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
            # CLAHE
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(denoised)
            # Otsu binarization
            _, thresh = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return thresh

    def _detect_mime(self, data: bytes) -> str | None:
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
            return "image/webp"
        return None
