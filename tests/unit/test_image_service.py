"""Unit tests for ImageService validation, security checks, and preprocessing."""

import io

from PIL import Image

from app.services.image_service import ImageService


def test_validate_valid_jpeg(sample_image_bytes, test_settings):
    service = ImageService(test_settings)
    res = service.validate_image_bytes(sample_image_bytes)
    assert res.is_valid is True
    assert res.mime_type == "image/jpeg"
    assert res.width == 200
    assert res.height == 200
    assert res.error_message is None


def test_validate_empty_bytes(test_settings):
    service = ImageService(test_settings)
    res = service.validate_image_bytes(b"")
    assert res.is_valid is False
    assert "فارغ" in res.error_message


def test_validate_unsupported_mime(test_settings):
    service = ImageService(test_settings)
    fake_pdf = b"%PDF-1.4 mock content here"
    res = service.validate_image_bytes(fake_pdf)
    assert res.is_valid is False
    assert "غير مدعوم" in res.error_message


def test_validate_corrupted_image(test_settings):
    service = ImageService(test_settings)
    # Valid JPEG header followed by garbage
    corrupted = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 50
    res = service.validate_image_bytes(corrupted)
    assert res.is_valid is False


def test_validate_decompression_bomb(test_settings):
    service = ImageService(test_settings)
    # Width * Height exceeds configured MAX_IMAGE_WIDTH * MAX_IMAGE_HEIGHT
    huge_img = Image.new("RGB", (5000, 5000))
    bio = io.BytesIO()
    huge_img.save(bio, format="JPEG")
    res = service.validate_image_bytes(bio.getvalue())
    assert res.is_valid is False
    assert "تتجاوز" in res.error_message


def test_image_preprocessing(tmp_path, sample_image_bytes, test_settings):
    service = ImageService(test_settings)
    input_path = tmp_path / "input.jpg"
    input_path.write_bytes(sample_image_bytes)

    out_std = tmp_path / "out_std.png"
    out_enhanced = tmp_path / "out_enh.png"

    service.preprocess_image(input_path, out_std, strategy="standard")
    assert out_std.exists()
    assert out_std.stat().st_size > 0

    service.preprocess_image(input_path, out_enhanced, strategy="enhanced_contrast")
    assert out_enhanced.exists()
    assert out_enhanced.stat().st_size > 0
