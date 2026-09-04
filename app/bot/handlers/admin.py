"""Admin panel Telegram handlers supporting 12 modules, pagination, callbacks, and audit logging."""

from datetime import datetime, timedelta
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards.admin_keyboards import (
    get_archive_keyboard,
    get_audit_keyboard,
    get_back_and_home_keyboard,
    get_confirmation_keyboard,
    get_export_menu_keyboard,
    get_images_keyboard,
    get_main_admin_keyboard,
    get_recipients_keyboard,
    get_schedule_details_keyboard,
    get_schedules_keyboard,
    get_student_details_keyboard,
    get_submission_details_keyboard,
)
from app.config.settings import Settings, get_settings
from app.database.repositories import (
    AuditLogRepository,
    ExportRepository,
    RecipientRepository,
    ScheduleRepository,
    SubmissionRepository,
    UserRepository,
)
from app.domain.enums import AdminAction, DeliveryStatus, ExportFormat, ProcessingStatus
from app.domain.exceptions import UnauthorizedError
from app.services.admin_service import AdminService
from app.services.export_service import ExportService
from app.services.file_service import FileService
from app.services.teacher_delivery_service import TeacherDeliveryService

admin_router = Router(name="admin_router")


def check_admin(user_id: int, settings: Settings):
    if user_id not in settings.admin_user_ids:
        raise UnauthorizedError("غير مصرح لك بالوصول إلى لوحة الإدارة.")


@admin_router.message(Command("admin"))
async def handle_admin_command(
    message: Message,
    session_factory: async_sessionmaker,
):
    """Entrypoint to the Telegram Admin Panel."""
    settings = get_settings()
    user = message.from_user
    if not user:
        return

    if user.id not in settings.admin_user_ids:
        await message.answer("⛔ ليس لديك صلاحية للوصول إلى هذا القسم.")
        return

    # Log admin panel access in audit trail
    async with session_factory() as session:
        audit_repo = AuditLogRepository(session)
        await audit_repo.log_action(
            admin_user_id=user.id,
            action=AdminAction.ADMIN_PANEL_OPEN.value,
        )
        await session.commit()

    welcome_text = (
        "🏠 <b>لوحة الإدارة والتحكم</b>\n\n"
        "مرحبًا بك في لوحة تحكم نظام معالجة الأسئلة التعليمية.\n"
        "اختر أحد الأقسام التالية لإدارة العمليات:"
    )
    await message.answer(welcome_text, reply_markup=get_main_admin_keyboard(), parse_mode="HTML")


