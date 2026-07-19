import time

import pytest
from fastapi.testclient import TestClient

from app import main


async def _fake_run_simulation(job, req):
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


def test_simulate_accepts_option_toggles(client):
    response = client.post(
        "/api/simulate",
        json={
            "profile": "x",
            "desired_targets": 4,
            "max_time": 120,
            "bloodlust": False,
            "raid_buffs": False,
            "consumables": False,
        },
    )
    assert response.status_code == 200


def test_unknown_job_returns_404(client):
    response = client.get("/api/simulate/does-not-exist")
    assert response.status_code == 404


async def test_cancel_running_job_terminates(client):
    job = await main.job_store.create()
    job.status = main.JobStatus.RUNNING

    terminated = []

    class FakeProcess:
        def terminate(self):
            terminated.append(True)

    job.process = FakeProcess()

    response = client.post(f"/api/simulate/{job.id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert terminated == [True]


async def test_cancel_finished_job_is_noop(client):
    job = await main.job_store.create()
    job.status = main.JobStatus.DONE

    response = client.post(f"/api/simulate/{job.id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "done"


def test_cancel_unknown_job_returns_404(client):
    response = client.post("/api/simulate/does-not-exist/cancel")
    assert response.status_code == 404
