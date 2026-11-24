"""Real-model transcription quality benchmark. NOT part of the normal test run.

The file name does not start with ``test_``, so ``pytest`` does not collect it by default.
Run it explicitly, pointing at a folder that holds COPIES of the three reference
recordings (never the live evidence store):

    $env:EVIDENCEX_AUDIO_BENCHMARK_DIR = "D:\\path\\to\\copies"   # audio1.wav .. audio3.wav
    .\\.venv\\Scripts\\python.exe -m pytest tests/benchmarks/bench_transcription_quality.py -v

It needs the local speech model (``WHISPER_MODEL_DIR``) and never downloads anything.
Accuracy checks that the ``base`` model is known to fail are marked ``xfail`` with the
measured output, so a later model or setting that passes them shows up as XPASS.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app.core.config import Settings
from app.modules.processing.extractors.audio import AudioExtractor
from app.modules.processing.options import engine_options
from tests.fixtures.extraction import run

BENCH_DIR = os.environ.get("EVIDENCEX_AUDIO_BENCHMARK_DIR", "")

pytestmark = pytest.mark.skipif(
    not BENCH_DIR or not all((Path(BENCH_DIR) / f"audio{i}.wav").is_file() for i in (1, 2, 3)),
    reason="set EVIDENCEX_AUDIO_BENCHMARK_DIR to a folder with copies of audio1..3.wav",
)

EXPECTED = {
    1: "Driver assigned to shipment NS-88421; planned arrival 10:30.",
    2: "A guard recalls the vehicle after noon, but may be referring to a second vehicle.",
    3: "I am not certain of the exact time. This is my recollection, and the system "
    "should preserve that uncertainty.",
}


@pytest.fixture(scope="module")
def transcripts():
    extractor = AudioExtractor()
    options = engine_options(Settings())
    out = {}
    for i in (1, 2, 3):
        data = (Path(BENCH_DIR) / f"audio{i}.wav").read_bytes()
        out[i] = run(extractor, data, mime="audio/wav", options=options)
    return out


def text_of(result) -> str:
    return " ".join(s.text for s in result.segments)


@pytest.mark.parametrize("i", [1, 2, 3])
def test_timestamps_stay_inside_each_recording(transcripts, i):
    result = transcripts[i]
    duration = result.metadata["duration_seconds"]
    for s in result.segments:
        assert 0.0 <= s.locator.start <= s.locator.end <= duration + 1e-6


@pytest.mark.parametrize("i", [1, 2, 3])
def test_engine_word_probabilities_are_recorded(transcripts, i):
    words = [w for s in transcripts[i].segments for w in s.data.get("words", [])]
    assert words and all(0.0 <= w["probability"] <= 1.0 for w in words)


def test_audio3_keeps_its_first_sentence_as_a_segment(transcripts):
    # Measured with base: the first sentence is transcribed (misheard), not dropped.
    assert len(transcripts[3].segments) >= 2
    assert transcripts[3].segments[0].locator.start == 0.0


@pytest.mark.xfail(strict=False, reason="base model hears 'ship maintenance 88,421'")
def test_audio1_identifier(transcripts):
    assert re.search(r"\bNS-?88421\b", text_of(transcripts[1]), re.IGNORECASE)


@pytest.mark.xfail(strict=False, reason="base model hears 'God recalls' (word p=0.13)")
def test_audio2_opening_phrase(transcripts):
    assert text_of(transcripts[2]).lower().startswith("a guard recalls")


@pytest.mark.xfail(strict=False, reason="base model hears 'I am not served in the next time'")
def test_audio3_uncertainty_statement(transcripts):
    assert "not certain of the exact time" in text_of(transcripts[3]).lower()


@pytest.mark.parametrize("i", [1, 2, 3])
def test_misheard_words_are_flagged(transcripts, i):
    # Every misrecognition measured with base had an engine word probability < 0.3.
    assert "low_probability_words" in [w.code for w in transcripts[i].warnings]
