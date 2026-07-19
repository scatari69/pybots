import time

import pytest
from fastapi.testclient import TestClient

from app import main


async def _fake_run_simulation(job, profile, iterations, fight_style):
    job.status = main.JobStatus.DONE


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "run_simulation", _fake_run_simulation)
    with TestClient(main.app) as test_client:
        yield test_client


def test_simulate_then_poll_until_done(client):
    response = client.post("/api/simulate", json={"profile": "raid_events=/dummy"})
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    status = None
    for _ in range(50):
        status = client.get(f"/api/simulate/{job_id}").json()
        if status["status"] != "queued":
            break
        time.sleep(0.02)

    assert status["status"] == "done"
    assert status["report_url"] == f"/reports/{job_id}/report.html"
    assert status["summary_url"] == f"/report/{job_id}"


def test_unknown_job_returns_404(client):
    response = client.get("/api/simulate/does-not-exist")
    assert response.status_code == 404
