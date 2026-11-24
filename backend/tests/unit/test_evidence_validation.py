"""Unit tests for evidence validation and storage (no HTTP, no network, no AI)."""

from __future__ import annotations

import hashlib
import io

import pytest

from app.modules.evidence.validation import (
    SUPPORTED_EXTENSIONS,
    UnsupportedFileError,
    extension_of,
    resolve_and_validate,
)
from app.storage.local_store import LocalStorage, sha256_hex
from tests.fixtures.sample_files import SAMPLES

# --- extension parsing ----------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("a.pdf", ".pdf"),
        ("IMAGE.PNG", ".png"),
        ("archive.tar.gz", ".gz"),
        ("noext", ""),
        ("  spaced.JPG  ", ".jpg"),
    ],
)
def test_extension_of(name, expected):
    assert extension_of(name) == expected


# --- signature + modality resolution across all supported types -----------------


@pytest.mark.parametrize("ext", list(SAMPLES.keys()))
def test_supported_files_resolve(ext):
    filename, content, expected_type = SAMPLES[ext]
    resolved = resolve_and_validate(filename, content[:32])
    assert resolved.evidence_type == expected_type
    assert resolved.mime_type  # a concrete mime was assigned


def test_all_supported_extensions_have_samples():
    sample_exts = {f".{k}" for k in SAMPLES}
    assert set(SUPPORTED_EXTENSIONS) == sample_exts


# --- rejections -----------------------------------------------------------------


def test_unsupported_extension_rejected():
    with pytest.raises(UnsupportedFileError):
        resolve_and_validate("malware.exe", b"MZ\x90\x00")


def test_no_extension_rejected():
    with pytest.raises(UnsupportedFileError):
        resolve_and_validate("datafile", b"%PDF-1.7")


def test_signature_extension_mismatch_rejected():
    # Claims to be a PDF but the bytes are PNG.
    png = SAMPLES["png"][1]
    with pytest.raises(UnsupportedFileError):
        resolve_and_validate("fake.pdf", png[:32])


def test_disguised_executable_as_pdf_rejected():
    with pytest.raises(UnsupportedFileError):
        resolve_and_validate("evil.pdf", b"MZ\x90\x00\x03\x00\x00\x00")


# --- storage: sha256 correctness + stream round-trip ----------------------------


def test_sha256_hex_matches_hashlib():
    data = b"evidence bytes"
    assert sha256_hex(data) == hashlib.sha256(data).hexdigest()


def test_put_stream_hash_and_size(tmp_path):
    store = LocalStorage(tmp_path)
    data = SAMPLES["pdf"][1]
    content_hash, size = store.put_stream(io.BytesIO(data))
    assert content_hash == hashlib.sha256(data).hexdigest()
    assert size == len(data)
    assert store.exists(content_hash)


def test_put_stream_is_idempotent_for_duplicates(tmp_path):
    store = LocalStorage(tmp_path)
    data = SAMPLES["png"][1]
    h1, _ = store.put_stream(io.BytesIO(data))
    h2, _ = store.put_stream(io.BytesIO(data))
    assert h1 == h2  # same content -> same key, written once


def test_open_returns_original_bytes(tmp_path):
    store = LocalStorage(tmp_path)
    data = SAMPLES["wav"][1]
    content_hash, _ = store.put_stream(io.BytesIO(data))
    with store.open(content_hash) as fh:
        assert fh.read() == data


def test_delete_removes_blob(tmp_path):
    store = LocalStorage(tmp_path)
    content_hash, _ = store.put_stream(io.BytesIO(SAMPLES["mp3"][1]))
    assert store.delete(content_hash) is True
    assert store.exists(content_hash) is False
    # Deleting an absent blob is safe.
    assert store.delete(content_hash) is False


def test_path_for_rejects_traversal(tmp_path):
    store = LocalStorage(tmp_path)
    with pytest.raises(ValueError):
        store.path_for("../../etc/passwd")
    with pytest.raises(ValueError):
        store.path_for("not-a-hash")
