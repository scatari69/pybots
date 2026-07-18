import pytest

from app.jobs import JobStatus, JobStore


@pytest.mark.asyncio
async def test_create_assigns_unique_ids_and_dirs(tmp_path):
    store = JobStore(tmp_path)

    job1 = await store.create()
    job2 = await store.create()

    assert job1.id != job2.id
    assert job1.status == JobStatus.QUEUED
    assert job1.dir == tmp_path / job1.id


@pytest.mark.asyncio
async def test_get_returns_created_job(tmp_path):
    store = JobStore(tmp_path)
    job = await store.create()

    assert store.get(job.id) is job


def test_get_unknown_id_returns_none(tmp_path):
    store = JobStore(tmp_path)
    assert store.get("does-not-exist") is None