@admin_router.callback_query(F.data == "admin_home")
async def cb_admin_home(callback: CallbackQuery):
    settings = get_settings()
    if not callback.from_user or callback.from_user.id not in settings.admin_user_ids:
        await callback.answer("⛔ غير مصرح لك.", show_alert=True)
        return

    welcome_text = (
        "🏠 <b>لوحة الإدارة والتحكم</b>\n\n"
        "مرحبًا بك في لوحة تحكم نظام معالجة الأسئلة التعليمية.\n"
        "اختر أحد الأقسام التالية لإدارة العمليات:"
    )
    await callback.message.edit_text(welcome_text, reply_markup=get_main_admin_keyboard(), parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery, session_factory: async_sessionmaker):
    """Display system dashboard metrics."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    admin_service = AdminService(session_factory, settings)
    m = await admin_service.get_dashboard_metrics()

    stats_text = (
        "📊 <b>لوحة المعلومات والإحصائيات</b>\n\n"
        f"📅 <b>تاريخ اليوم:</b> {m['today_date']}\n"
        "───────────────\n"
        f"📥 <b>الواردة اليوم:</b> {m['today_total']}\n"
        f"✅ <b>المعالجة الناجحة:</b> {m['today_success']}\n"
        f"❌ <b>المعالجة الفاشلة:</b> {m['today_failed']}\n"
        f"📤 <b>تم تسليمها للمعلم:</b> {m['today_delivered']}\n"
        f"⚠️ <b>تعذر تسليمها:</b> {m['today_delivery_failed']}\n"
        f"👥 <b>الطلاب النشطون اليوم:</b> {m['today_students']}\n"
        f"🚫 <b>الطلاب المحظورون:</b> {m['blocked_students']}\n"
        f"📅 <b>المهام المجدولة النشطة:</b> {m['active_schedules_count']}\n"
        "───────────────\n"
        f"📈 <b>إجمالي العمليات التاريخية:</b> {m['all_total']} (ناجح: {m['all_success']} | فاشل: {m['all_failed']})"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[get_back_and_home_keyboard("admin_home")])
    await callback.message.edit_text(stats_text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_submissions:"))
async def cb_admin_submissions(callback: CallbackQuery, session_factory: async_sessionmaker):
    """Browse historical submissions with pagination."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    page = int(callback.data.split(":")[1])
    admin_service = AdminService(session_factory, settings)
    res = await admin_service.list_submissions_paginated(page=page, per_page=7)

    items = res["items"]
    total = res["total_items"]
    total_pages = res["total_pages"]

    if not items:
        text = "📥 <b>الأسئلة الواردة</b>\n\nلا توجد أسئلة مسجلة حاليًا."
        kb = InlineKeyboardMarkup(inline_keyboard=[get_back_and_home_keyboard("admin_home")])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        return

    text = f"📥 <b>الأسئلة الواردة</b> (إجمالي {total} سؤال)\n\nاضغط على أي سؤال لعرض تفاصيله ومعاينته:"
    buttons = []
    for sub in items:
        time_str = sub.submitted_at_utc.astimezone(settings.tz).strftime("%H:%M")
        status_icon = "✅" if sub.processing_status == ProcessingStatus.READY else "❌"
        deliv_icon = "📤" if sub.delivery_status == DeliveryStatus.DELIVERY_SUCCESS else "⚠️"
        s_name = sub.user.display_name if sub.user else "طالب"
        label = f"{status_icon}{deliv_icon} {time_str} - {s_name[:14]}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"sub_detail:{sub.job_id}")])

    # Pagination controls
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ السابق", callback_data=f"admin_submissions:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="التالي ➡️", callback_data=f"admin_submissions:{page + 1}"))
    buttons.append(nav_row)
    buttons.append(get_back_and_home_keyboard("admin_home"))

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data.startswith("sub_detail:"))
async def cb_submission_detail(callback: CallbackQuery, session_factory: async_sessionmaker):
    """View details of a single submission record."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    job_id = callback.data.split(":")[1]
    admin_service = AdminService(session_factory, settings)
    sub = await admin_service.get_submission_details(job_id)

    if not sub:
        await callback.answer("⚠️ لم يتم العثور على هذا السؤال.", show_alert=True)
        return

    local_dt = sub.submitted_at_utc.astimezone(settings.tz)
    time_str = local_dt.strftime("%I:%M:%S %p")
    student_name = sub.user.display_name if sub.user else "طالب"
    student_id = str(sub.user.telegram_user_id) if sub.user else "-"
    username = f"@{sub.user.username}" if (sub.user and sub.user.username) else "بدون"

    text = (
        f"📄 <b>تفاصيل السؤال</b>\n\n"
        f"🆔 <b>Job ID:</b> <code>{sub.job_id}</code>\n"
        f"👤 <b>الطالب:</b> {student_name} ({username})\n"
        f"🆔 <b>Student ID:</b> <code>{student_id}</code>\n"
        f"📅 <b>التاريخ:</b> {sub.business_date} | {time_str}\n"
        f"📊 <b>حالة المعالجة:</b> {sub.processing_status.value}\n"
        f"📤 <b>حالة التسليم:</b> {sub.delivery_status.value}\n"
        f"🔁 <b>محاولات المعالجة:</b> {len(sub.attempts)}\n"
        "───────────────\n"
        f"📝 <b>السؤال:</b>\n{sub.question_text or '(لا يوجد نص مستخرج)'}\n\n"
        f"<b>أ)</b> {sub.option_a or '-'}\n"
        f"<b>ب)</b> {sub.option_b or '-'}\n"
        f"<b>ج)</b> {sub.option_c or '-'}\n"
        f"<b>د)</b> {sub.option_d or '-'}"
    )

    kb = get_submission_details_keyboard(sub.job_id, has_processed_image=bool(sub.processed_file_path))
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data.startswith("sub_orig:"))
async def cb_sub_view_orig(callback: CallbackQuery, session_factory: async_sessionmaker):
    """Send the original uploaded image to the admin."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    job_id = callback.data.split(":")[1]
    admin_service = AdminService(session_factory, settings)
    sub = await admin_service.get_submission_details(job_id)

    if not sub or not sub.original_file_path or not Path(sub.original_file_path).exists():
        await callback.answer("⚠️ ملف الصورة الأصلية غير متوفر.", show_alert=True)
        return

    photo = FSInputFile(sub.original_file_path)
    await callback.message.answer_photo(
        photo, caption=f"🖼️ الصورة الأصلية للعملية:\n<code>{job_id}</code>", parse_mode="HTML"
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("sub_proc:"))
async def cb_sub_view_proc(callback: CallbackQuery, session_factory: async_sessionmaker):
    """Send the processed rendered image to the admin."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    job_id = callback.data.split(":")[1]
    admin_service = AdminService(session_factory, settings)
    sub = await admin_service.get_submission_details(job_id)

    if not sub or not sub.processed_file_path or not Path(sub.processed_file_path).exists():
        await callback.answer("⚠️ لم يتم إنشاء صورة معالجة بعد لهذا السؤال.", show_alert=True)
        return

    photo = FSInputFile(sub.processed_file_path)
    await callback.message.answer_photo(
        photo, caption=f"🎨 الصورة المعالجة للعملية:\n<code>{job_id}</code>", parse_mode="HTML"
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_images:"))
async def cb_admin_images(callback: CallbackQuery, session_factory: async_sessionmaker):
    """Gallery and fast inspection of submissions images."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    parts = callback.data.split(":")
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
    admin_service = AdminService(session_factory, settings)
    res = await admin_service.list_submissions_paginated(page=page, per_page=6)

    items = res["items"]
    total = res["total_items"]
    total_pages = res["total_pages"]

    if not items:
        text = "🖼️ <b>الصور والمعالجات</b>\n\nلا توجد صور أو أسئلة مسجلة حاليًا."
        kb = InlineKeyboardMarkup(inline_keyboard=[get_back_and_home_keyboard("admin_home")])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        return

    text = (
        f"🖼️ <b>معاينة الصور والمعالجات</b> (إجمالي {total} سؤال)\n\n"
        "اضغط على أي من الأزرار لمعاينة الصورة الأصلية أو المعالجة مباشرة:"
    )
    kb = get_images_keyboard(items, page, total_pages)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data.startswith("sub_reproc:"))
