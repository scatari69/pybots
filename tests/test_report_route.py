import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main

SAMPLE_RESULTS = Path(__file__).parent / "fixtures" / "sample_results.json"


@pytest.fixture
def client():
    with TestClient(main.app) as test_client:
        yield test_client


async def test_report_pending_shows_status(client):
    job = await main.job_store.create()

    response = client.get(f"/report/{job.id}")

    assert response.status_code == 200
    assert "queued" in response.text


async def test_report_cancelled_shows_message(client):
    job = await main.job_store.create()
    job.status = main.JobStatus.CANCELLED

    response = client.get(f"/report/{job.id}")

    assert response.status_code == 200
    assert "cancelled" in response.text


async def test_report_error_shows_log_tail(client):
    job = await main.job_store.create()
    job.status = main.JobStatus.ERROR
    job.error = "simc exploded"

    response = client.get(f"/report/{job.id}")

    assert response.status_code == 200
    assert "simc exploded" in response.text


async def test_report_done_renders_summary(client):
    job = await main.job_store.create()
    job.dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(SAMPLE_RESULTS, job.dir / main.RESULTS_FILENAME)
    job.status = main.JobStatus.DONE

    response = client.get(f"/report/{job.id}")

    assert response.status_code == 200
    assert "3,698" in response.text
    assert "Fury Warrior" in response.text
    assert f"/reports/{job.id}/report.html" in response.text


def test_report_unknown_job_returns_404(client):
    response = client.get("/report/does-not-exist")
    assert response.status_code == 404
