"""QA BUG-04: identify uploads by their magic bytes, not by the MIME type the client declares."""
from __future__ import annotations

IMAGE_MSG = "This file is not a supported image. Please upload a PNG, JPEG or WebP screenshot."
AUDIO_MSG = "This file is not a supported audio recording."
EMPTY_MSG = "This file is empty. Please choose the screenshot again."


def sniff(data: bytes) -> str | None:
    """Return the real MIME type for the formats the app accepts, else None."""
    h = data[:16]
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if h.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "image/webp"
    if h[:4] == b"RIFF" and h[8:12] == b"WAVE":
        return "audio/wav"
    if h.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio/webm"
    if h.startswith(b"OggS"):
        return "audio/ogg"
    if h.startswith(b"fLaC"):
        return "audio/flac"
    if h[4:8] == b"ftyp":
        return "audio/mp4"
    if h.startswith(b"ID3") or (len(h) > 1 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0):
        return "audio/mpeg" if (h.startswith(b"ID3") or (h[1] & 0x06) != 0) else "audio/aac"
    if h.startswith(b"#!AMR"):
        return "audio/amr"
    return None


def is_image(data: bytes) -> bool:
    return (sniff(data) or "").startswith("image/")


def is_audio(data: bytes) -> bool:
    return (sniff(data) or "").startswith("audio/")