async def cb_sub_reproc(callback: CallbackQuery, session_factory: async_sessionmaker):
    """Re-run OCR, validation and rendering for a specific submission."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    job_id = callback.data.split(":")[1]
    await callback.answer("⏳ جاري إعادة المعالجة واستخراج السؤال والخيارات...", show_alert=False)
    progress_msg = await callback.message.answer(f"⏳ جاري إعادة فحص ومعالجة السؤال <code>{job_id}</code>...")

    admin_service = AdminService(session_factory, settings)
    success, msg = await admin_service.reprocess_submission(callback.from_user.id, job_id)

    if success:
        await progress_msg.edit_text(f"✅ {msg}")
    else:
        await progress_msg.edit_text(f"❌ {msg}")

    # Re-display updated submission detail
    await cb_submission_detail(callback, session_factory)


@admin_router.callback_query(F.data.startswith("sub_resend:"))
async def cb_sub_resend(callback: CallbackQuery, bot: Bot, session_factory: async_sessionmaker):
    """Resend the existing processed question to teacher without rerunning OCR."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    job_id = callback.data.split(":")[1]
    admin_service = AdminService(session_factory, settings)
    sub = await admin_service.get_submission_details(job_id)

    if not sub or not sub.processed_file_path or not Path(sub.processed_file_path).exists():
        await callback.answer("⚠️ لا توجد صورة معالجة صالحة لإعادة إرسالها.", show_alert=True)
        return

    delivery_service = TeacherDeliveryService(bot, settings)
    res = await delivery_service.deliver_processed_question(
        job_id=job_id,
        processed_image_path=Path(sub.processed_file_path),
        student_name=sub.user.display_name if sub.user else "طالب",
        student_telegram_id=sub.user.telegram_user_id if sub.user else 0,
        business_date=str(sub.business_date),
        submitted_at=sub.submitted_at_utc,
    )

    new_deliv_status = DeliveryStatus.DELIVERY_SUCCESS if res.is_success else DeliveryStatus.DELIVERY_FAILED
    async with session_factory() as session:
        sub_repo = SubmissionRepository(session)
        audit_repo = AuditLogRepository(session)
        await sub_repo.update_status(job_id, delivery_status=new_deliv_status)
        await audit_repo.log_action(
            admin_user_id=callback.from_user.id,
            action=AdminAction.ADMIN_RESEND_SUBMISSION.value,
            target_type="submission",
            target_id=job_id,
            metadata_safe={"delivery_success": res.is_success},
        )
        await session.commit()

    if res.is_success:
        await callback.answer("✅ تمت إعادة الإرسال إلى المعلم بنجاح.", show_alert=True)
    else:
        await callback.answer("❌ تعذر تسليم الصورة إلى المعلم.", show_alert=True)


