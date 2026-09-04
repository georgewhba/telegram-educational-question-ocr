"""Telegram bot handlers for the Student workflow (image submission, validation, feedback)."""

import io
from datetime import datetime, timezone

from aiogram import Bot, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config.settings import get_settings
from app.database.repositories import (
    SubmissionRepository,
    UserRepository,
)
from app.domain.enums import DeliveryStatus, ProcessingStatus, QualityGateResult
from app.services.file_service import FileService
from app.services.image_service import ImageService
from app.services.ocr_service import OCRService
from app.services.parser_service import ParserService
from app.services.rendering_service import RenderingService
from app.services.teacher_delivery_service import TeacherDeliveryService
from app.services.validation_service import ValidationService

student_router = Router(name="student_router")


def get_services(bot: Bot, session_factory: async_sessionmaker):
    settings = get_settings()
    file_service = FileService(settings)
    image_service = ImageService(settings)
    ocr_service = OCRService(settings)
    parser_service = ParserService(settings)
    validation_service = ValidationService()
    rendering_service = RenderingService(settings)
    delivery_service = TeacherDeliveryService(bot, settings)
    return (
        settings,
        file_service,
        image_service,
        ocr_service,
        parser_service,
        validation_service,
        rendering_service,
        delivery_service,
    )


@student_router.message(CommandStart())
async def handle_start(message: Message, session_factory: async_sessionmaker):
    """Handle /start command with standard welcome instructions."""
    user = message.from_user
    if not user:
        return

    # Record or update user in database
    async with session_factory() as session:
        user_repo = UserRepository(session)
        db_user = await user_repo.get_or_create(
            telegram_user_id=user.id,
            display_name=user.full_name or user.first_name or "طالب",
            username=user.username,
        )
        await session.commit()

        if db_user.is_blocked:
            await message.answer("⛔ لا يمكنك استخدام البوت حاليًا.")
            return

    welcome_text = (
        "مرحبًا 👋\n\n"
        "أرسل صورة تحتوي على:\n"
        "- سؤال واحد\n"
        "- 4 اختيارات واضحة\n\n"
        "سيتم تحليل الصورة وتجهيزها تلقائيًا وإرسال النسخة النهائية إلى المعلم."
    )
    await message.answer(welcome_text)


