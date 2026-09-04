"""Pluggable OCR providers and multi-strategy extraction pipeline."""

import asyncio
import time
from pathlib import Path
from typing import Protocol

import pytesseract
from PIL import Image

from app.config.settings import Settings, get_settings
from app.domain.exceptions import OCRError, OCRTimeoutError
from app.domain.models import OCRResult, QuestionPayload


class OCRProvider(Protocol):
    """Protocol defining the interface for all OCR extraction providers."""

    async def extract_text(self, image_path: Path, language: str = "ara+eng") -> OCRResult: ...


class TesseractOCRProvider:
    """OCR implementation using local Tesseract engine."""

    def __init__(self, tesseract_cmd: str | None = None):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    async def extract_text(self, image_path: Path, language: str = "ara+eng") -> OCRResult:
        start_time = time.perf_counter()
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self._run_tesseract, image_path, language)
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            result.processing_time_ms = duration_ms
            return result
        except pytesseract.TesseractNotFoundError as e:
            raise OCRError(
                f"Tesseract OCR executable not found: {str(e)}",
                safe_message="محرك قراءة الصور غير متاح حاليًا على الخادم.",
            )
        except Exception as e:
            raise OCRError(f"Tesseract OCR failed: {str(e)}")

    def _run_tesseract(self, image_path: Path, language: str) -> OCRResult:
        with Image.open(image_path) as img:
            # Custom configuration: PSM 3 (fully automatic page segmentation)
            custom_config = r"--oem 3 --psm 3"
            try:
                # Attempt to get word data for confidence calculation
                data = pytesseract.image_to_data(
                    img, lang=language, config=custom_config, output_type=pytesseract.Output.DICT
                )
                confs = [int(c) for c in data.get("conf", []) if str(c).isdigit() and int(c) >= 0]
                avg_conf = (sum(confs) / len(confs) / 100.0) if confs else None
            except Exception:
                avg_conf = None

            raw_text = pytesseract.image_to_string(img, lang=language, config=custom_config)

            # Fallback to PSM 6 (single uniform block) if PSM 3 returned minimal text
            if not raw_text or len(raw_text.strip()) < 15:
                alt_text = pytesseract.image_to_string(img, lang=language, config=r"--oem 3 --psm 6")
                if len(alt_text.strip()) > len(raw_text.strip() if raw_text else ""):
                    raw_text = alt_text

        return OCRResult(
            raw_text=raw_text,
            normalized_text="",  # Will be populated by normalizer
            confidence=avg_conf,
            language=language,
            provider="tesseract",
        )


