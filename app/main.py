import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from app.jobs import JobStatus, JobStore
from app.schemas import JobStatusResponse, SimulateRequest
from app.simc_runner import run_simulation

DATA_DIR = Path(os.environ.get("SIMCBOTS_DATA_DIR", "data"))
JOBS_DIR = DATA_DIR / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

job_store = JobStore(JOBS_DIR)

# Keep strong references to in-flight background tasks so they aren't
# garbage-collected mid-run (asyncio only holds a weak reference otherwise).
_background_tasks: set[asyncio.Task] = set()

app = FastAPI(title="simcbots")


def _report_url(job_id: str) -> str:
    return f"/reports/{job_id}/report.html"


def _job_response(job) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.id,
        status=job.status.value,
        error=job.error,
        report_url=_report_url(job.id) if job.status == JobStatus.DONE else None,
    )


@app.post("/api/simulate", response_model=JobStatusResponse)
async def simulate(req: SimulateRequest) -> JobStatusResponse:
    job = await job_store.create()

    task = asyncio.create_task(
        run_simulation(job, req.profile, req.iterations, req.fight_style)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return _job_response(job)


@app.get("/api/simulate/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str) -> JobStatusResponse:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_response(job)


app.mount("/reports", StaticFiles(directory=JOBS_DIR), name="reports")
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