@student_router.message(lambda msg: msg.photo is not None)
async def handle_question_photo(
    message: Message,
    bot: Bot,
    session_factory: async_sessionmaker,
):
    """Process an uploaded question photo through the complete engineering pipeline."""
    user = message.from_user
    if not user:
        return

    # Check user blocking
    async with session_factory() as session:
        user_repo = UserRepository(session)
        db_user = await user_repo.get_or_create(
            telegram_user_id=user.id,
            display_name=user.full_name or user.first_name or "طالب",
            username=user.username,
        )
        await session.commit()
        if db_user.is_blocked:
            await message.answer("⛔ لا يمكنك استخدام البوت حاليًا.")
            return
        user_db_id = db_user.id

    (
        settings,
        file_service,
        image_service,
        ocr_service,
        parser_service,
        validation_service,
        rendering_service,
        delivery_service,
    ) = get_services(bot, session_factory)

    # 1. Acknowledge receipt
    await message.answer("📥 تم استلام الصورة.")
    status_msg = await message.answer("⏳ جاري تحليل السؤال وتجهيز القالب...")

    job_id = file_service.generate_job_id()
    tmp_dir = file_service.get_isolated_tmp_dir(job_id)

    now_utc = datetime.now(timezone.utc)
    business_date = now_utc.astimezone(settings.tz).date()

    try:
        # 2. Download best available resolution
        photo = message.photo[-1]
        raw_bio = io.BytesIO()
        await bot.download(photo, destination=raw_bio)
        image_bytes = raw_bio.getvalue()

        # 3. Validate image security and dimensions
        val_res = image_service.validate_image_bytes(image_bytes)
        if not val_res.is_valid:
            await status_msg.edit_text(
                "❌ لم أتمكن من قراءة السؤال بشكل موثوق.\nيرجى إرسال صورة أوضح تحتوي على سؤال واحد و4 اختيارات."
            )
            return

        # 4. Save immutable original
        orig_path = file_service.get_original_path(job_id, extension="jpg")
        orig_path.write_bytes(image_bytes)

        # 5. Record initial submission in DB
        async with session_factory() as session:
            sub_repo = SubmissionRepository(session)
            await sub_repo.create_submission(
                job_id=job_id,
                user_id=user_db_id,
                submitted_at_utc=now_utc,
                business_date=business_date,
                original_file_path=str(orig_path),
            )
            await session.commit()

        # 6. Preprocessing & OCR Loop (Attempt 1: Standard, Attempt 2: Enhanced Contrast if needed)
        payload = None
        for attempt_idx, strategy in enumerate(["standard", "enhanced_contrast"], start=1):
            preproc_path = tmp_dir / f"preproc_{attempt_idx}.png"
            image_service.preprocess_image(orig_path, preproc_path, strategy=strategy)

            ocr_res = await ocr_service.extract(preproc_path)
            candidate_payload = parser_service.parse(ocr_res.raw_text, job_id=job_id)

            eval_res = validation_service.evaluate(
                candidate_payload,
                ocr_confidence=ocr_res.confidence,
                is_retry=(attempt_idx > 1),
            )

            # Record attempt in DB
            async with session_factory() as session:
                sub_repo = SubmissionRepository(session)
                sub = await sub_repo.get_by_job_id(job_id)
                if sub:
                    await sub_repo.record_attempt(
                        submission_id=sub.id,
                        attempt_number=attempt_idx,
                        stage=f"OCR_{strategy}",
                        status=eval_res.result.value,
                        safe_error_message=eval_res.reason if eval_res.result != QualityGateResult.PASS else None,
                    )
                    await session.commit()

            if eval_res.result == QualityGateResult.PASS and eval_res.cleaned_payload:
                payload = eval_res.cleaned_payload
                break

        # 7. Check if quality gate failed all attempts
        if payload is None:
            async with session_factory() as session:
                sub_repo = SubmissionRepository(session)
                await sub_repo.update_status(job_id, processing_status=ProcessingStatus.FAILED)
                await session.commit()

            await status_msg.edit_text(
                "❌ لم أتمكن من قراءة السؤال بشكل موثوق.\nيرجى إرسال صورة أوضح تحتوي على سؤال واحد و4 اختيارات."
            )
            return

        # 8. Render standardized deterministic template
        processed_path = file_service.get_processed_path(job_id)
        rendering_service.render_question(payload, processed_path)

        # Update parsed question and ready status in DB
        async with session_factory() as session:
            sub_repo = SubmissionRepository(session)
            await sub_repo.update_parsed_question(
                job_id=job_id,
                question_text=payload.question,
                option_a=payload.option_a,
                option_b=payload.option_b,
                option_c=payload.option_c,
                option_d=payload.option_d,
                processed_file_path=str(processed_path),
                processing_status=ProcessingStatus.READY,
            )
            await session.commit()

        # 9. Deliver to teacher
        delivery_res = await delivery_service.deliver_processed_question(
            job_id=job_id,
            processed_image_path=processed_path,
            student_name=user.full_name or "طالب",
            student_telegram_id=user.id,
            business_date=str(business_date),
            submitted_at=now_utc,
        )

        # 10. Update delivery result in DB and notify student accordingly
        async with session_factory() as session:
            sub_repo = SubmissionRepository(session)
            deliv_status = (
                DeliveryStatus.DELIVERY_SUCCESS if delivery_res.is_success else DeliveryStatus.DELIVERY_FAILED
            )
            await sub_repo.update_status(job_id, delivery_status=deliv_status)
            await session.commit()

        if delivery_res.is_success:
            await status_msg.edit_text("✅ تم تجهيز السؤال وإرساله للمعلم بنجاح.")
        else:
            await status_msg.edit_text("⚠️ تم تجهيز السؤال، لكن تعذر إرساله للمعلم حاليًا.")

    except Exception:
        # Non-exposing failure handling
        try:
            async with session_factory() as session:
                sub_repo = SubmissionRepository(session)
                await sub_repo.update_status(job_id, processing_status=ProcessingStatus.FAILED)
                await session.commit()
        except Exception:
            pass

        await status_msg.edit_text(
            "❌ لم أتمكن من قراءة السؤال بشكل موثوق.\nيرجى إرسال صورة أوضح تحتوي على سؤال واحد و4 اختيارات."
        )
    finally:
        # Clean temporary directory
        file_service.cleanup_tmp_dir(job_id)


@student_router.message()
async def handle_unsupported_message(message: Message):
    """Handle text, audio, stickers, etc. with friendly guidance."""
    # Ignore commands like /admin
    if message.text and message.text.startswith("/"):
        return

    guidance_text = "💡 يرجى إرسال **صورة** تحتوي على سؤال واحد وأربعة اختيارات واضحة ليتم التعرف عليها آليًا."
    await message.answer(guidance_text, parse_mode="Markdown")


@student_router.callback_query()
async def cb_student_fallback(callback: CallbackQuery):
    """Safely answer any orphaned student callback query."""
    await callback.answer()
