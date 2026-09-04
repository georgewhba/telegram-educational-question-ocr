"""Standardized deterministic template rendering service with first-class Arabic RTL typography."""

from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from app.config.settings import Settings, get_settings
from app.domain.exceptions import RenderingError
from app.domain.models import QuestionPayload


class RenderingService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.font_dir = Path(__file__).resolve().parent.parent.parent / "assets" / "fonts"
        self._init_fonts()

    def _init_fonts(self):
        # Look for bundled fonts in assets/fonts/
        bold_candidates = [
            self.font_dir / "arialbd.ttf",
            self.font_dir / "tahoma.ttf",
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("C:/Windows/Fonts/tahoma.ttf"),
        ]
        regular_candidates = [
            self.font_dir / "arial.ttf",
            self.font_dir / "tahoma.ttf",
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/tahoma.ttf"),
        ]

        self.bold_font_path = next((p for p in bold_candidates if p.exists()), None)
        self.regular_font_path = next((p for p in regular_candidates if p.exists()), None)

    def _get_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        path = self.bold_font_path if bold else self.regular_font_path
        if path and path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                pass
        return ImageFont.load_default()

    def format_arabic_text(self, text: str) -> str:
        """Reshape Arabic letters and apply the Unicode bidirectional algorithm for visual rendering."""
        if not text:
            return ""
        try:
            # Reshape joins connected Arabic letters properly
            reshaped = arabic_reshaper.reshape(text)
            # Reorder for visual RTL display
            bidi_text = get_display(reshaped)
            return bidi_text
        except Exception:
            return text

    def wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
        """Wrap text into lines fitting within max_width using real glyph measurement."""
        words = text.split()
        if not words:
            return []

        lines = []
        current_line = []

        dummy_img = Image.new("RGB", (1, 1))
        draw = ImageDraw.Draw(dummy_img)

        for word in words:
            test_line = " ".join(current_line + [word])
            # Check length of reshaped bidi line
            formatted_test = self.format_arabic_text(test_line)
            bbox = draw.textbbox((0, 0), formatted_test, font=font)
            line_width = bbox[2] - bbox[0]

            if line_width <= max_width or not current_line:
                current_line.append(word)
            else:
                lines.append(" ".join(current_line))
                current_line = [word]

        if current_line:
            lines.append(" ".join(current_line))

        return lines

    def render_question(self, payload: QuestionPayload, output_path: Path) -> Path:
        """Render question and 4 options onto a clean, standardized, high-res canvas."""
        canvas_width = 1080
        padding_x = 60
        content_width = canvas_width - (2 * padding_x)

        # Base font sizes
        title_font_size = 36
        q_font_size = 32
        opt_font_size = 28
        badge_font_size = 24

        font_title = self._get_font(title_font_size, bold=True)
        font_q = self._get_font(q_font_size, bold=True)
        font_opt = self._get_font(opt_font_size, bold=False)
        font_badge = self._get_font(badge_font_size, bold=True)
        font_meta = self._get_font(20, bold=False)

        # Wrap question text
        q_lines = self.wrap_text(payload.question, font_q, content_width - 60)
        line_height_q = int(q_font_size * 1.5)
        q_box_height = max(140, len(q_lines) * line_height_q + 60)

        # Wrap options
        option_badges = ["أ", "ب", "ج", "د"]
        option_texts = [payload.option_a, payload.option_b, payload.option_c, payload.option_d]
        opt_badge_width = 60
        opt_text_width = content_width - opt_badge_width - 80

        wrapped_options = []
        opt_box_heights = []
        line_height_opt = int(opt_font_size * 1.45)

        for text in option_texts:
            lines = self.wrap_text(text, font_opt, opt_text_width)
            wrapped_options.append(lines)
            height = max(90, len(lines) * line_height_opt + 40)
            opt_box_heights.append(height)

        # Calculate total required canvas height
        header_height = 140
        spacing_between_boxes = 24
        footer_height = 80
        total_height = (
            header_height
            + q_box_height
            + spacing_between_boxes
            + sum(opt_box_heights)
            + (len(opt_box_heights) * spacing_between_boxes)
            + footer_height
        )
        total_height = max(1080, total_height)

        # Create canvas
        # Modern refined color palette: Soft off-white background
        bg_color = (248, 249, 252)
        img = Image.new("RGB", (canvas_width, total_height), bg_color)
        draw = ImageDraw.Draw(img)

        # Draw Top Header Banner
        header_bg = (30, 41, 59)  # Slate 800
        draw.rectangle([(0, 0), (canvas_width, 100)], fill=header_bg)

        # Header Title
        header_title = self.format_arabic_text("بنك الأسئلة التعليمية")
        draw.text((canvas_width - padding_x, 30), header_title, font=font_title, fill=(255, 255, 255), anchor="ra")

        # Job ID badge
        job_label = f"ID: {payload.job_id[:8]}"
        draw.text((padding_x, 38), job_label, font=font_meta, fill=(148, 163, 184), anchor="la")

        # Draw Question Box
        cur_y = 130
        q_box_rect = [padding_x, cur_y, padding_x + content_width, cur_y + q_box_height]
        draw.rounded_rectangle(q_box_rect, radius=16, fill=(255, 255, 255), outline=(226, 232, 240), width=2)

        # Question Title Badge
        q_badge_text = self.format_arabic_text("السؤال:")
        draw.text(
            (padding_x + content_width - 30, cur_y + 24),
            q_badge_text,
            font=font_badge,
            fill=(15, 23, 42),
            anchor="ra",
        )

        # Draw Question Lines (Right-aligned)
        text_y = cur_y + 64
        for line in q_lines:
            f_line = self.format_arabic_text(line)
            draw.text((padding_x + content_width - 30, text_y), f_line, font=font_q, fill=(30, 41, 59), anchor="ra")
            text_y += line_height_q

        cur_y += q_box_height + spacing_between_boxes

        # Option colors & badges
        badge_colors = [
            (59, 130, 246),  # Blue
            (16, 185, 129),  # Green
            (245, 158, 11),  # Amber
            (139, 92, 246),  # Purple
        ]

        for i in range(4):
            b_height = opt_box_heights[i]
            box_rect = [padding_x, cur_y, padding_x + content_width, cur_y + b_height]
            draw.rounded_rectangle(box_rect, radius=12, fill=(255, 255, 255), outline=(226, 232, 240), width=2)

            # Option Badge Pill (positioned on the right side for RTL)
            badge_x = padding_x + content_width - 20 - opt_badge_width
            badge_y = cur_y + (b_height - opt_badge_width) // 2
            pill_rect = [badge_x, badge_y, badge_x + opt_badge_width, badge_y + opt_badge_width]
            draw.rounded_rectangle(pill_rect, radius=30, fill=badge_colors[i])

            f_badge = self.format_arabic_text(option_badges[i])
            draw.text(
                (badge_x + opt_badge_width // 2, badge_y + opt_badge_width // 2 - 2),
                f_badge,
                font=font_badge,
                fill=(255, 255, 255),
                anchor="mm",
            )

            # Option Lines (Right-aligned, leaving room for badge)
            opt_text_right = badge_x - 20
            start_opt_y = cur_y + (b_height - (len(wrapped_options[i]) * line_height_opt)) // 2
            for line in wrapped_options[i]:
                f_line = self.format_arabic_text(line)
                draw.text((opt_text_right, start_opt_y), f_line, font=font_opt, fill=(51, 65, 85), anchor="ra")
                start_opt_y += line_height_opt

            cur_y += b_height + spacing_between_boxes

        # Footer
        footer_text = self.format_arabic_text("تمت المعالجة والتحقق آليًا")
        draw.text(
            (canvas_width // 2, total_height - 40), footer_text, font=font_meta, fill=(148, 163, 184), anchor="mm"
        )

        # Save output image
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_path), "PNG", optimize=True)

        # Validate final output image
        self.validate_rendered_image(output_path)
        return output_path

    def validate_rendered_image(self, file_path: Path) -> None:
        """Validate that the generated final template file is not corrupted and adheres to specs."""
        if not file_path.exists():
            raise RenderingError("فشل إنشاء ملف القالب النهائي: الملف غير موجود.")

        size = file_path.stat().st_size
        if size < 5000:  # Less than 5KB is abnormally small for a rendered 1080p template
            raise RenderingError(f"حجم القالب النهائي صغير جدًا بصورة غير طبيعية ({size} bytes).")

        try:
            with Image.open(file_path) as img:
                img.verify()
            with Image.open(file_path) as img:
                w, h = img.size
                if w < 600 or h < 600:
                    raise RenderingError(f"أبعاد القالب النهائي غير مطابقة للمواصفات ({w}x{h}).")
        except Exception as e:
            raise RenderingError(f"الصورة الناتجة تالفة أو غير صالحة: {str(e)}")
