"""Dedicated teacher delivery service for sending processed questions and tracking delivery state."""

from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from app.config.settings import Settings, get_settings
from app.domain.models import DeliveryResult


class TeacherDeliveryService:
    def __init__(self, bot: Bot, settings: Settings | None = None):
        self.bot = bot
        self.settings = settings or get_settings()

    async def deliver_processed_question(
        self,
        job_id: str,
        student_name: str,
        student_telegram_id: int,
        business_date: str,
        submitted_at: datetime,
        question_text: str | None = None,
        option_a: str | None = None,
        option_b: str | None = None,
        option_c: str | None = None,
        option_d: str | None = None,
        processed_image_path: Path | None = None,
        target_chat_id: int | None = None,
    ) -> DeliveryResult:
        """Deliver processed question text and options with metadata to the teacher chat without sending an image."""
        destination_chat_id = target_chat_id or self.settings.TEACHER_CHAT_ID

        # Convert UTC submitted_at to business local time
        local_tz = self.settings.tz
        local_time_str = submitted_at.astimezone(local_tz).strftime("%I:%M:%S %p")

        if question_text and option_a:
            message_text = (
                "📚 <b>سؤال تعليمي جديد</b>\n\n"
                f"❓ <b>نص السؤال:</b>\n{question_text}\n\n"
                "<b>الخيارات:</b>\n"
                f"1️⃣ {option_a}\n"
                f"2️⃣ {option_b}\n"
                f"3️⃣ {option_c}\n"
                f"4️⃣ {option_d}\n\n"
                f"👤 <b>الطالب:</b> {student_name}\n"
                f"🆔 <b>Student ID:</b> <code>{student_telegram_id}</code>\n"
                f"📅 <b>التاريخ:</b> {business_date}\n"
                f"🕐 <b>الوقت:</b> {local_time_str}\n"
                f"🆔 <b>Job:</b> <code>{job_id}</code>"
            )
            try:
                message = await self.bot.send_message(
                    chat_id=destination_chat_id,
                    text=message_text,
                    parse_mode="HTML",
                )
                return DeliveryResult(
                    is_success=True,
                    telegram_message_id=message.message_id,
                    delivered_at=datetime.now(timezone.utc),
                )
            except Exception as e:
                return DeliveryResult(
                    is_success=False,
                    error_message=f"فشل الإرسال إلى المعلم عبر تليجرام: {str(e)}",
                )
        else:
            # Fallback for legacy callers and tests supplying only processed image
            if not processed_image_path or not processed_image_path.exists():
                return DeliveryResult(
                    is_success=False,
                    error_message=f"ملف المعالجة غير موجود: {processed_image_path.name if processed_image_path else 'None'}",
                )

            caption = (
                "📚 <b>سؤال جديد</b>\n\n"
                f"👤 <b>الطالب:</b> {student_name}\n"
                f"🆔 <b>Student ID:</b> <code>{student_telegram_id}</code>\n"
                f"📅 <b>التاريخ:</b> {business_date}\n"
                f"🕐 <b>الوقت:</b> {local_time_str}\n"
                f"🆔 <b>Job:</b> <code>{job_id}</code>"
            )

            try:
                input_file = FSInputFile(str(processed_image_path))
                message = await self.bot.send_photo(
                    chat_id=destination_chat_id,
                    photo=input_file,
                    caption=caption,
                    parse_mode="HTML",
                )
                return DeliveryResult(
                    is_success=True,
                    telegram_message_id=message.message_id,
                    delivered_at=datetime.now(timezone.utc),
                )
            except Exception as e:
                return DeliveryResult(
                    is_success=False,
                    error_message=f"فشل الإرسال إلى المعلم عبر تليجرام: {str(e)}",
                )
