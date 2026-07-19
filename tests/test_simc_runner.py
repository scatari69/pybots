from pathlib import Path

import pytest

from app.jobs import Job, JobStatus
from app.schemas import SimulateRequest
from app.simc_runner import LOG_FILENAME, build_args, read_progress, run_simulation

FAKE_SIMC = str(Path(__file__).parent / "fixtures" / "fake_simc.py")


def make_request(profile: str = "some profile text", **overrides) -> SimulateRequest:
    return SimulateRequest(profile=profile, iterations=100, **overrides)


@pytest.mark.asyncio
async def test_run_simulation_success_writes_report(tmp_path):
    job = Job(id="ok", dir=tmp_path / "ok")

    await run_simulation(job, make_request(), binary=FAKE_SIMC)

    assert job.status == JobStatus.DONE
    assert job.error is None
    assert job.process is None
    assert (job.dir / "report.html").exists()
    assert (job.dir / "input.simc").read_text() == "some profile text"


@pytest.mark.asyncio
async def test_run_simulation_nonzero_exit_marks_error(tmp_path):
    job = Job(id="bad", dir=tmp_path / "bad")

    await run_simulation(job, make_request("this profile is set to FAIL"), binary=FAKE_SIMC)

    assert job.status == JobStatus.ERROR
    assert "boom" in job.error
    assert not (job.dir / "report.html").exists()


@pytest.mark.asyncio
async def test_run_simulation_skips_already_cancelled_job(tmp_path):
    job = Job(id="cxl", dir=tmp_path / "cxl", status=JobStatus.CANCELLED)

    await run_simulation(job, make_request(), binary=FAKE_SIMC)

    assert job.status == JobStatus.CANCELLED
    assert not (tmp_path / "cxl").exists()


def test_build_args_defaults_include_options():
    args = build_args(make_request())

    assert "desired_targets=1" in args
    assert "max_time=300" in args
    assert "optimal_raid=0" not in args
    assert "override.bloodlust=0" not in args
    assert "flask=disabled" not in args


def test_build_args_toggles_off():
    args = build_args(
        make_request(bloodlust=False, raid_buffs=False, consumables=False, desired_targets=5)
    )

    assert "desired_targets=5" in args
    assert "optimal_raid=0" in args
    assert "override.bloodlust=0" in args
    assert "flask=disabled" in args
    assert "food=disabled" in args
    assert "potion=disabled" in args


def _job_with_log(tmp_path, content: str) -> Job:
    job = Job(id="log", dir=tmp_path)
    (tmp_path / LOG_FILENAME).write_text(content)
    return job


def test_read_progress_percent_takes_last_match(tmp_path):
    job = _job_with_log(tmp_path, "Generating Baseline: 10%\rGenerating Baseline: 42%")
    assert read_progress(job) == 42.0


def test_read_progress_fraction_form(tmp_path):
    job = _job_with_log(tmp_path, "Simulating: 250/1000")
    assert read_progress(job) == 25.0


def test_read_progress_no_log_or_no_match(tmp_path):
    assert read_progress(Job(id="none", dir=tmp_path / "missing")) is None
    assert read_progress(_job_with_log(tmp_path, "no numbers here")) is None