@admin_router.callback_query(F.data.startswith("sub_del_confirm:"))
async def cb_sub_del_confirm(callback: CallbackQuery):
    job_id = callback.data.split(":")[1]
    confirm_kb = get_confirmation_keyboard(
        confirm_callback=f"sub_del_do:{job_id}",
        cancel_callback=f"sub_detail:{job_id}",
    )
    await callback.message.edit_text(
        f"⚠️ <b>تأكيد الحذف</b>\n\nهل أنت متأكد من رغبتك في حذف السؤال <code>{job_id}</code> نهائيًا؟",
        reply_markup=confirm_kb,
        parse_mode="HTML",
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("sub_del_do:"))
async def cb_sub_del_do(callback: CallbackQuery, session_factory: async_sessionmaker):
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    job_id = callback.data.split(":")[1]
    admin_service = AdminService(session_factory, settings)
    deleted = await admin_service.delete_submission(callback.from_user.id, job_id)

    if deleted:
        await callback.answer("✅ تم حذف السؤال بنجاح.", show_alert=True)
    else:
        await callback.answer("⚠️ تعذر حذف السؤال.", show_alert=True)

    # Return to submissions list
    await cb_admin_submissions(callback, session_factory)


@admin_router.callback_query(F.data == "admin_export_menu")
async def cb_export_menu(callback: CallbackQuery):
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    text = (
        "📄 <b>تصدير الملفات والتقارير</b>\n\n"
        "يمكنك إنشاء وتنزيل تقارير الأسئلة بصيغة DOCX (Word) أو Excel (XLSX) "
        "مرتبة زمنيًا بدقة مع الصور وتفاصيل الطلاب:"
    )
    await callback.message.edit_text(text, reply_markup=get_export_menu_keyboard(), parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data.startswith("export_today:") | F.data.startswith("export_yesterday:"))
async def cb_trigger_export(callback: CallbackQuery, session_factory: async_sessionmaker):
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    parts = callback.data.split(":")
    mode = parts[0]
    fmt = ExportFormat(parts[1])

    today = datetime.now(settings.tz).date()
    target_date = today if mode == "export_today" else (today - timedelta(days=1))

    await callback.answer("⏳ جاري تجهيز الملف وتجميعه...")
    await callback.message.answer(f"⏳ جاري تجميع أسئلة {target_date} بصيغة {fmt.value}...")

    file_service = FileService(settings)
    export_service = ExportService(settings)

    async with session_factory() as session:
        sub_repo = SubmissionRepository(session)
        export_repo = ExportRepository(session)
        audit_repo = AuditLogRepository(session)

        submissions = await sub_repo.get_chronological_for_date_range(target_date, target_date, successful_only=True)

        if not submissions:
            await callback.message.answer(f"ℹ️ لا توجد أسئلة ناجحة مسجلة لتاريخ {target_date}.")
            return

        export_id = file_service.generate_export_id()
        ext = "docx" if fmt == ExportFormat.DOCX else "xlsx"
        file_path = file_service.get_export_path(export_id, ext)

        if fmt == ExportFormat.DOCX:
            export_service.generate_docx(submissions, file_path, target_date, target_date)
        else:
            export_service.generate_excel(submissions, file_path, target_date, target_date)

        await export_repo.create(
            export_id=export_id,
            export_type="MANUAL",
            date_from=target_date,
            date_to=target_date,
            format=fmt,
            content_config={"target_date": str(target_date)},
            created_by=callback.from_user.id,
        )
        await audit_repo.log_action(
            admin_user_id=callback.from_user.id,
            action=AdminAction.ADMIN_CREATE_EXPORT.value,
            target_type="export",
            target_id=export_id,
        )
        await session.commit()

    # Send generated document directly to admin
    doc_file = FSInputFile(str(file_path))
    caption = (
        f"✅ <b>ملف التصدير جاهز</b>\n\n"
        f"📅 <b>التاريخ:</b> {target_date}\n"
        f"📥 <b>عدد الأسئلة:</b> {len(submissions)}\n"
        f"📄 <b>الصيغة:</b> {fmt.value}"
    )
    await callback.message.answer_document(doc_file, caption=caption, parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("admin_archive:"))
