"""Unit tests for text normalization and 3-tier hybrid question/options parsing."""

from app.services.parser_service import ParserService


def test_text_normalization(test_settings):
    parser = ParserService(test_settings)
    raw = "  ما  هو   السؤال؟  \r\n\r\n\r\nأ)   الخيار الأول \u00a0\u200b  \n\n\nب) الخيار الثاني  "
    normalized = parser.normalize_text(raw)
    assert "ما هو السؤال؟" in normalized
    assert "الخيار الأول" in normalized
    assert "\u00a0" not in normalized
    assert "\u200b" not in normalized


def test_parse_arabic_markers_tier1(test_settings):
    parser = ParserService(test_settings)
    text = "ما هي عاصمة جمهورية مصر العربية؟\nأ) القاهرة\nب) الإسكندرية\nج) الجيزة\nد) أسوان\n"
    payload = parser.parse(text, job_id="job-1")
    assert payload is not None
    assert payload.question == "ما هي عاصمة جمهورية مصر العربية؟"
    assert payload.option_a == "القاهرة"
    assert payload.option_b == "الإسكندرية"
    assert payload.option_c == "الجيزة"
    assert payload.option_d == "أسوان"


def test_parse_english_markers_tier1(test_settings):
    parser = ParserService(test_settings)
    text = "What is the capital of France?\nA) Paris\nB) London\nC) Berlin\nD) Madrid\n"
    payload = parser.parse(text, job_id="job-2")
    assert payload is not None
    assert payload.question == "What is the capital of France?"
    assert payload.option_a == "Paris"
    assert payload.option_b == "London"
    assert payload.option_c == "Berlin"
    assert payload.option_d == "Madrid"


def test_parse_numeric_markers_tier1(test_settings):
    parser = ParserService(test_settings)
    text = "كم عدد أركان الإسلام؟\n1. ثلاثة\n2. أربعة\n3. خمسة\n4. ستة\n"
    payload = parser.parse(text, job_id="job-3")
    assert payload is not None
    assert "كم عدد أركان الإسلام؟" in payload.question
    assert payload.option_a == "ثلاثة"
    assert payload.option_b == "أربعة"
    assert payload.option_c == "خمسة"
    assert payload.option_d == "ستة"


def test_parse_inline_options_tier2(test_settings):
    parser = ParserService(test_settings)
    text = "ما هي وحدة قياس القوة؟\nأ) نيوتن    ب) جول\nج) واط     د) باسكال\n"
    payload = parser.parse(text, job_id="job-4")
    assert payload is not None
    assert "وحدة قياس القوة" in payload.question
    assert payload.option_a == "نيوتن"
    assert payload.option_b == "جول"
    assert payload.option_c == "واط"
    assert payload.option_d == "باسكال"


def test_parse_incomplete_options_returns_none(test_settings):
    parser = ParserService(test_settings)
    # Only 3 options
    text = "سؤال تجريبي؟\nأ) خيار 1\nب) خيار 2\nج) خيار 3\n"
    payload = parser.parse(text, job_id="job-incomplete")
    assert payload is None
