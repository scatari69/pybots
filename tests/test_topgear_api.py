from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main

EXPORT = (Path(__file__).parent / "fixtures" / "sample_export.simc").read_text()

captured = {}


async def _fake_run_simulation(job, req):
    captured["profile"] = req.profile
    job.status = main.JobStatus.DONE


@pytest.fixture
def client(monkeypatch):
    captured.clear()
    monkeypatch.setattr(main, "run_simulation", _fake_run_simulation)
    with TestClient(main.app) as test_client:
        yield test_client


def test_preview_lists_candidates(client):
    response = client.post("/api/topgear/preview", json={"profile": EXPORT})

    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert len(candidates) == 5
    assert candidates[0]["name"] == "Voidclaw Gauntlets"


def test_preview_empty_export(client):
    response = client.post("/api/topgear/preview", json={"profile": "warrior=X\nlevel=80"})
    assert response.json()["candidates"] == []


def test_topgear_run_builds_combined_profile(client):
    response = client.post("/api/topgear", json={"profile": EXPORT, "iterations": 100})

    assert response.status_code == 200
    assert "profileset." in captured["profile"]
    assert captured["profile"].startswith("# Vexatra")

    job_id = response.json()["job_id"]
    job = main.job_store.get(job_id)
    assert job.kind == "topgear"
    assert (job.dir / "topgear.json").exists()


def test_topgear_run_respects_selection(client):
    response = client.post(
        "/api/topgear", json={"profile": EXPORT, "iterations": 100, "selected": [0]}
    )

    assert response.status_code == 200
    ps_lines = [
        line for line in captured["profile"].splitlines() if line.startswith("profileset.")
    ]
    assert len(ps_lines) == 1
    assert "TG0_hands" in ps_lines[0]


def test_topgear_run_no_candidates_is_400(client):
    response = client.post("/api/topgear", json={"profile": "warrior=X\nlevel=80"})
    assert response.status_code == 400
