"""Deterministic transcription behaviour (fake model, real decoder, generated audio).

These tests pin what EvidenceX does with whatever the speech engine returns: text is kept
verbatim, no segment is dropped, timestamps stay inside the recording, engine word
probabilities are stored unchanged, and every configuration that biases recognition is
recorded. Real-model accuracy is measured separately in
``tests/benchmarks/bench_transcription_quality.py`` and is not part of this suite.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.modules.processing.errors import ModelUnavailableError
from app.modules.processing.extractors.audio import AudioExtractor, FasterWhisperTranscriber
from tests.fixtures.extraction import assert_locators_valid, run, warning_codes
from tests.fixtures.processing_samples import make_wav
from tests.unit.test_audio_decoding import OPTIONS, RecordingModel, transcriber_with


def seg(start, end, text, words=None, avg_logprob=-0.3, no_speech_prob=0.02):
    return SimpleNamespace(
        start=start,
        end=end,
        text=text,
        avg_logprob=avg_logprob,
        no_speech_prob=no_speech_prob,
        compression_ratio=1.2,
        words=words,
    )


def word(start, end, text, probability):
    return SimpleNamespace(start=start, end=end, word=text, probability=probability)


def extract(model, seconds=8.0, **options):
    return run(
        AudioExtractor(transcriber_with(model)),
        make_wav(seconds),
        mime="audio/wav",
        options={**OPTIONS, **options},
    )


# --- verbatim text for the three reference phrasings -----------------------------


def test_audio1_identifier_and_time_are_stored_exactly_as_recognized():
    text = "Driver assigned to shipment NS-88421; planned arrival 10:30."
    result = extract(RecordingModel(segments=[seg(0.0, 7.0, f" {text} ")]))
    assert result.segments[0].text == text


def test_audio1_misrecognized_identifier_is_not_silently_corrected():
    heard = "Driver assigned to ship maintenance 88,421, planned arrival 1030."
    result = extract(RecordingModel(segments=[seg(0.0, 7.0, heard)]))
    assert result.segments[0].text == heard  # no ID or time "repair" is applied


def test_audio2_opening_phrase_is_preserved():
    text = "A guard recalls the vehicle after noon, but may be referring to a second vehicle."
    result = extract(RecordingModel(segments=[seg(0.0, 5.2, text)]), seconds=5.6)
    assert result.segments[0].text.startswith("A guard recalls")
    assert "after noon" in result.segments[0].text


def test_audio3_opening_uncertainty_sentence_is_kept_as_its_own_segment():
    model = RecordingModel(
        segments=[
            # A doubtful first segment (low engine scores) must still be kept.
            seg(
                0.0,
                2.8,
                " I am not certain of the exact time.",
                avg_logprob=-1.4,
                no_speech_prob=0.6,
            ),
            seg(
                2.8,
                7.4,
                " This is my recollection, and the system should preserve that uncertainty.",
            ),
        ]
    )
    result = extract(model)
    texts = [s.text for s in result.segments]
    assert texts[0] == "I am not certain of the exact time."
    assert texts[1].startswith("This is my recollection")
    assert (result.segments[0].locator.start, result.segments[0].locator.end) == (0.0, 2.8)


# --- options reach the engine -----------------------------------------------------


@pytest.mark.parametrize("vad", [True, False])
def test_vad_setting_is_passed_through(vad):
    model = RecordingModel()
    extract(model, whisper_vad_filter=vad)
    assert model.calls[0]["vad_filter"] is vad


@pytest.mark.parametrize("enabled", [True, False])
def test_word_timestamps_setting_is_passed_through(enabled):
    model = RecordingModel()
    result = extract(model, whisper_word_timestamps=enabled)
    assert model.calls[0]["word_timestamps"] is enabled
    assert result.metadata["word_timestamps"] is enabled


# --- contextual prompt ------------------------------------------------------------


def test_no_prompt_is_sent_by_default_and_nothing_is_flagged():
    model = RecordingModel()
    result = extract(model)
    assert model.calls[0]["initial_prompt"] is None
    assert "initial_prompt_used" not in warning_codes(result)
    assert result.metadata["initial_prompt_used"] is False


def test_configured_prompt_is_sent_flagged_and_never_copied_into_the_transcript():
    prompt = "Shipment identifiers look like AB-12345."
    model = RecordingModel(segments=[seg(0.0, 2.0, " Driver assigned to shipment NS-88421.")])
    result = extract(model, whisper_initial_prompt=f"  {prompt}  ")
    assert model.calls[0]["initial_prompt"] == prompt
    assert "initial_prompt_used" in warning_codes(result)
    assert result.metadata["initial_prompt_used"] is True
    stored = " ".join(s.text for s in result.segments)
    assert "AB-12345" not in stored and "identifiers" not in stored


def test_whitespace_prompt_counts_as_no_prompt():
    model = RecordingModel()
    result = extract(model, whisper_initial_prompt="   ")
    assert model.calls[0]["initial_prompt"] is None
    assert result.metadata["initial_prompt_used"] is False


# --- timestamps -------------------------------------------------------------------


def test_segment_times_inside_the_recording_are_unchanged_and_not_flagged():
    result = extract(RecordingModel(segments=[seg(0.5, 2.25, "Inside.")]), seconds=3.0)
    assert (result.segments[0].locator.start, result.segments[0].locator.end) == (0.5, 2.25)
    assert "timestamps_clamped" not in warning_codes(result)


def test_segment_end_beyond_the_recording_is_limited_and_flagged():
    # The real base model produced an end of 9.12 s for a 7.165 s file.
    result = extract(RecordingModel(segments=[seg(0.0, 9.12, "Too long.")]), seconds=7.0)
    loc = result.segments[0].locator
    assert loc.end == pytest.approx(7.0)
    assert loc.start == 0.0
    detail = next(w.detail for w in result.warnings if w.code == "timestamps_clamped")
    assert detail["count"] == 1 and detail["duration_seconds"] == pytest.approx(7.0)
    assert_locators_valid(result)


def test_negative_start_is_limited_to_zero():
    result = extract(RecordingModel(segments=[seg(-0.4, 1.0, "Early.")]), seconds=2.0)
    assert result.segments[0].locator.start == 0.0
    assert "timestamps_clamped" in warning_codes(result)


def test_segments_stay_in_time_order():
    model = RecordingModel(
        segments=[seg(0.0, 1.0, "One."), seg(1.0, 2.5, "Two."), seg(2.5, 4.0, "Three.")]
    )
    spans = [(s.locator.start, s.locator.end) for s in extract(model, seconds=4.0).segments]
    assert spans == sorted(spans)
    assert all(start <= end for start, end in spans)


# --- word-level engine values -----------------------------------------------------


def test_words_are_stored_with_engine_probabilities_unchanged():
    words = [word(0.0, 0.3, " God", 0.132), word(0.3, 1.1, " recalls", 0.934)]
    result = extract(RecordingModel(segments=[seg(0.0, 1.1, " God recalls", words)]))
    stored = result.segments[0].data["words"]
    assert stored == [
        {"word": "God", "start": 0.0, "end": 0.3, "probability": 0.132},
        {"word": "recalls", "start": 0.3, "end": 1.1, "probability": 0.934},
    ]
    assert result.segments[0].text == "God recalls"  # the text itself is not changed


def test_low_probability_words_are_flagged_with_the_threshold():
    words = [word(0.0, 0.5, " served", 0.189), word(0.5, 0.9, " time.", 0.948)]
    result = extract(RecordingModel(segments=[seg(0.0, 0.9, " served time.", words)]))
    assert result.segments[0].data["low_probability_words"] == ["served"]
    detail = next(w.detail for w in result.warnings if w.code == "low_probability_words")
    assert detail == {"count": 1, "threshold": 0.5}
    assert result.metadata["low_word_probability_threshold"] == 0.5


def test_low_probability_threshold_is_configurable():
    words = [word(0.0, 0.5, " served", 0.189), word(0.5, 0.9, " time.", 0.948)]
    model = RecordingModel(segments=[seg(0.0, 0.9, " served time.", words)])
    result = extract(model, whisper_low_word_probability=0.1)
    assert result.segments[0].data["low_probability_words"] == []
    assert "low_probability_words" not in warning_codes(result)


def test_words_without_a_probability_are_not_flagged_or_given_one():
    words = [word(0.0, 0.5, " unknown", None)]
    result = extract(RecordingModel(segments=[seg(0.0, 0.5, " unknown", words)]))
    assert result.segments[0].data["words"][0]["probability"] is None
    assert result.segments[0].data["low_probability_words"] == []


def test_word_times_are_limited_to_the_recording_too():
    words = [word(1.5, 2.6, " late", 0.9)]
    result = extract(RecordingModel(segments=[seg(1.5, 2.0, " late", words)]), seconds=2.0)
    assert result.segments[0].data["words"][0]["end"] == pytest.approx(2.0)
    assert "timestamps_clamped" in warning_codes(result)


def test_no_word_data_when_the_engine_returns_none():
    result = extract(RecordingModel(segments=[seg(0.0, 1.0, " Plain.", None)]))
    assert "words" not in result.segments[0].data
    assert "low_probability_words" not in warning_codes(result)


# --- failures ---------------------------------------------------------------------


def test_missing_model_propagates_as_model_unavailable():
    def unavailable(options):
        raise ModelUnavailableError("The speech model 'base' is not available locally.")

    transcriber = FasterWhisperTranscriber()
    transcriber._model = unavailable
    with pytest.raises(ModelUnavailableError):
        run(AudioExtractor(transcriber), make_wav(0.5), mime="audio/wav", options=OPTIONS)


def test_no_speech_is_empty_with_a_warning_and_no_word_warnings():
    result = extract(RecordingModel(segments=[]), seconds=1.0)
    assert result.outcome == "empty"
    codes = warning_codes(result)
    assert "no_speech_detected" in codes
    assert "low_probability_words" not in codes and "timestamps_clamped" not in codes