async def cb_admin_archive(callback: CallbackQuery, session_factory: async_sessionmaker):
    """Browse archive of generated export reports."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    parts = callback.data.split(":")
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
    admin_service = AdminService(session_factory, settings)
    res = await admin_service.list_exports_paginated(page=page, per_page=6)

    items = res["items"]
    total = res["total_items"]
    total_pages = res["total_pages"]

    if not items:
        text = "📦 <b>أرشيف الملفات والتقارير</b>\n\nلا توجد ملفات تصدير محفوظة حاليًا."
        kb = InlineKeyboardMarkup(inline_keyboard=[get_back_and_home_keyboard("admin_export_menu")])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        return

    text = f"📦 <b>أرشيف الملفات والتقارير</b> (إجمالي {total} ملف):\n\nاضغط على أي ملف لتنزيله مباشرة إلى جهازك:"
    kb = get_archive_keyboard(items, page, total_pages)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data.startswith("archive_dl:"))
async def cb_archive_download(callback: CallbackQuery, session_factory: async_sessionmaker):
    """Send an archived document directly to admin."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    export_id = callback.data.split(":")[1]
    file_service = FileService(settings)

    async with session_factory() as session:
        export_repo = ExportRepository(session)
        exp = await export_repo.get_by_id(export_id)

    if not exp:
        await callback.answer("⚠️ لم يتم العثور على هذا الملف في السجل.", show_alert=True)
        return

    ext = "docx" if exp.format == ExportFormat.DOCX else "xlsx"
    file_path = file_service.get_export_path(export_id, ext)
    if not file_path.exists():
        if exp.file_path and Path(exp.file_path).exists():
            file_path = Path(exp.file_path)
        else:
            await callback.answer("⚠️ ملف التقرير غير موجود على القرص أو انتهت مدة الاحتفاظ به.", show_alert=True)
            return

    await callback.answer("📥 جاري إرسال الملف...")
    doc_file = FSInputFile(str(file_path))
    fmt_str = exp.format.value if hasattr(exp.format, "value") else str(exp.format)
    caption = (
        f"📄 <b>ملف أرشيف:</b> <code>{exp.id}</code>\n"
        f"📅 <b>الفترة:</b> {exp.date_from} إلى {exp.date_to}\n"
        f"🏷️ <b>النوع:</b> {fmt_str}"
    )
    await callback.message.answer_document(doc_file, caption=caption, parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("admin_students:"))
