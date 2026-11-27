"""The evidence service and processing runner use the configured storage backend, and
behave correctly on S3-compatible storage. A fake in-memory S3 client is used; nothing
leaves the machine and no credentials are needed."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.modules.cases.models import Case
from app.modules.evidence.models import Evidence
from app.modules.evidence.service import EvidenceService
from app.storage import factory, s3_store
from app.storage.local_store import LocalStorage
from app.storage.s3_store import S3Storage, StorageUnavailableError
from tests.unit.test_s3_storage import FakeS3, _client_error

CSV = b"id,note\n1,alpha\n2,beta\n"


@pytest.fixture
def fake(monkeypatch) -> FakeS3:
    client = FakeS3()
    monkeypatch.setattr(s3_store, "_build_client", lambda **_: client)
    factory.clear_storage_cache()
    yield client
    factory.clear_storage_cache()


@pytest.fixture
def s3_settings() -> Settings:
    return Settings(
        STORAGE_BACKEND="s3",
        S3_BUCKET="evidence",
        S3_ACCESS_KEY_ID="id",
        S3_SECRET_ACCESS_KEY="secret",
    )


@pytest.fixture
def case_id(db_session):
    case = Case(title="S3 storage case")
    db_session.add(case)
    db_session.commit()
    return case.id


def _upload(service, case_id, name="ledger.csv", data=CSV):
    import io

    return service.upload(case_id, filename=name, fileobj=io.BytesIO(data))


def test_service_uses_the_configured_s3_backend(db_session, fake, s3_settings, case_id):
    service = EvidenceService(db_session, settings=s3_settings)
    assert isinstance(service._storage, S3Storage)
    ev = _upload(service, case_id)
    assert ("evidence", S3Storage.key_for(ev.sha256)) in fake.objects
    data = service.open_file(case_id, ev.id)
    try:
        assert data.stream.read() == CSV and data.byte_size == len(CSV)
    finally:
        data.stream.close()
    service.delete(case_id, ev.id)
    assert fake.objects == {}


def test_a_missing_object_is_reported_as_not_found(db_session, fake, s3_settings, case_id):
    service = EvidenceService(db_session, settings=s3_settings)
    ev = _upload(service, case_id)
    fake.objects.clear()  # the object vanished from the bucket
    with pytest.raises(NotFoundError):
        service.open_file(case_id, ev.id)


def test_a_failed_upload_creates_no_evidence_record(db_session, fake, s3_settings, case_id):
    service = EvidenceService(db_session, settings=s3_settings)
    fake.fail["put_object"] = _client_error("AccessDenied", "PutObject", 403)
    with pytest.raises(StorageUnavailableError):
        _upload(service, case_id)
    assert db_session.query(Evidence).filter_by(case_id=case_id).count() == 0


def test_a_failed_blob_delete_does_not_block_deleting_the_record(
    db_session, fake, s3_settings, case_id
):
    service = EvidenceService(db_session, settings=s3_settings)
    ev = _upload(service, case_id)
    fake.fail["delete_object"] = _client_error("AccessDenied", "DeleteObject", 403)
    service.delete(case_id, ev.id)  # best effort, as with local storage
    assert db_session.get(Evidence, ev.id) is None


def test_default_settings_still_use_local_storage(db_session, tmp_path):
    service = EvidenceService(db_session, settings=Settings(STORAGE_ROOT=str(tmp_path / "b")))
    assert isinstance(service._storage, LocalStorage)


def test_the_processing_runner_uses_the_configured_backend(fake, s3_settings, monkeypatch):
    from app.modules.processing import runner as runner_module

    monkeypatch.setattr(runner_module, "get_settings", lambda: s3_settings)
    runner = runner_module.build_default_runner()
    assert isinstance(runner._storage, S3Storage)
