"""Unit tests for template rendering service."""

from app.services.rendering_service import RenderingService


def test_format_arabic_text(test_settings):
    renderer = RenderingService(test_settings)
    arabic_text = "السؤال الأول"
    formatted = renderer.format_arabic_text(arabic_text)
    assert len(formatted) > 0


def test_render_and_validate_canvas(tmp_path, sample_question_payload, test_settings):
    renderer = RenderingService(test_settings)
    out_file = tmp_path / "rendered_output.png"

    result_path = renderer.render_question(sample_question_payload, out_file)
    assert result_path.exists()
    assert result_path.stat().st_size > 5000  # Valid rendered template size