async def cb_admin_students(callback: CallbackQuery, session_factory: async_sessionmaker):
    """View and manage students list."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    page = int(callback.data.split(":")[1])
    async with session_factory() as session:
        user_repo = UserRepository(session)
        skip = (page - 1) * 8
        students = await user_repo.list_students(skip=skip, limit=8)
        total = await user_repo.count_students()

    total_pages = max(1, (total + 7) // 8)
    if not students:
        text = "👥 <b>الطلاب</b>\n\nلا يوجد طلاب مسجلون حاليًا."
        kb = InlineKeyboardMarkup(inline_keyboard=[get_back_and_home_keyboard("admin_home")])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        return

    text = f"👥 <b>إدارة الطلاب</b> (إجمالي {total} طالب):\n\nاضغط على أي طالب لإدارته وحظره/إلغاء حظره:"
    buttons = []
    for st in students:
        status_icon = "🚫" if st.is_blocked else "🟢"
        name = st.display_name[:18]
        buttons.append(
            [InlineKeyboardButton(text=f"{status_icon} {name}", callback_data=f"student_view:{st.telegram_user_id}")]
        )

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ السابق", callback_data=f"admin_students:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="التالي ➡️", callback_data=f"admin_students:{page + 1}"))
    buttons.append(nav_row)
    buttons.append(get_back_and_home_keyboard("admin_home"))

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data.startswith("student_view:"))
async def cb_student_view(callback: CallbackQuery, session_factory: async_sessionmaker):
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    t_id = int(callback.data.split(":")[1])
    async with session_factory() as session:
        user_repo = UserRepository(session)
        sub_repo = SubmissionRepository(session)
        student = await user_repo.get_by_telegram_id(t_id)
        if not student:
            await callback.answer("⚠️ الطالب غير موجود.", show_alert=True)
            return
        sub_count = await sub_repo.count_submissions(user_id=student.id)

    status_str = "🚫 محظور" if student.is_blocked else "🟢 نشط"
    text = (
        f"👤 <b>الملف الشخصي للطالب</b>\n\n"
        f"🏷️ <b>الاسم:</b> {student.display_name}\n"
        f"🆔 <b>Telegram ID:</b> <code>{student.telegram_user_id}</code>\n"
        f"🔗 <b>اسم المستخدم:</b> @{student.username or 'بدون'}\n"
        f"📊 <b>الحالة:</b> {status_str}\n"
        f"📥 <b>إجمالي الأسئلة المرسلة:</b> {sub_count}\n"
        f"🕐 <b>آخر ظهور:</b> {student.last_seen_at.strftime('%Y-%m-%d %H:%M')}"
    )
    kb = get_student_details_keyboard(student.telegram_user_id, student.is_blocked)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data.startswith("student_block:") | F.data.startswith("student_unblock:"))
async def cb_student_toggle_block(callback: CallbackQuery, session_factory: async_sessionmaker):
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    action, t_id_str = callback.data.split(":")
    t_id = int(t_id_str)
    is_blocked = action == "student_block"

    admin_service = AdminService(session_factory, settings)
    await admin_service.set_student_blocked(callback.from_user.id, t_id, is_blocked)

    status_msg = "🚫 تم حظر الطالب بنجاح." if is_blocked else "✅ تم إلغاء حظر الطالب."
    await callback.answer(status_msg, show_alert=True)
    await cb_student_view(callback, session_factory)


@admin_router.callback_query(F.data == "admin_health")
async def cb_admin_health(callback: CallbackQuery, session_factory: async_sessionmaker):
    """View system diagnostic health."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    admin_service = AdminService(session_factory, settings)
    h = await admin_service.get_system_health()

    text = (
        "🟢 <b>حالة النظام والجاهزية</b>\n\n"
        f"🤖 <b>البوت (Aiogram):</b> {'🟢 متصل ويعمل' if h['bot_running'] else '🔴 متوقف'}\n"
        f"🗄️ <b>قاعدة البيانات (SQLAlchemy):</b> {h['database']}\n"
        f"💾 <b>نظام التخزين المحلي (Storage):</b> {h['storage']}\n"
        f"🌐 <b>المنطقة الزمنية (Timezone):</b> <code>{h['timezone']}</code>\n"
        f"👁️ <b>محرك الـ OCR:</b> <code>{h['ocr_provider']}</code>\n"
        f"⚙️ <b>البيئة التشغيلية:</b> <code>{h['environment']}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[get_back_and_home_keyboard("admin_home")])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data == "admin_settings")
async def cb_admin_settings(callback: CallbackQuery):
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    text = (
        "⚙️ <b>الإعدادات التشغيلية للنظام</b>\n\n"
        f"⏱️ <b>موعد التصدير المجدول اليومي:</b> {settings.DEFAULT_EXPORT_TIME}\n"
        f"📦 <b>مدة الاحتفاظ بالصور:</b> {settings.IMAGE_RETENTION_DAYS} يومًا\n"
        f"📄 <b>مدة الاحتفاظ بالملفات:</b> {settings.EXPORT_RETENTION_DAYS} يومًا\n"
        f"🛡️ <b>الحد الأقصى لحجم الصورة:</b> {settings.MAX_FILE_SIZE_MB}MB\n"
        f"⚡ <b>الحد الأقصى للطلبات:</b> {settings.RATE_LIMIT_REQUESTS} طلبات لكل {settings.RATE_LIMIT_WINDOW_SECONDS} ثانية\n"
        f"👨‍🏫 <b>معرف محادثة المعلم:</b> <code>{settings.TEACHER_CHAT_ID}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[get_back_and_home_keyboard("admin_home")])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_audit:"))