class GeminiVisionOCRProvider:
    """Multimodal OCR provider using Google Gemini Vision API."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def extract_text(self, image_path: Path, language: str = "ara+eng") -> OCRResult:
        start_time = time.perf_counter()
        if not self.api_key:
            raise OCRError("Gemini API key is not configured")

        try:
            from google import genai

            client = genai.Client(api_key=self.api_key)

            loop = asyncio.get_running_loop()

            def _call_gemini():
                with open(image_path, "rb") as f:
                    image_bytes = f.read()

                prompt = (
                    "Extract the exact text from this image faithfully. "
                    "Preserve the question and all multiple choice options exactly as printed. "
                    "Do not translate, do not add commentary, and do not modify the wording."
                )

                response = None
                for model_name in [
                    "gemini-3.5-flash",
                    "gemini-3.5-flash-lite",
                    "gemini-flash-latest",
                    "gemini-2.5-flash",
                ]:
                    try:
                        response = client.models.generate_content(
                            model=model_name,
                            contents=[
                                genai.types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                                prompt,
                            ],
                        )
                        if response and response.text:
                            break
                    except Exception:
                        continue

                return response.text if response else ""

            raw_text = await loop.run_in_executor(None, _call_gemini)
            duration_ms = int((time.perf_counter() - start_time) * 1000)

            return OCRResult(
                raw_text=raw_text,
                normalized_text="",
                confidence=0.95,
                language="ar",
                provider="gemini",
                processing_time_ms=duration_ms,
            )
        except Exception as e:
            raise OCRError(f"Gemini OCR extraction failed: {str(e)}")


class MockOCRProvider:
    """Deterministic mock provider for testing and environments without Tesseract."""

    def __init__(self, default_text: str | None = None):
        self.default_text = default_text or (
            "ما هي عاصمة المملكة العربية السعودية؟\nأ) الرياض\nب) جدة\nج) الدمام\nد) مكة المكرمة\n"
        )
        self.custom_responses: dict[str, str] = {}

    def set_fixture_text(self, key: str, text: str) -> None:
        self.custom_responses[key] = text

    async def extract_text(self, image_path: Path, language: str = "ara+eng") -> OCRResult:
        filename = image_path.name
        text = self.custom_responses.get(filename, self.default_text)
        return OCRResult(
            raw_text=text,
            normalized_text="",
            confidence=0.98,
            language="ar",
            provider="mock",
            processing_time_ms=10,
        )


class OCRService:
    """Orchestrator for OCR extraction with multi-provider fallback."""

    def __init__(self, settings: Settings | None = None, primary_provider: OCRProvider | None = None):
        self.settings = settings or get_settings()
        if primary_provider:
            self.provider = primary_provider
        else:
            self.provider = self._create_provider(self.settings.OCR_PROVIDER)

    def _create_provider(self, provider_name: str) -> OCRProvider:
        provider_lower = provider_name.lower().strip()
        if provider_lower == "gemini" and self.settings.GEMINI_API_KEY:
            return GeminiVisionOCRProvider(api_key=self.settings.GEMINI_API_KEY)
        elif provider_lower == "mock":
            return MockOCRProvider()
        else:
            return TesseractOCRProvider()

    async def extract(self, image_path: Path, language: str = "ara+eng") -> OCRResult:
        """Extract text using configured provider with timeout protection and automatic Gemini fallback."""
        try:
            # 30 second timeout per OCR call
            result = await asyncio.wait_for(
                self.provider.extract_text(image_path, language=language),
                timeout=30.0,
            )
            # If primary provider returned empty or near-empty text, and Gemini key is configured, fallback to Gemini
            if (not result.raw_text or len(result.raw_text.strip()) < 15) and self.settings.GEMINI_API_KEY and not isinstance(self.provider, GeminiVisionOCRProvider):
                gemini_prov = GeminiVisionOCRProvider(api_key=self.settings.GEMINI_API_KEY)
                try:
                    return await asyncio.wait_for(
                        gemini_prov.extract_text(image_path, language=language),
                        timeout=25.0,
                    )
                except Exception:
                    pass
            return result
        except asyncio.TimeoutError:
            if self.settings.GEMINI_API_KEY and not isinstance(self.provider, GeminiVisionOCRProvider):
                gemini_prov = GeminiVisionOCRProvider(api_key=self.settings.GEMINI_API_KEY)
                try:
                    return await asyncio.wait_for(
                        gemini_prov.extract_text(image_path, language=language),
                        timeout=25.0,
                    )
                except Exception:
                    pass
            raise OCRTimeoutError("انتهت مهلة استخراج النص من الصورة (OCR Timeout).")
        except Exception:
            if self.settings.GEMINI_API_KEY and not isinstance(self.provider, GeminiVisionOCRProvider):
                gemini_prov = GeminiVisionOCRProvider(api_key=self.settings.GEMINI_API_KEY)
                try:
                    return await asyncio.wait_for(
                        gemini_prov.extract_text(image_path, language=language),
                        timeout=25.0,
                    )
                except Exception:
                    pass
            raise

    async def extract_multimodal_question(self, image_path: Path, job_id: str) -> QuestionPayload | None:
        """Direct multimodal vision extraction using Gemini to directly parse question and 4 choices."""
        if not self.settings.GEMINI_API_KEY:
            return None
        try:
            from google import genai
            from google.genai import types
            from pydantic import BaseModel

            class ExtractedQuestion(BaseModel):
                question: str
                option_a: str
                option_b: str
                option_c: str
                option_d: str

            client = genai.Client(api_key=self.settings.GEMINI_API_KEY)
            with open(image_path, "rb") as f:
                img_bytes = f.read()

            system_instruction = (
                "You are an expert OCR and educational exam parsing engine. Analyze the provided image of an educational multiple-choice question. "
                "Extract the main question text and the exactly four choices (options). "
                "Remove exam headers like 'Question No: X/Y' or selection markers. "
                "Do NOT answer the question. Strictly output structured JSON matching the schema."
            )

            models_to_try = [
                "gemini-3.5-flash",
                "gemini-3.5-flash-lite",
                "gemini-flash-latest",
                "gemini-2.5-flash",
            ]

            response = None
            for model_name in models_to_try:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=[
                            genai.types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                            "Extract the question text and 4 choices from this image into structured JSON.",
                        ],
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            response_mime_type="application/json",
                            response_schema=ExtractedQuestion,
                            temperature=0.0,
                            max_output_tokens=1000,
                        ),
                    )
                    if response and response.text:
                        break
                except Exception:
                    continue

            if response and response.text:
                import json
                data = json.loads(response.text)
                return QuestionPayload(
                    question=data.get("question", "").strip(),
                    option_a=data.get("option_a", "").strip(),
                    option_b=data.get("option_b", "").strip(),
                    option_c=data.get("option_c", "").strip(),
                    option_d=data.get("option_d", "").strip(),
                    job_id=job_id,
                )
        except Exception:
            return None
        return None
