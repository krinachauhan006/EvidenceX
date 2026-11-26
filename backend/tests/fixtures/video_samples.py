"""Synthetic video files, generated in memory with PyAV (no external media).

The clip shows a dark-blue card with white text for the first half and a light
card with dark text for the second half, so a scene change happens at ``change_at``.
The optional soundtrack is a quiet tone (it carries no speech; tests replace the
speech model with a stand-in).
"""

from __future__ import annotations

import io
import math

WIDTH, HEIGHT = 320, 180


def _card(color: tuple[int, int, int], ink: tuple[int, int, int], text: str):  # noqa: ANN202
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (WIDTH, HEIGHT), color)
    draw = ImageDraw.Draw(img)
    draw.rectangle((20, 60, 300, 120), outline=ink, width=3)
    draw.text((30, 80), text, fill=ink)
    return img


def make_video(
    seconds: float = 6.0,
    fps: int = 5,
    change_at: float = 3.0,
    audio: bool = True,
    container: str = "mp4",
    tone_window: tuple[float, float] | None = None,
    video: bool = True,
) -> bytes:
    """``tone_window`` limits the tone to [start, end) seconds (silence elsewhere), so
    tests can check that decoded audio sits at the right place on the media timeline.
    ``video=False`` writes an audio-only file."""
    import av
    import numpy as np

    buf = io.BytesIO()
    with av.open(buf, mode="w", format=container) as out:
        codec = "mpeg4" if container in ("mp4", "mov") else "libvpx"
        vs = None
        if video:
            vs = out.add_stream(codec, rate=fps)
            vs.width, vs.height, vs.pix_fmt = WIDTH, HEIGHT, "yuv420p"
        a_stream = None
        if audio:
            a_stream = out.add_stream("aac" if container != "webm" else "libvorbis", rate=16000)
        first = _card((20, 30, 70), (255, 255, 255), "GATE LOG 10:30")
        second = _card((230, 230, 220), (10, 10, 10), "TRUCK KX-4471")
        for i in range(int(seconds * fps) if vs is not None else 0):
            img = first if i / fps < change_at else second
            frame = av.VideoFrame.from_image(img)
            frame.pts = i
            for packet in vs.encode(frame):
                out.mux(packet)
        if vs is not None:
            for packet in vs.encode():
                out.mux(packet)
        if a_stream is not None:
            rate, size = 16000, 1024
            total = int(seconds * rate)
            channels = a_stream.codec_context.layout.nb_channels
            for start in range(0, total, size):
                n = min(size, total - start)
                t = (np.arange(start, start + n) / rate).astype(np.float32)
                tone = (0.05 * np.sin(2 * math.pi * 440 * t)).astype(np.float32)
                if tone_window is not None:
                    lo, hi = tone_window
                    tone = np.where((t >= lo) & (t < hi), tone * 6, 0.0).astype(np.float32)
                samples = np.tile(tone, (channels, 1))
                frame = av.AudioFrame.from_ndarray(
                    samples, format="fltp", layout=a_stream.codec_context.layout.name
                )
                frame.sample_rate = rate
                frame.pts = start
                for packet in a_stream.encode(frame):
                    out.mux(packet)
            for packet in a_stream.encode():
                out.mux(packet)
    return buf.getvalue()
