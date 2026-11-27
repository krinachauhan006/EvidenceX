"""S3-compatible storage adapter (app/storage/s3_store.py) and the storage factory.

No network and no real credentials: most tests use an in-memory fake S3 client; the
request-shape tests use botocore's Stubber on a real boto3 client, which intercepts
every call before it is sent.
"""

from __future__ import annotations

import hashlib
import io
import logging

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.stub import ANY, Stubber
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import EvidenceXError
from app.storage import factory, s3_store
from app.storage.local_store import LocalStorage
from app.storage.s3_store import (
    S3Storage,
    StorageConfigError,
    StorageUnavailableError,
)

BUCKET = "evidence-test"
SECRET = "test-secret-key-never-shown-42"
ACCESS = "test-access-key-id"
ENDPOINT = "https://project-ref.storage.supabase.co/storage/v1/s3"
DATA = b"id,note\n1,alpha\n"
SHA = hashlib.sha256(DATA).hexdigest()


def _client_error(code: str, op: str, status: int = 400) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "provider text"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        op,
    )


class FakeBody:
    def __init__(self, data: bytes, fail_read: bool = False) -> None:
        self._buf = io.BytesIO(data)
        self.closed = False
        self._fail = fail_read

    def read(self, size: int | None = None) -> bytes:
        if self._fail:
            raise ConnectionResetError("connection reset by peer")
        return self._buf.read() if size is None else self._buf.read(size)

    def close(self) -> None:
        self.closed = True


