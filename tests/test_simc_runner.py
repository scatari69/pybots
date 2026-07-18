from pathlib import Path

import pytest

from app.jobs import Job, JobStatus
from app.simc_runner import run_simulation

FAKE_SIMC = str(Path(__file__).parent / "fixtures" / "fake_simc.py")


@pytest.mark.asyncio
async def test_run_simulation_success_writes_report(tmp_path):
    job = Job(id="ok", dir=tmp_path / "ok")

    await run_simulation(job, "some profile text", 100, "Patchwerk", binary=FAKE_SIMC)

    assert job.status == JobStatus.DONE
    assert job.error is None
    assert (job.dir / "report.html").exists()
    assert (job.dir / "input.simc").read_text() == "some profile text"


@pytest.mark.asyncio
async def test_run_simulation_nonzero_exit_marks_error(tmp_path):
    job = Job(id="bad", dir=tmp_path / "bad")

    await run_simulation(job, "this profile is set to FAIL", 100, "Patchwerk", binary=FAKE_SIMC)

    assert job.status == JobStatus.ERROR
    assert "boom" in job.error
    assert not (job.dir / "report.html").exists()