async def cb_admin_audit(callback: CallbackQuery, session_factory: async_sessionmaker):
    """Browse security and operational audit trail logs."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    parts = callback.data.split(":")
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
    admin_service = AdminService(session_factory, settings)
    res = await admin_service.list_audit_logs_paginated(page=page, per_page=6)

    items = res["items"]
    total = res["total_items"]
    total_pages = res["total_pages"]

    if not items:
        text = "🛡️ <b>سجل الإدارة والأمان</b>\n\nلا توجد عمليات مسجلة في سجل الأمان حاليًا."
        kb = InlineKeyboardMarkup(inline_keyboard=[get_back_and_home_keyboard("admin_home")])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        return

    text = f"🛡️ <b>سجل الإدارة والأمان</b> (إجمالي {total} عملية):\n\n"
    for log in items:
        local_time = log.created_at.astimezone(settings.tz).strftime("%m/%d %H:%M:%S")
        target_str = f" (<code>{log.target_id}</code>)" if log.target_id else ""
        text += f"• <b>{log.action}</b>{target_str}\n  👤 <code>{log.admin_user_id}</code> | 🕐 {local_time}\n\n"

    kb = get_audit_keyboard(page, total_pages)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_errors:"))
async def cb_admin_errors(callback: CallbackQuery, session_factory: async_sessionmaker):
    """Error Center displaying failed questions."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    parts = callback.data.split(":")
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
    skip = (page - 1) * 8
    admin_service = AdminService(session_factory, settings)
    failed_items = await admin_service.get_failed_submissions(skip=skip, limit=8)

    if not failed_items:
        text = "⚠️ <b>مركز الأخطاء</b>\n\n🟢 لا توجد أي أخطاء أو عمليات فاشلة مسجلة."
        kb = InlineKeyboardMarkup(inline_keyboard=[get_back_and_home_keyboard("admin_home")])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        return

    text = f"⚠️ <b>مركز الأخطاء</b> ({len(failed_items)} عملية فاشلة):\n\nاضغط على أي عملية لفحصها أو إعادة معالجتها:"
    buttons = []
    for sub in failed_items:
        time_str = sub.submitted_at_utc.astimezone(settings.tz).strftime("%H:%M")
        name = sub.user.display_name if sub.user else "طالب"
        buttons.append(
            [InlineKeyboardButton(text=f"❌ {time_str} - {name[:16]}", callback_data=f"sub_detail:{sub.job_id}")]
        )

    buttons.append(get_back_and_home_keyboard("admin_home"))
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data == "admin_schedules")
async def cb_admin_schedules(callback: CallbackQuery, session_factory: async_sessionmaker):
    """List all scheduled recurring export jobs."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    async with session_factory() as session:
        sched_repo = ScheduleRepository(session)
        schedules = await sched_repo.get_all()

    text = (
        "📅 <b>الجدولة اليومية والتقارير الدورية</b>\n\n"
        "المهام المجدولة المسجلة لإرسال تقارير الأسئلة آليًا:\n"
        "اضغط على أي مهمة لإدارتها، أو إيقافها، أو تشغيلها فوريًا الآن:\n\n"
        f"• المنطقة الزمنية: <code>{settings.TIMEZONE}</code>\n"
        f"• تخطي الأيام الفارغة: <b>{'نعم' if settings.SKIP_EMPTY_DAYS else 'لا'}</b>"
    )
    kb = get_schedules_keyboard(schedules)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data.startswith("sched_detail:"))
async def cb_sched_detail(callback: CallbackQuery, session_factory: async_sessionmaker):
    """Display individual schedule options and toggle buttons."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    sched_id = int(callback.data.split(":")[1])
    async with session_factory() as session:
        sched_repo = ScheduleRepository(session)
        schedule = await sched_repo.get_by_id(sched_id)

    if not schedule:
        await callback.answer("⚠️ المهمة غير موجودة.", show_alert=True)
        return

    status_str = "🟢 نشطة وتعمل تلقائيًا" if schedule.is_active else "⏸️ متوقفة مؤقتًا"
    fmt_str = schedule.format.value if hasattr(schedule.format, "value") else str(schedule.format)
    text = (
        f"📅 <b>إدارة المهمة المجدولة #{schedule.id}</b>\n\n"
        f"⏰ <b>موعد الإرسال اليومي:</b> {schedule.time_of_day}\n"
        f"📄 <b>صيغة الملف:</b> {fmt_str}\n"
        f"🌐 <b>المنطقة الزمنية:</b> {schedule.timezone}\n"
        f"📊 <b>الحالة الحالية:</b> {status_str}"
    )
    kb = get_schedule_details_keyboard(schedule.id, schedule.is_active)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data.startswith("sched_toggle:"))