class FakeS3:
    """Just enough of the boto3 S3 client API, backed by a dict."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.calls: list[tuple[str, dict]] = []
        self.fail: dict[str, Exception] = {}
        self.bodies: list[FakeBody] = []
        self.fail_reads = False

    def _enter(self, op: str, kwargs: dict) -> None:
        self.calls.append((op, kwargs))
        if op in self.fail:
            raise self.fail[op]

    def head_object(self, **kw):  # noqa: ANN003, ANN201
        self._enter("head_object", kw)
        if (kw["Bucket"], kw["Key"]) not in self.objects:
            raise _client_error("404", "HeadObject", 404)
        return {"ContentLength": len(self.objects[(kw["Bucket"], kw["Key"])])}

    def put_object(self, **kw):  # noqa: ANN003, ANN201
        self._enter("put_object", kw)
        data = kw["Body"].read()
        assert len(data) == kw["ContentLength"]
        self.objects[(kw["Bucket"], kw["Key"])] = data
        return {}

    def get_object(self, **kw):  # noqa: ANN003, ANN201
        self._enter("get_object", kw)
        if (kw["Bucket"], kw["Key"]) not in self.objects:
            raise _client_error("NoSuchKey", "GetObject", 404)
        body = FakeBody(self.objects[(kw["Bucket"], kw["Key"])], self.fail_reads)
        self.bodies.append(body)
        return {"Body": body}

    def delete_object(self, **kw):  # noqa: ANN003, ANN201
        self._enter("delete_object", kw)
        self.objects.pop((kw["Bucket"], kw["Key"]), None)
        return {}

    def ops(self) -> list[str]:
        return [op for op, _ in self.calls]


@pytest.fixture
def fake() -> FakeS3:
    return FakeS3()


@pytest.fixture
def store(fake) -> S3Storage:
    return S3Storage(bucket=BUCKET, client=fake)


# --- round trip and key layout ----------------------------------------------------


def test_round_trip_put_exists_open_delete(store, fake):
    sha, size = store.put_stream(io.BytesIO(DATA))
    assert (sha, size) == (SHA, len(DATA))
    assert (BUCKET, f"{SHA[:2]}/{SHA[2:4]}/{SHA}") in fake.objects  # same layout as local
    assert store.exists(SHA) is True
    with store.open(SHA) as fh:
        assert fh.read() == DATA
    assert store.delete(SHA) is True
    assert store.exists(SHA) is False
    assert store.delete(SHA) is False  # already gone


def test_put_returns_the_hash(store):
    assert store.put(DATA) == SHA


def test_duplicate_content_is_uploaded_once(store, fake):
    store.put_stream(io.BytesIO(DATA))
    assert store.put_stream(io.BytesIO(DATA)) == (SHA, len(DATA))
    assert fake.ops().count("put_object") == 1


def test_large_streams_spill_to_disk_and_hash_correctly(store, fake, monkeypatch):
    monkeypatch.setattr(s3_store, "SPOOL_MEMORY_BYTES", 1024)  # force a temp file
    data = bytes(range(256)) * 20_000  # ~5 MB, several 1 MiB chunks
    sha, size = store.put_stream(io.BytesIO(data))
    assert sha == hashlib.sha256(data).hexdigest() and size == len(data)
    assert fake.objects[(BUCKET, S3Storage.key_for(sha))] == data


def test_upload_metadata_is_opaque(store, fake):
    store.put_stream(io.BytesIO(DATA))
    (put,) = [kw for op, kw in fake.calls if op == "put_object"]
    assert put["ContentType"] == "application/octet-stream"
    assert put["Bucket"] == BUCKET and put["ContentLength"] == len(DATA)


@pytest.mark.parametrize(
    "bad", ["../../etc/passwd", "ab/" + "c" * 61, "A" * 63, "g" * 64, "", SHA + "0"]
)
def test_invalid_hashes_are_rejected_before_any_request(store, fake, bad):
    for call in (store.exists, store.open, store.delete):
        with pytest.raises(ValueError):
            call(bad)
    assert fake.calls == []


def test_uppercase_hash_maps_to_the_same_key():
    assert S3Storage.key_for(SHA.upper()) == S3Storage.key_for(SHA)


# --- missing objects behave like missing local files ------------------------------


def test_missing_object(store, fake):
    assert store.exists(SHA) is False
    with pytest.raises(FileNotFoundError):
        store.open(SHA)
    assert store.delete(SHA) is False
    assert "delete_object" not in fake.ops()


@pytest.mark.parametrize("code", ["404", "NoSuchKey", "NotFound"])
def test_all_not_found_codes_mean_missing(store, fake, code):
    fake.fail["head_object"] = _client_error(code, "HeadObject", 404)
    assert store.exists(SHA) is False


# --- failures: generic, safe, and still OSError for best-effort cleanup -------------


def test_failed_upload_raises_a_generic_503_and_stores_nothing(store, fake, caplog):
    fake.fail["put_object"] = _client_error("AccessDenied", "PutObject", 403)
    with caplog.at_level(logging.WARNING), pytest.raises(StorageUnavailableError) as info:
        store.put_stream(io.BytesIO(DATA))
    exc = info.value
    assert isinstance(exc, EvidenceXError) and isinstance(exc, OSError)
    assert exc.status_code == 503
    assert exc.message == StorageUnavailableError.message
    assert "provider text" not in str(exc)
    assert fake.objects == {}
    assert "upload failed (AccessDenied)" in caplog.text
    assert "provider text" not in caplog.text


@pytest.mark.parametrize(
    "error",
    [
        _client_error("AccessDenied", "HeadObject", 403),
        _client_error("InternalError", "HeadObject", 500),
        EndpointConnectionError(endpoint_url=ENDPOINT),
    ],
    ids=["403", "500", "unreachable"],
)
def test_lookup_failures_are_not_reported_as_missing(store, fake, error, caplog):
    fake.fail["head_object"] = error
    with caplog.at_level(logging.WARNING), pytest.raises(StorageUnavailableError):
        store.exists(SHA)
    # The endpoint URL (part of the connection error's text) is never logged.
    assert ENDPOINT not in caplog.text


def test_download_and_delete_failures(store, fake):
    store.put_stream(io.BytesIO(DATA))
    fake.fail["get_object"] = _client_error("SlowDown", "GetObject", 503)
    with pytest.raises(StorageUnavailableError):
        store.open(SHA)
    fake.fail["delete_object"] = _client_error("AccessDenied", "DeleteObject", 403)
    with pytest.raises(OSError):  # caught by the service's best-effort delete
        store.delete(SHA)


# --- the returned stream ------------------------------------------------------------


def test_stream_reads_in_chunks_and_closes_once(store, fake):
    store.put_stream(io.BytesIO(DATA))
    fh = store.open(SHA)
    assert fh.read(4) + fh.read(4) + fh.read() == DATA
    assert fh.read(10) == b""
    fh.close()
    fh.close()  # the download route closes twice; must be harmless
    assert fake.bodies[0].closed is True
    with pytest.raises(ValueError):
        fh.read()


def test_stream_context_manager_closes_the_body(store, fake):
    store.put_stream(io.BytesIO(DATA))
    with store.open(SHA) as fh:
        fh.read(1)
    assert fake.bodies[0].closed is True


def test_stream_read_errors_become_storage_errors(store, fake):
    store.put_stream(io.BytesIO(DATA))
    fake.fail_reads = True
    with store.open(SHA) as fh, pytest.raises(StorageUnavailableError):
        fh.read()
    assert fake.bodies[0].closed is True


def test_path_for_is_not_available(store):
    with pytest.raises(NotImplementedError):
        store.path_for(SHA)


# --- configuration -----------------------------------------------------------------


def test_bucket_and_credentials_are_required():
    with pytest.raises(StorageConfigError, match="S3_BUCKET"):
        S3Storage(bucket="", access_key_id=ACCESS, secret_access_key=SECRET)
    with pytest.raises(StorageConfigError, match="S3_ACCESS_KEY_ID") as info:
        S3Storage(bucket=BUCKET, access_key_id=ACCESS, secret_access_key="")
    assert ACCESS not in str(info.value)


def test_repr_hides_client_and_credentials():
    s = S3Storage(
        bucket=BUCKET, endpoint_url=ENDPOINT, access_key_id=ACCESS, secret_access_key=SECRET
    )
    assert repr(s) == f"S3Storage(bucket={BUCKET!r})"


def test_real_client_is_path_style_with_relaxed_checksums():
    client = s3_store._build_client(
        endpoint_url=ENDPOINT, region="eu-central-1", access_key_id=ACCESS, secret_access_key=SECRET
    )
    assert client.meta.endpoint_url == ENDPOINT
    assert client.meta.region_name == "eu-central-1"
    assert client.meta.config.s3["addressing_style"] == "path"
    assert client.meta.config.signature_version == "s3v4"
    assert client.meta.config.request_checksum_calculation == "when_required"


def test_request_shapes_against_a_stubbed_real_client():
    client = s3_store._build_client(
        endpoint_url=ENDPOINT, region="eu-central-1", access_key_id=ACCESS, secret_access_key=SECRET
    )
    key = S3Storage.key_for(SHA)
    with Stubber(client) as stub:
        stub.add_client_error(
            "head_object",
            "404",
            http_status_code=404,
            expected_params={"Bucket": BUCKET, "Key": key},
        )
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": BUCKET,
                "Key": key,
                "Body": ANY,
                "ContentLength": len(DATA),
                "ContentType": "application/octet-stream",
            },
        )
        stub.add_response(
            "head_object", {"ContentLength": len(DATA)}, {"Bucket": BUCKET, "Key": key}
        )
        stub.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": key})
        store = S3Storage(bucket=BUCKET, client=client)
        assert store.put_stream(io.BytesIO(DATA)) == (SHA, len(DATA))
        assert store.delete(SHA) is True
        stub.assert_no_pending_responses()


# --- settings and factory -------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_factory_cache():
    factory.clear_storage_cache()
    yield
    factory.clear_storage_cache()


def _s3_settings(**extra) -> Settings:
    return Settings(
        STORAGE_BACKEND="s3",
        S3_BUCKET=BUCKET,
        S3_ENDPOINT_URL=ENDPOINT,
        S3_REGION="eu-central-1",
        S3_ACCESS_KEY_ID=ACCESS,
        S3_SECRET_ACCESS_KEY=SECRET,
        **extra,
    )


def test_local_storage_is_the_default(tmp_path):
    s = Settings(STORAGE_ROOT=str(tmp_path / "blobs"))
    assert s.storage_backend == "local"
    assert isinstance(factory.build_storage(s), LocalStorage)


def test_s3_backend_is_built_from_settings_and_reused():
    s = _s3_settings()
    a, b = factory.build_storage(s), factory.build_storage(s)
    assert isinstance(a, S3Storage) and a is b  # one client per configuration


def test_s3_backend_without_bucket_fails_clearly():
    with pytest.raises(StorageConfigError, match="S3_BUCKET"):
        factory.build_storage(Settings(STORAGE_BACKEND="s3"))


def test_unknown_backend_is_rejected_at_startup():
    with pytest.raises(ValidationError):
        Settings(STORAGE_BACKEND="ftp")


def test_settings_never_show_the_secret():
    s = _s3_settings()
    assert SECRET not in repr(s) and SECRET not in str(s.model_dump())
    assert s.s3_secret_access_key.get_secret_value() == SECRET
