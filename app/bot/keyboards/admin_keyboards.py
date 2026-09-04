"""Inline keyboards for Telegram admin panel navigation, pagination, and confirmation dialogs."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_main_admin_keyboard() -> InlineKeyboardMarkup:
    """Construct the main admin control panel keyboard with 12 operational sections."""
    keyboard = [
        [
            InlineKeyboardButton(text="📊 الإحصائيات", callback_data="admin_stats"),
            InlineKeyboardButton(text="📥 الأسئلة الواردة", callback_data="admin_submissions:1"),
        ],
        [
            InlineKeyboardButton(text="🖼️ الصور والمعالجات", callback_data="admin_images:1"),
            InlineKeyboardButton(text="📄 الملفات والتصدير", callback_data="admin_export_menu"),
        ],
        [
            InlineKeyboardButton(text="📅 الجدولة", callback_data="admin_schedules"),
            InlineKeyboardButton(text="👥 الطلاب", callback_data="admin_students:1"),
        ],
        [
            InlineKeyboardButton(text="📤 المستلمون", callback_data="admin_recipients"),
            InlineKeyboardButton(text="⚠️ الأخطاء", callback_data="admin_errors:1"),
        ],
        [
            InlineKeyboardButton(text="📦 الأرشيف", callback_data="admin_archive:1"),
            InlineKeyboardButton(text="🛡️ سجل الإدارة", callback_data="admin_audit:1"),
        ],
        [
            InlineKeyboardButton(text="🟢 حالة النظام", callback_data="admin_health"),
            InlineKeyboardButton(text="⚙️ الإعدادات", callback_data="admin_settings"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_back_and_home_keyboard(back_callback: str) -> list[InlineKeyboardButton]:
    """Provide standard return buttons for submenus."""
    return [
        InlineKeyboardButton(text="⬅️ رجوع", callback_data=back_callback),
        InlineKeyboardButton(text="🏠 الرئيسية", callback_data="admin_home"),
    ]


def get_pagination_keyboard(
    current_page: int,
    total_pages: int,
    prefix: str,
    back_callback: str = "admin_home",
) -> InlineKeyboardMarkup:
    """Build a pagination controller with Previous, Page indicator, Next, and Return buttons."""
    buttons = []
    nav_row = []

    if current_page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ السابق", callback_data=f"{prefix}:{current_page - 1}"))

    nav_row.append(InlineKeyboardButton(text=f"صفحة {current_page} من {total_pages}", callback_data="noop"))

    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton(text="التالي ➡️", callback_data=f"{prefix}:{current_page + 1}"))

    buttons.append(nav_row)
    buttons.append(get_back_and_home_keyboard(back_callback))
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_submission_details_keyboard(job_id: str, has_processed_image: bool = True) -> InlineKeyboardMarkup:
    """Construct action buttons for inspecting and managing a single submission."""
    rows = [
        [
            InlineKeyboardButton(text="🖼️ الأصلية", callback_data=f"sub_orig:{job_id}"),
            InlineKeyboardButton(text="🎨 المعالجة", callback_data=f"sub_proc:{job_id}"),
        ],
        [
            InlineKeyboardButton(text="🔁 إعادة المعالجة", callback_data=f"sub_reproc:{job_id}"),
            InlineKeyboardButton(text="📤 إعادة الإرسال", callback_data=f"sub_resend:{job_id}"),
        ],
        [
            InlineKeyboardButton(text="🗑️ حذف", callback_data=f"sub_del_confirm:{job_id}"),
        ],
        get_back_and_home_keyboard("admin_submissions:1"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_confirmation_keyboard(confirm_callback: str, cancel_callback: str) -> InlineKeyboardMarkup:
    """Build a safety confirmation dialog for destructive actions."""
    keyboard = [
        [
            InlineKeyboardButton(text="⚠️ نعم، تأكيد", callback_data=confirm_callback),
            InlineKeyboardButton(text="❌ إلغاء", callback_data=cancel_callback),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_student_details_keyboard(telegram_user_id: int, is_blocked: bool) -> InlineKeyboardMarkup:
    """Buttons for student profile view with block/unblock action."""
    block_action = "unblock" if is_blocked else "block"
    block_label = "✅ إلغاء الحظر" if is_blocked else "🚫 حظر الطالب"

    keyboard = [
        [
            InlineKeyboardButton(
                text=block_label,
                callback_data=f"student_{block_action}:{telegram_user_id}",
            )
        ],
        get_back_and_home_keyboard("admin_students:1"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_export_menu_keyboard() -> InlineKeyboardMarkup:
    """Export generation options menu."""
    keyboard = [
        [
            InlineKeyboardButton(text="📄 تصدير أسئلة اليوم (DOCX)", callback_data="export_today:DOCX"),
            InlineKeyboardButton(text="📊 تصدير أسئلة اليوم (Excel)", callback_data="export_today:XLSX"),
        ],
        [
            InlineKeyboardButton(text="📄 تصدير أمس (DOCX)", callback_data="export_yesterday:DOCX"),
            InlineKeyboardButton(text="📊 تصدير أمس (Excel)", callback_data="export_yesterday:XLSX"),
        ],
        [
            InlineKeyboardButton(text="📦 تصفح أرشيف الملفات", callback_data="admin_archive:1"),
        ],
        get_back_and_home_keyboard("admin_home"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_schedules_keyboard(schedules: list) -> InlineKeyboardMarkup:
    """List of active schedules with toggle and trigger options."""
    rows = []
    for s in schedules:
        status_icon = "🟢" if s.is_active else "⏸️"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{status_icon} {s.time_of_day} ({s.format.value})",
                    callback_data=f"sched_detail:{s.id}",
                )
            ]
        )
    rows.append(get_back_and_home_keyboard("admin_home"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_schedule_details_keyboard(schedule_id: int, is_active: bool) -> InlineKeyboardMarkup:
    """Action buttons for a selected recurring export schedule."""
    toggle_text = "⏸️ إيقاف التفعيل" if is_active else "🟢 تفعيل المهمة"
    keyboard = [
        [
            InlineKeyboardButton(text=toggle_text, callback_data=f"sched_toggle:{schedule_id}"),
            InlineKeyboardButton(text="⚡ تشغيل فوري الآن", callback_data=f"sched_run:{schedule_id}"),
        ],
        get_back_and_home_keyboard("admin_schedules"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_archive_keyboard(exports: list, current_page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Construct paginated archive documents list with direct download triggers."""
    buttons = []
    for exp in exports:
        fmt_str = exp.format.value if hasattr(exp.format, "value") else str(exp.format)
        created_str = exp.created_at.strftime("%m/%d %H:%M")
        btn_text = f"📥 {fmt_str} | {exp.date_from} ({created_str})"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"archive_dl:{exp.id}")])

    # Pagination controls
    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ السابق", callback_data=f"admin_archive:{current_page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"{current_page}/{total_pages}", callback_data="noop"))
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton(text="التالي ➡️", callback_data=f"admin_archive:{current_page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append(get_back_and_home_keyboard("admin_export_menu"))
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_audit_keyboard(current_page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Pagination navigation for audit logs view."""
    buttons = []
    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ السابق", callback_data=f"admin_audit:{current_page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"{current_page}/{total_pages}", callback_data="noop"))
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton(text="التالي ➡️", callback_data=f"admin_audit:{current_page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append(get_back_and_home_keyboard("admin_home"))
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_images_keyboard(submissions: list, current_page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Fast inspection keyboard for submissions original vs processed images."""
    buttons = []
    for sub in submissions:
        sub_time = sub.submitted_at_utc.strftime("%H:%M")
        student_name = sub.user.display_name[:12] if sub.user else "طالب"
        row = [
            InlineKeyboardButton(text=f"ℹ️ {sub_time} {student_name}", callback_data=f"sub_detail:{sub.job_id}"),
            InlineKeyboardButton(text="🖼️ الأصلية", callback_data=f"sub_orig:{sub.job_id}"),
        ]
        if sub.processed_file_path:
            row.append(InlineKeyboardButton(text="🎨 المعالجة", callback_data=f"sub_proc:{sub.job_id}"))
        buttons.append(row)

    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ السابق", callback_data=f"admin_images:{current_page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"{current_page}/{total_pages}", callback_data="noop"))
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton(text="التالي ➡️", callback_data=f"admin_images:{current_page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append(get_back_and_home_keyboard("admin_home"))
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_recipients_keyboard(recipients: list) -> InlineKeyboardMarkup:
    """Recipients list with direct toggle buttons."""
    buttons = []
    for r in recipients:
        status_icon = "🟢" if r.is_active else "⛔"
        btn_text = f"{status_icon} {r.name} (تبديل الحالة)"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"recip_toggle:{r.id}")])

    buttons.append(get_back_and_home_keyboard("admin_home"))
    return InlineKeyboardMarkup(inline_keyboard=buttons)