async def cb_sched_toggle(callback: CallbackQuery, session_factory: async_sessionmaker):
    """Toggle a schedule active status."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    sched_id = int(callback.data.split(":")[1])
    admin_service = AdminService(session_factory, settings)
    new_state = await admin_service.toggle_schedule(callback.from_user.id, sched_id)

    alert_txt = "🟢 تم تفعيل المهمة المجدولة بنجاح." if new_state else "⏸️ تم إيقاف المهمة المجدولة."
    await callback.answer(alert_txt, show_alert=True)
    await cb_sched_detail(callback, session_factory)


@admin_router.callback_query(F.data.startswith("sched_run:"))
async def cb_sched_run(callback: CallbackQuery, bot: Bot, session_factory: async_sessionmaker):
    """Trigger schedule export immediately."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    sched_id = int(callback.data.split(":")[1])
    await callback.answer("⚡ جاري تنفيذ المهمة وتوليد الملف...", show_alert=False)

    from app.services.scheduling_service import SchedulingService

    scheduler = SchedulingService(bot=bot, session_factory=session_factory, settings=settings)
    success = await scheduler.trigger_manually(sched_id)

    if success:
        await callback.message.answer(f"✅ تم تنفيذ المهمة المجدولة #{sched_id} وإرسال التقرير للمعلمين بنجاح.")
    else:
        await callback.message.answer(f"⚠️ تم تشغيل المهمة #{sched_id} (قد لا توجد أسئلة لليوم أو تم تخطيها).")


@admin_router.callback_query(F.data == "admin_recipients")
async def cb_admin_recipients(callback: CallbackQuery, session_factory: async_sessionmaker):
    """List and toggle recipients."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    async with session_factory() as session:
        recip_repo = RecipientRepository(session)
        recipients = await recip_repo.get_all(active_only=False)

    text = (
        "📤 <b>إدارة المستلمين (المعلمون والقنوات)</b>\n\n"
        "المستلمون المسجلون لتلقي التقارير الدورية والأسئلة:\n"
        "اضغط على أي مستلم لتفعيل أو تعطيل استلامه:"
    )
    if not recipients:
        text += f"\n\nالمستلم الأساسي في الإعدادات: <code>{settings.TEACHER_CHAT_ID}</code>"

    kb = get_recipients_keyboard(recipients)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data.startswith("recip_toggle:"))
async def cb_recip_toggle(callback: CallbackQuery, session_factory: async_sessionmaker):
    """Toggle a recipient active status."""
    settings = get_settings()
    check_admin(callback.from_user.id, settings)

    recip_id = int(callback.data.split(":")[1])
    admin_service = AdminService(session_factory, settings)
    new_state = await admin_service.toggle_recipient(callback.from_user.id, recip_id)

    alert_txt = "🟢 تم تفعيل المستلم." if new_state else "⛔ تم تعطيل المستلم."
    await callback.answer(alert_txt, show_alert=True)
    await cb_admin_recipients(callback, session_factory)


@admin_router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    """No-operation acknowledgment for page indicators."""
    await callback.answer()


@admin_router.callback_query()
async def cb_fallback(callback: CallbackQuery):
    """Safety catch-all to guarantee no button in the admin interface ever hangs with a spinner."""
    await callback.answer("ℹ️ هذا الإجراء غير متاح حاليًا أو انتهت صلاحية الزر.", show_alert=False)
