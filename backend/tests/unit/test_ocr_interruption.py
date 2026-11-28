"""An OCR engine process stopped from outside (Ctrl+C, console closed) is an
interruption, never a verdict on the file.

On Windows, Ctrl+C reaches every process attached to the console, including the
``tesseract`` child of an inline OCR run. Here a fake ``pytesseract`` runs a REAL child
process that ends the way an interrupted tesseract does (STATUS_CONTROL_C_EXIT on
Windows, death by SIGINT elsewhere). No real Tesseract and no real process of anyone
else is interrupted.
"""

from __future__ import annotations

import subprocess
import sys
import types

import pytest

from app.modules.processing.errors import (
    INTERRUPTED,
    DependencyMissingError,
    ExtractionInterruptedError,
    UnsupportedContentError,
)
from app.modules.processing.extractors.ocr_engine import (
    TesseractEngine,
    is_interrupted_status,
)

# Ends this child exactly like an interrupted tesseract process.
_INTERRUPTED_CHILD = (
    "import os, signal\n"
    "if os.name == 'nt':\n"
    "    os._exit(-1073741510)  # 0xC000013A STATUS_CONTROL_C_EXIT\n"
    "signal.signal(signal.SIGINT, signal.SIG_DFL)\n"
    "os.kill(os.getpid(), signal.SIGINT)\n"
)
_FAILING_CHILD = "import sys; sys.exit(1)"


def _fake_pytesseract(child_code: str, message: str = "") -> types.ModuleType:
    """A pytesseract stand-in that, like the real one, runs a subprocess and raises
    ``TesseractError(returncode, message)`` when it exits non-zero."""
    mod = types.ModuleType("pytesseract")

    class TesseractError(RuntimeError):  # the real one is a RuntimeError subclass too
        def __init__(self, status: int, msg: str) -> None:
            super().__init__(status, msg)
            self.status = status
            self.message = msg

    class TesseractNotFoundError(OSError):
        pass

    def image_to_data(image, lang="eng", output_type=None, timeout=0):  # noqa: ANN001, ANN202
        proc = subprocess.run([sys.executable, "-c", child_code], capture_output=True)
        if proc.returncode:
            raise TesseractError(proc.returncode, message)
        return {"text": []}

    mod.TesseractError = TesseractError
    mod.TesseractNotFoundError = TesseractNotFoundError
    mod.Output = types.SimpleNamespace(DICT="dict")
    mod.image_to_data = image_to_data
    mod.get_tesseract_version = lambda: "5.0-fake"
    mod.pytesseract = types.SimpleNamespace(tesseract_cmd="")
    return mod


@pytest.fixture
def fake_tesseract_cmd(tmp_path) -> str:
    exe = tmp_path / "tesseract.exe"
    exe.write_bytes(b"")  # only has to exist; the fake module never runs it
    return str(exe)


def _recognize(monkeypatch, cmd: str, child: str, message: str = ""):  # noqa: ANN001, ANN202
    monkeypatch.setitem(sys.modules, "pytesseract", _fake_pytesseract(child, message))
    return TesseractEngine().recognize(object(), {"tesseract_cmd": cmd, "tesseract_langs": "eng"})


def test_the_interrupted_exit_statuses_are_recognised():
    assert is_interrupted_status(0xC000013A)
    assert is_interrupted_status(-1073741510)
    assert is_interrupted_status(-2)
    assert not is_interrupted_status(1)
    assert not is_interrupted_status(None)


def test_an_interrupted_ocr_subprocess_is_reported_as_interrupted(monkeypatch, fake_tesseract_cmd):
    with pytest.raises(ExtractionInterruptedError) as info:
        _recognize(monkeypatch, fake_tesseract_cmd, _INTERRUPTED_CHILD)
    assert info.value.code == INTERRUPTED
    assert not isinstance(info.value, UnsupportedContentError)


def test_a_real_ocr_failure_is_still_unsupported_content(monkeypatch, fake_tesseract_cmd):
    # TesseractError subclasses RuntimeError; it must not be swallowed by the
    # timeout handler (which used to re-raise it as an unexpected crash).
    with pytest.raises(UnsupportedContentError):
        _recognize(monkeypatch, fake_tesseract_cmd, _FAILING_CHILD, "Error in pixReadMem")


def test_missing_language_data_is_a_dependency_problem(monkeypatch, fake_tesseract_cmd):
    with pytest.raises(DependencyMissingError, match="language data"):
        _recognize(
            monkeypatch,
            fake_tesseract_cmd,
            _FAILING_CHILD,
            "Failed loading language 'hin'. Tesseract couldn't load any languages!",
        )


class _InterruptedEngine:
    name = "interrupted-ocr"

    def version(self, options):  # noqa: ANN001, ANN201
        return "fake"

    def recognize(self, image, options):  # noqa: ANN001, ANN201
        raise ExtractionInterruptedError("OCR was interrupted.")


def test_an_interrupted_pdf_page_fails_the_run_instead_of_saving_a_partial_one():
    pytest.importorskip("pymupdf")
    from app.modules.processing.extractors.pdf import PdfExtractor
    from tests.fixtures.extraction import run
    from tests.fixtures.processing_samples import make_pdf_scanned

    with pytest.raises(ExtractionInterruptedError):
        run(PdfExtractor(_InterruptedEngine()), make_pdf_scanned(), mime="application/pdf")
