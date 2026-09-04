"""Export service generating professional, chronologically ordered DOCX and Excel files."""

from datetime import date
from pathlib import Path

import docx
import openpyxl
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.shared import Inches, Pt, RGBColor
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.config.settings import Settings, get_settings
from app.database.models import Submission
from app.domain.exceptions import ExportError


def set_cell_rtl(cell):
    """Set right-to-left layout for a table cell in python-docx."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcBidi = OxmlElement("w:tcBidi")
    tcPr.append(tcBidi)


def set_paragraph_rtl(paragraph):
    """Set right-to-left direction for a paragraph in python-docx."""
    pPr = paragraph._p.get_or_add_pPr()
    bidi = OxmlElement("w:bidi")
    pPr.append(bidi)


class ExportService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def generate_docx(
        self,
        submissions: list[Submission],
        output_path: Path,
        date_from: date,
        date_to: date,
        include_processed_images: bool = True,
    ) -> Path:
        """Generate a professionally styled, RTL-aware DOCX file of submissions ordered chronologically."""
        try:
            doc = docx.Document()

            # Set 0.75 inch margins for comfortable layout
            for section in doc.sections:
                section.top_margin = Inches(0.75)
                section.bottom_margin = Inches(0.75)
                section.left_margin = Inches(0.75)
                section.right_margin = Inches(0.75)

            # Document Title
            title_p = doc.add_paragraph()
            title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            set_paragraph_rtl(title_p)
            title_run = title_p.add_run("تقرير الأسئلة التعليمية")
            title_run.font.name = "Arial"
            title_run.font.size = Pt(22)
            title_run.font.bold = True
            title_run.font.color.rgb = RGBColor(30, 41, 59)

            # Subtitle / Date Range
            sub_p = doc.add_paragraph()
            sub_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            set_paragraph_rtl(sub_p)
            if date_from == date_to:
                date_text = f"التاريخ: {date_from.strftime('%Y-%m-%d')} | إجمالي الأسئلة: {len(submissions)}"
            else:
                date_text = f"الفترة من: {date_from.strftime('%Y-%m-%d')} إلى {date_to.strftime('%Y-%m-%d')} | الإجمالي: {len(submissions)}"
            sub_run = sub_p.add_run(date_text)
            sub_run.font.name = "Arial"
            sub_run.font.size = Pt(12)
            sub_run.font.color.rgb = RGBColor(100, 116, 139)

            doc.add_paragraph().paragraph_format.space_after = Pt(12)

            # Ensure chronological order (ASC)
            sorted_submissions = sorted(submissions, key=lambda s: s.submitted_at_utc)

            for idx, sub in enumerate(sorted_submissions, start=1):
                # Header for Question
                q_head_p = doc.add_paragraph()
                set_paragraph_rtl(q_head_p)
                head_run = q_head_p.add_run(f"سؤال رقم #{idx}")
                head_run.font.name = "Arial"
                head_run.font.size = Pt(16)
                head_run.font.bold = True
                head_run.font.color.rgb = RGBColor(37, 99, 235)  # Blue 600

                # Metadata table
                table = doc.add_table(rows=2, cols=2)
                table.autofit = False

                local_dt = sub.submitted_at_utc.astimezone(self.settings.tz)
                time_str = local_dt.strftime("%I:%M:%S %p")
                student_name = sub.user.display_name if sub.user else "طالب"
                student_id = str(sub.user.telegram_user_id) if sub.user else "-"

                cell_00 = table.cell(0, 0)
                cell_00.text = f"الطالب: {student_name}"
                set_cell_rtl(cell_00)

                cell_01 = table.cell(0, 1)
                cell_01.text = f"معرف الطالب: {student_id}"
                set_cell_rtl(cell_01)

                cell_10 = table.cell(1, 0)
                cell_10.text = f"التاريخ والوقت: {sub.business_date} {time_str}"
                set_cell_rtl(cell_10)

                cell_11 = table.cell(1, 1)
                cell_11.text = f"معرف العملية (Job ID): {sub.job_id[:12]}"
                set_cell_rtl(cell_11)

                for row in table.rows:
                    for cell in row.cells:
                        for p in cell.paragraphs:
                            set_paragraph_rtl(p)
                            for run in p.runs:
                                run.font.name = "Arial"
                                run.font.size = Pt(10)
                                run.font.color.rgb = RGBColor(71, 85, 105)

                doc.add_paragraph().paragraph_format.space_after = Pt(6)

                # Question text
                q_p = doc.add_paragraph()
                set_paragraph_rtl(q_p)
                q_label = q_p.add_run("نص السؤال:\n")
                q_label.font.name = "Arial"
                q_label.font.bold = True
                q_label.font.size = Pt(12)

                q_body = q_p.add_run(sub.question_text or "(لا يوجد نص مستخرج)")
                q_body.font.name = "Arial"
                q_body.font.size = Pt(12)
                q_body.font.color.rgb = RGBColor(15, 23, 42)

                # Options table
                opt_table = doc.add_table(rows=4, cols=2)
                opt_table.autofit = False
                col_widths = [Inches(0.6), Inches(5.8)]

                options = [
                    ("أ", sub.option_a or "-"),
                    ("ب", sub.option_b or "-"),
                    ("ج", sub.option_c or "-"),
                    ("د", sub.option_d or "-"),
                ]

                for row_idx, (letter, text) in enumerate(options):
                    c0 = opt_table.cell(row_idx, 0)
                    c0.width = col_widths[0]
                    c0.text = f"({letter})"
                    set_cell_rtl(c0)

                    c1 = opt_table.cell(row_idx, 1)
                    c1.width = col_widths[1]
                    c1.text = text
                    set_cell_rtl(c1)

                    for cell in (c0, c1):
                        for p in cell.paragraphs:
                            set_paragraph_rtl(p)
                            for run in p.runs:
                                run.font.name = "Arial"
                                run.font.size = Pt(11)

                # Embedded Processed Image
                if include_processed_images and sub.processed_file_path:
                    img_path = Path(sub.processed_file_path)
                    if img_path.exists():
                        doc.add_paragraph().paragraph_format.space_after = Pt(8)
                        img_p = doc.add_paragraph()
                        img_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        set_paragraph_rtl(img_p)
                        img_p.add_run("الصورة المعالجة:\n").font.size = Pt(10)
                        # Restrict image width to 4.8 inches to prevent page layout distortion
                        img_p.add_run().add_picture(str(img_path), width=Inches(4.8))

                # Add a page break between questions (except after last question)
                if idx < len(sorted_submissions):
                    doc.add_page_break()

            output_path.parent.mkdir(parents=True, exist_ok=True)
            doc.save(str(output_path))

            self._validate_export_file(output_path)
            return output_path
        except Exception as e:
            raise ExportError(f"فشل إنشاء ملف DOCX: {str(e)}")

    def generate_excel(
        self,
        submissions: list[Submission],
        output_path: Path,
        date_from: date,
        date_to: date,
    ) -> Path:
        """Generate a professionally formatted XLSX file with questions and options chronologically ordered."""
        try:
            wb = openpyxl.Workbook()

            # Sheet 1: Questions
            ws = wb.active
            ws.title = "الأسئلة"
            ws.views.sheetView[0].rightToLeft = True  # RTL display

            headers = [
                "#",
                "Job ID",
                "اسم الطالب",
                "معرف الطالب",
                "اسم المستخدم",
                "التاريخ",
                "الوقت",
                "حالة المعالجة",
                "حالة الإرسال",
                "نص السؤال",
                "الاختيار (أ)",
                "الاختيار (ب)",
                "الاختيار (ج)",
                "الاختيار (د)",
            ]

            ws.append(headers)

            # Style Headers
            header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
            header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
            header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

            thin_border = Border(
                left=Side(style="thin", color="E2E8F0"),
                right=Side(style="thin", color="E2E8F0"),
                top=Side(style="thin", color="E2E8F0"),
                bottom=Side(style="thin", color="E2E8F0"),
            )

            for col_num in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=col_num)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = header_align
                cell.border = thin_border

            ws.row_dimensions[1].height = 30

            # Sort chronologically
            sorted_submissions = sorted(submissions, key=lambda s: s.submitted_at_utc)

            # Alternate row fills for readability
            alt_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
            regular_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")

            for idx, sub in enumerate(sorted_submissions, start=1):
                local_dt = sub.submitted_at_utc.astimezone(self.settings.tz)
                time_str = local_dt.strftime("%I:%M:%S %p")
                student_name = sub.user.display_name if sub.user else "طالب"
                student_id = sub.user.telegram_user_id if sub.user else 0
                username = f"@{sub.user.username}" if (sub.user and sub.user.username) else "-"

                row_data = [
                    idx,
                    sub.job_id,
                    student_name,
                    student_id,
                    username,
                    str(sub.business_date),
                    time_str,
                    sub.processing_status.value,
                    sub.delivery_status.value,
                    sub.question_text or "",
                    sub.option_a or "",
                    sub.option_b or "",
                    sub.option_c or "",
                    sub.option_d or "",
                ]
                ws.append(row_data)

                row_num = idx + 1
                row_fill = alt_fill if idx % 2 == 0 else regular_fill
                ws.row_dimensions[row_num].height = 24

                for col_num in range(1, len(headers) + 1):
                    cell = ws.cell(row=row_num, column=col_num)
                    cell.fill = row_fill
                    cell.border = thin_border
                    cell.font = Font(name="Arial", size=10)
                    # Align numbers center, text right
                    if col_num in [1, 4, 6, 7, 8, 9]:
                        cell.alignment = Alignment(horizontal="center", vertical="center")
                    else:
                        cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)

            # Enable auto-filter on table
            ws.auto_filter.ref = ws.dimensions

            # Freeze panes for top row
            ws.freeze_panes = "A2"

            # Auto-fit column widths with upper bounds
            col_width_limits = {
                1: 6,
                2: 24,
                3: 18,
                4: 16,
                5: 16,
                6: 12,
                7: 14,
                8: 16,
                9: 16,
                10: 45,
                11: 25,
                12: 25,
                13: 25,
                14: 25,
            }

            for col_idx, width in col_width_limits.items():
                col_letter = get_column_letter(col_idx)
                ws.column_dimensions[col_letter].width = width

            output_path.parent.mkdir(parents=True, exist_ok=True)
            wb.save(str(output_path))

            self._validate_export_file(output_path)
            return output_path
        except Exception as e:
            raise ExportError(f"فشل إنشاء ملف Excel: {str(e)}")

    def _validate_export_file(self, file_path: Path) -> None:
        if not file_path.exists():
            raise ExportError(f"ملف التصدير غير موجود: {file_path}")
        if file_path.stat().st_size == 0:
            raise ExportError(f"ملف التصدير فارغ (0 bytes): {file_path}")
