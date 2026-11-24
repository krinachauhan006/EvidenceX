"""Every format the upload accepts has an extractor, and nothing else is advertised."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.modules.evidence.validation import (
    SIGNATURE_PREFIX_LEN,
    SUPPORTED_EXTENSIONS,
    resolve_and_validate,
)
from app.modules.processing.options import engine_options
from app.modules.processing.registry import build_default_registry
from tests.fixtures.sample_files import SAMPLES


@pytest.mark.parametrize("ext", sorted(SAMPLES))
def test_every_accepted_extension_has_an_extractor(ext):
    filename, content, _ = SAMPLES[ext]
    resolved = resolve_and_validate(filename, content[:SIGNATURE_PREFIX_LEN])
    assert build_default_registry().supports(resolved.mime_type), ext


def test_supported_extensions_match_the_documented_set():
    assert set(SUPPORTED_EXTENSIONS) == {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".wav",
        ".mp3",
        ".m4a",
        ".csv",
        ".xlsx",
        ".eml",
    }


def test_registry_has_no_extractor_for_a_type_the_upload_rejects():
    accepted = set()
    for filename, content, _ in SAMPLES.values():
        accepted.add(resolve_and_validate(filename, content[:SIGNATURE_PREFIX_LEN]).mime_type)
    assert set(build_default_registry().mime_types()) == accepted


def test_pdf_can_be_switched_off_for_licensing_reasons():
    registry = build_default_registry(Settings(PDF_EXTRACTION_ENABLED=False))
    assert not registry.supports("application/pdf")
    assert registry.supports("text/csv")
    assert build_default_registry(Settings()).supports("application/pdf")


def test_engine_options_come_from_settings():
    options = engine_options(Settings(TESSERACT_LANGS="eng+deu", WHISPER_MODEL_SIZE="small"))
    assert options["tesseract_langs"] == "eng+deu"
    assert options["whisper_model_size"] == "small"
    assert options["whisper_allow_download"] is False  # never implicit


def test_unregister_removes_a_type():
    registry = build_default_registry()
    registry.unregister("image/png")
    assert not registry.supports("image/png")
    registry.unregister("image/png")  # removing twice is harmless
