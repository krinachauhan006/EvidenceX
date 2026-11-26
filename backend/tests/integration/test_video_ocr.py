"""Video processing, OCR language checks and the subprocess executor.

Videos are generated in memory with PyAV (tests/fixtures/video_samples.py). OCR and
speech engines are replaced with stand-ins; the real PyAV decoder is used for frames
and for the soundtrack. All data is synthetic.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from app.modules.evidence.validation import resolve_and_validate
from app.modules.processing.errors import (
    CorruptFileError,
    ExtractionError,
    ExtractionTimeoutError,
    LimitExceededError,
)
from app.modules.processing.executor import (
    InlineExecutor,
    SubprocessExecutor,
    build_executor,
)
from app.modules.processing.extractors import ocr_languages, video
from app.modules.processing.extractors.audio import AudioExtractor, FasterWhisperTranscriber
from app.modules.processing.extractors.base import ExtractionInput
from app.modules.processing.extractors.video import VideoExtractor, plan_probes
from app.modules.processing.limits import ExtractionLimits
from tests.fixtures.fake_engines import (
    CorruptExtractor,
    CrashingExtractor,
    EchoExtractor,
    FakeOcrEngine,
    FakeTranscriber,
    MissingOcrEngine,
    SleepyExtractor,
)
from tests.fixtures.video_samples import HEIGHT, WIDTH, make_video

WORDS = [
    ("GATE", 91.0, 30, 80, 40, 12, 1, 1, 1),
    ("LOG", 89.0, 75, 80, 30, 12, 1, 1, 1),
    ("10:30", 87.0, 110, 80, 40, 12, 1, 1, 1),
]


@pytest.fixture(scope="module")
def clip() -> bytes:
    return make_video(seconds=6.0, fps=5, change_at=3.0, audio=True)


@pytest.fixture(scope="module")
def silent_clip() -> bytes:
    return make_video(seconds=6.0, fps=5, change_at=3.0, audio=False)


def inp(data: bytes, **options) -> ExtractionInput:
    base = {"video_frame_interval_seconds": 100.0, "video_scene_threshold": 28.0}
    base.update(options)
    return ExtractionInput(
        data=data,
        filename="clip.mp4",
        mime_type="video/mp4",
        sha256="0" * 64,
        limits=ExtractionLimits(),
        options=base,
    )


def extractor(ocr=None) -> VideoExtractor:
    return VideoExtractor(ocr=ocr or FakeOcrEngine(WORDS), audio=AudioExtractor(FakeTranscriber()))


# --- metadata and sampling ------------------------------------------------------


def test_probe_reports_container_metadata(clip):
    meta = video.probe(clip)
    assert meta["duration_seconds"] == pytest.approx(6.0, abs=0.2)
    assert meta["frame_rate"] == pytest.approx(5.0)
    assert (meta["width"], meta["height"]) == (WIDTH, HEIGHT)
    assert meta["has_audio"] is True and meta["audio_codec"] == "aac"


def test_probe_rejects_undecodable_bytes():
    with pytest.raises(CorruptFileError):
        video.probe(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 200)


def test_probe_plan_never_decodes_every_frame():
    times, step = plan_probes(3600.0, 10.0)
    assert step >= 2.0 and len(times) <= 1800
    short, _ = plan_probes(0.0, 10.0)
    assert short == [0.0]


def test_frames_are_sampled_at_start_and_scene_change(clip):
    result = extractor().extract(inp(clip))
    frames = [s for s in result.segments if s.segment_type == "video_frame"]
    reasons = [f.data["sampling"] for f in frames]
    assert reasons[0] == "first_frame" and frames[0].locator.t == 0.0
    assert "scene_change" in reasons
    change = frames[reasons.index("scene_change")]
    assert 3.0 <= change.locator.t <= 4.5  # detected at the first probe after the cut
    assert result.metadata["sampled_frames"] == len(frames)
    assert result.metadata["frame_times"] == [f.locator.t for f in frames]
    assert any(w.code == "sampled_frames_only" for w in result.warnings)


def test_frame_text_becomes_anchored_ocr_lines(clip):
    result = extractor().extract(inp(clip))
    lines = [s for s in result.segments if s.segment_type == "video_ocr_line"]
    assert lines, "every sampled frame is OCR'd"
    first = lines[0]
    assert first.text == "GATE LOG 10:30"
    loc = first.locator
    assert loc.kind == "video" and loc.t == 0.0
    assert (loc.frame_width, loc.frame_height) == (WIDTH, HEIGHT)
    assert loc.bbox is not None and tuple(loc.bbox) == (30.0, 80.0, 150.0, 92.0)
    assert 0 < first.engine_confidence <= 1  # the engine's own score, kept separate


def test_soundtrack_goes_through_the_audio_pipeline(clip):
    result = extractor().extract(inp(clip))
    spoken = [s for s in result.segments if s.segment_type == "transcript_segment"]
    assert [s.text for s in spoken] == ["Synthetic first sentence.", "Synthetic second sentence."]
    assert result.metadata["transcript_segments"] == 2
    assert result.outcome == "ok"


def test_video_without_audio_reports_it(silent_clip):
    result = extractor().extract(inp(silent_clip))
    assert any(w.code == "no_audio_track" for w in result.warnings)
    assert not [s for s in result.segments if s.segment_type == "transcript_segment"]


def test_long_video_is_rejected_before_sampling(clip):
    with pytest.raises(LimitExceededError):
        extractor().extract(inp(clip, max_video_seconds=2))


def test_frame_limit_is_reported_as_partial(clip):
    result = extractor().extract(inp(clip, video_max_frames=1))
    assert result.metadata["sampled_frames"] == 1
    assert any(w.code == "frame_limit_reached" for w in result.warnings)
    assert result.outcome == "partial"


def test_missing_ocr_keeps_frames_and_warns(clip):
    result = extractor(MissingOcrEngine()).extract(inp(clip))
    assert any(w.code == "ocr_unavailable" for w in result.warnings)
    assert [s for s in result.segments if s.segment_type == "video_frame"]
    assert not [s for s in result.segments if s.segment_type == "video_ocr_line"]
    assert result.metadata["frame_ocr"] is False


def test_frame_at_decodes_the_requested_time(clip):
    early = video.frame_at(clip, 0.0)
    late = video.frame_at(clip, 4.0)
    assert early.size == (WIDTH, HEIGHT)
    assert early.getpixel((5, 5))[2] > 50  # dark-blue card
    assert min(late.getpixel((5, 5))) > 180  # light card after the cut
    small = video.frame_at(clip, 4.0, max_width=160)
    assert small.size == (160, 90)


# --- upload validation ----------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "mime"),
    [("a.mp4", "video/mp4"), ("a.mov", "video/quicktime"), ("a.webm", "video/webm")],
)
def test_video_signatures_are_checked(name, mime):
    from tests.fixtures.sample_files import SAMPLES

    _, content, _ = SAMPLES[name.rsplit(".", 1)[1]]
    resolved = resolve_and_validate(name, content[:64])
    assert (resolved.evidence_type, resolved.mime_type) == ("video", mime)


def test_video_extension_with_wrong_content_is_rejected():
    with pytest.raises(Exception):  # noqa: B017 - domain validation error
        resolve_and_validate("clip.mp4", b"%PDF-1.4 not a video at all")
    with pytest.raises(Exception):  # noqa: B017
        resolve_and_validate("clip.webm", b"\x00\x00\x00\x20ftypisom" + b"\x00" * 20)


# --- through the API ------------------------------------------------------------


class FakeWhisperModel:
    def transcribe(self, audio, **kwargs):
        seg = SimpleNamespace(
            start=0.5,
            end=2.0,
            text=" The truck reached the gate at 10:30.",
            avg_logprob=-0.3,
            no_speech_prob=0.02,
            compression_ratio=1.1,
        )
        return iter([seg]), SimpleNamespace(language="en", language_probability=0.97)


@pytest.fixture
def video_registry(registry):
    transcriber = FasterWhisperTranscriber()
    transcriber._model = lambda options: FakeWhisperModel()
    ex = VideoExtractor(ocr=FakeOcrEngine(WORDS), audio=AudioExtractor(transcriber))
    for mime in ("video/mp4", "video/quicktime", "video/webm"):
        registry.register(mime, ex)
    return registry


def make_case(client) -> str:
    return client.post("/api/cases", json={"title": "Video case", "description": None}).json()["id"]


def upload(client, case_id, name, content):
    return client.post(
        f"/api/cases/{case_id}/evidence",
        files={"file": (name, content, "application/octet-stream")},
    )


def test_video_upload_process_and_frame_endpoint(client, video_registry, clip):
    case_id = make_case(client)
    res = upload(client, case_id, "gate-camera.mp4", clip)
    assert res.status_code == 201, res.text
    ev = res.json()
    assert ev["evidence_type"] == "video" and ev["mime_type"] == "video/mp4"
    client.post(f"/api/cases/{case_id}/evidence/{ev['id']}/process", json={})
    state = client.get(f"/api/cases/{case_id}/evidence/{ev['id']}/processing").json()
    assert state["status"] == "completed", state
    assert state["current_extraction"]["extractor"] == "video"

    items = client.get(f"/api/cases/{case_id}/evidence/{ev['id']}/segments").json()["items"]
    kinds = {s["segment_type"] for s in items}
    assert {"video_frame", "video_ocr_line", "transcript_segment"} <= kinds
    ocr = next(s for s in items if s["segment_type"] == "video_ocr_line")
    assert ocr["locator"]["kind"] == "video" and ocr["locator"]["bbox"] is not None
    spoken = next(s for s in items if s["segment_type"] == "transcript_segment")
    assert (spoken["locator"]["start"], spoken["locator"]["end"]) == (0.5, 2.0)

    frame = client.get(f"/api/cases/{case_id}/evidence/{ev['id']}/frame", params={"t": 4.0})
    assert frame.status_code == 200 and frame.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(frame.content))
    assert img.size == (WIDTH, HEIGHT)
    assert frame.headers["x-content-type-options"] == "nosniff"


def test_frame_endpoint_refuses_non_video(client, video_registry):
    from tests.fixtures.sample_files import CSV_BYTES

    case_id = make_case(client)
    ev = upload(client, case_id, "ledger.csv", CSV_BYTES).json()
    r = client.get(f"/api/cases/{case_id}/evidence/{ev['id']}/frame", params={"t": 1})
    assert r.status_code == 400


def test_frame_endpoint_is_case_scoped(client, video_registry, clip):
    case_id = make_case(client)
    other = make_case(client)
    ev = upload(client, case_id, "clip.mp4", clip).json()
    r = client.get(f"/api/cases/{other}/evidence/{ev['id']}/frame", params={"t": 0})
    assert r.status_code == 404


def test_corrupt_video_fails_without_affecting_others(client, video_registry, clip):
    from tests.fixtures.sample_files import MP4_BYTES

    case_id = make_case(client)
    bad = upload(client, case_id, "bad.mp4", MP4_BYTES).json()
    good = upload(client, case_id, "good.mp4", clip).json()
    for ev in (bad, good):
        client.post(f"/api/cases/{case_id}/evidence/{ev['id']}/process", json={})
    bad_state = client.get(f"/api/cases/{case_id}/evidence/{bad['id']}/processing").json()
    good_state = client.get(f"/api/cases/{case_id}/evidence/{good['id']}/processing").json()
    assert bad_state["status"] == "failed" and bad_state["error_code"] == "corrupt_file"
    assert good_state["status"] == "completed"


def test_video_has_its_own_upload_limit(client, settings):
    settings.max_upload_size_mb = 1
    settings.max_video_upload_mb = 2
    case_id = make_case(client)
    head = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
    ok = upload(client, case_id, "big.mp4", head + b"\x00" * (1536 * 1024))
    assert ok.status_code == 201, ok.text  # 1.5 MB: above the general cap, under video's
    too_big = upload(client, case_id, "huge.mp4", head + b"\x00" * (2100 * 1024))
    assert too_big.status_code == 400 and "2 MB" in too_big.json()["detail"]
    from tests.fixtures.sample_files import CSV_BYTES

    csv = upload(client, case_id, "big.csv", CSV_BYTES * 20000)  # ~1.4 MB of text
    assert csv.status_code == 400


# --- OCR languages ----------------------------------------------------------------


def test_validate_languages_normalizes_and_reports_missing():
    value, missing = ocr_languages.validate_languages("eng,deu+eng", ["eng", "osd"])
    assert value == "eng+deu" and missing == ["deu"]
    assert ocr_languages.validate_languages("chi_sim", None) == ("chi_sim", ["chi_sim"])
    for bad in ("", "../eng", "eng;rm", "EN", "e"):
        with pytest.raises(ValueError):
            ocr_languages.validate_languages(bad, ["eng"])


def test_language_report_never_downloads(monkeypatch):
    monkeypatch.setattr(ocr_languages, "installed_languages", lambda cmd="": ["eng", "osd"])
    report = ocr_languages.language_report("", "eng")
    assert report["engine_available"] is True
    assert [i["code"] for i in report["installed"]] == ["eng", "osd"]
    assert report["installed"][1]["usable_for_text"] is False
    assert report["orientation_detection"] is True
    assert "never downloads" in report["install_help"]
    monkeypatch.setattr(ocr_languages, "installed_languages", lambda cmd="": None)
    assert ocr_languages.language_report("", "eng")["engine_available"] is False


def test_ocr_languages_endpoint(client, monkeypatch):
    monkeypatch.setattr(ocr_languages, "installed_languages", lambda cmd="": ["eng"])
    r = client.get("/api/ocr/languages")
    assert r.status_code == 200, r.text
    assert [i["code"] for i in r.json()["installed"]] == ["eng"]


# --- subprocess executor -----------------------------------------------------------


def exec_input(mime: str = "video/mp4") -> ExtractionInput:
    return ExtractionInput(
        data=b"synthetic",
        filename="x",
        mime_type=mime,
        sha256="0" * 64,
        limits=ExtractionLimits(),
        options={},
    )


def test_subprocess_executor_runs_isolated_formats_in_a_child():
    import os

    result = SubprocessExecutor(60).run(EchoExtractor(), exec_input())
    assert result.metadata["bytes"] == 9
    assert result.metadata["pid"] != os.getpid()


def test_subprocess_executor_keeps_other_formats_inline():
    import os

    result = SubprocessExecutor(60).run(EchoExtractor(), exec_input("text/csv"))
    assert result.metadata["pid"] == os.getpid()


def test_subprocess_executor_stops_a_hung_extractor():
    with pytest.raises(ExtractionTimeoutError) as info:
        SubprocessExecutor(3).run(SleepyExtractor(), exec_input())
    assert info.value.code == "timeout"


def test_subprocess_executor_relays_expected_errors_with_their_code():
    with pytest.raises(ExtractionError) as info:
        SubprocessExecutor(60).run(CorruptExtractor(), exec_input())
    assert info.value.code == "corrupt_file"
    assert info.value.message == "The synthetic file could not be read."


def test_subprocess_executor_reports_crashes_by_type_only():
    with pytest.raises(RuntimeError) as info:
        SubprocessExecutor(60).run(CrashingExtractor(), exec_input())
    assert "ValueError" in str(info.value) and "secret" not in str(info.value)


def test_build_executor_follows_settings():
    assert isinstance(
        build_executor(SimpleNamespace(processing_isolation="inline")), InlineExecutor
    )
    sub = build_executor(
        SimpleNamespace(processing_isolation="subprocess", processing_item_timeout_seconds=5)
    )
    assert isinstance(sub, SubprocessExecutor)


# --- gate: timestamps, audio sync, unsupported media ------------------------------------


class RecordingWhisper:
    """Stand-in speech model that keeps the decoded soundtrack it was given."""

    def __init__(self) -> None:
        self.audio = None

    def transcribe(self, audio, **kwargs):
        self.audio = audio
        seg = SimpleNamespace(
            start=2.0,
            end=3.0,
            text=" Tone heard.",
            avg_logprob=-0.2,
            no_speech_prob=0.01,
            compression_ratio=1.0,
        )
        return iter([seg]), SimpleNamespace(language="en", language_probability=0.9)


def test_sampled_frame_times_are_exact_media_times(clip):
    result = extractor().extract(inp(clip, video_frame_interval_seconds=1.0))
    frames = [s for s in result.segments if s.segment_type == "video_frame"]
    assert len(frames) >= 4
    for f in frames:
        t = f.locator.t
        assert 0.0 <= t < 6.0
        assert abs(t * 5 - round(t * 5)) < 1e-6  # a real frame boundary at 5 fps
        # The picture shown at the cited time is the picture that was sampled.
        pixel = video.frame_at(clip, t).getpixel((5, 5))
        expected_light = t >= 3.0
        assert (min(pixel) > 180) == expected_light, (t, pixel)
    times = [f.locator.t for f in frames]
    assert times == sorted(times) and len(set(times)) == len(times)


def test_soundtrack_is_decoded_on_the_same_timeline_as_the_frames():
    import numpy as np

    data = make_video(seconds=6.0, fps=5, change_at=3.0, audio=True, tone_window=(2.0, 3.0))
    model = RecordingWhisper()
    transcriber = FasterWhisperTranscriber()
    transcriber._model = lambda options: model
    ex = VideoExtractor(ocr=FakeOcrEngine(WORDS), audio=AudioExtractor(transcriber))
    result = ex.extract(inp(data))
    audio = model.audio
    assert isinstance(audio, np.ndarray) and audio.dtype == np.float32
    assert abs(len(audio) / 16000 - 6.0) < 0.15  # same length as the video
    loud = np.flatnonzero(np.abs(audio) > 0.05)
    start, end = loud[0] / 16000, loud[-1] / 16000
    assert abs(start - 2.0) < 0.1 and abs(end - 3.0) < 0.1, (start, end)
    (spoken,) = [s for s in result.segments if s.segment_type == "transcript_segment"]
    assert (spoken.locator.start, spoken.locator.end) == (2.0, 3.0)


def test_audio_only_mp4_is_reported_as_having_no_video():
    data = make_video(seconds=2.0, audio=True, video=False)
    with pytest.raises(CorruptFileError) as info:
        video.probe(data)
    assert "no video stream" in info.value.message


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("clip.avi", b"RIFF\x00\x00\x00\x00AVI LIST" + b"\x00" * 40),
        ("clip.mkv", b"\x1a\x45\xdf\xa3" + b"\x00" * 40),
        ("clip.flv", b"FLV\x01\x05" + b"\x00" * 40),
        ("clip.mp4", b"RIFF\x00\x00\x00\x00AVI LIST" + b"\x00" * 40),
        ("clip.webm", b"\x00\x00\x00\x20ftypisom" + b"\x00" * 40),
        ("clip.mov", b"%PDF-1.4" + b"\x00" * 40),
    ],
)
def test_unsupported_or_mislabelled_media_is_rejected_at_upload(client, name, content):
    case_id = make_case(client)
    r = upload(client, case_id, name, content)
    assert r.status_code == 400, (name, r.status_code, r.text)
    assert client.get(f"/api/cases/{case_id}/evidence").json()["total"] == 0


def test_audio_only_mp4_upload_fails_processing_cleanly(client, video_registry):
    case_id = make_case(client)
    ev = upload(client, case_id, "voice.mp4", make_video(seconds=2.0, video=False)).json()
    client.post(f"/api/cases/{case_id}/evidence/{ev['id']}/process", json={})
    state = client.get(f"/api/cases/{case_id}/evidence/{ev['id']}/processing").json()
    assert state["status"] == "failed" and state["error_code"] == "corrupt_file"
    assert state["error"] == "The file has no video stream."
