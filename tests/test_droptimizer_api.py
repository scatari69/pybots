from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import droptimizer, main

EXPORT = (Path(__file__).parent / "fixtures" / "sample_export.simc").read_text()
CATALOG_PATH = Path(__file__).parent / "fixtures" / "sample_droptimizer_catalog.json"

captured = {}


async def _fake_run_simulation(job, req):
    captured["profile"] = req.profile
    job.status = main.JobStatus.DONE


@pytest.fixture
def client(monkeypatch):
    captured.clear()
    monkeypatch.setattr(main, "run_simulation", _fake_run_simulation)
    monkeypatch.setattr(droptimizer, "DEFAULT_CATALOG_PATH", CATALOG_PATH)
    with TestClient(main.app) as test_client:
        yield test_client


def test_preview_reports_class_and_category_counts(client):
    response = client.post("/api/droptimizer/preview", json={"profile": EXPORT})

    assert response.status_code == 200
    body = response.json()
    assert body["wow_class"] == "warrior"
    assert body["armor_type"] == "plate"
    assert body["season"] == "Test Season"
    categories = {c["category"]: c["count"] for c in body["by_category"]}
    assert categories == {"raid": 2, "world_boss": 1, "delve": 1}
    assert body["total_sources"] == 4


def test_droptimizer_run_builds_combined_profile(client):
    response = client.post("/api/droptimizer", json={"profile": EXPORT, "iterations": 100})

    assert response.status_code == 200
    assert "profileset." in captured["profile"]
    assert captured["profile"].startswith("# Vexatra")

    job_id = response.json()["job_id"]
    job = main.job_store.get(job_id)
    assert job.kind == "droptimizer"
    assert (job.dir / "droptimizer.json").exists()


def test_droptimizer_run_respects_category_filter(client):
    response = client.post(
        "/api/droptimizer",
        json={"profile": EXPORT, "iterations": 100, "categories": ["delve"]},
    )

    assert response.status_code == 200
    ps_lines = [
        line for line in captured["profile"].splitlines() if line.startswith("profileset.")
    ]
    # the delve trinket is a paired slot -> two profilesets.
    assert len(ps_lines) == 2


def test_droptimizer_run_no_matching_items_is_400(client):
    response = client.post(
        "/api/droptimizer",
        json={"profile": EXPORT, "iterations": 100, "categories": ["nonexistent"]},
    )
    assert response.status_code == 400
