import asyncio
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import topgear
from app.gear_parser import parse_candidates
from app.jobs import JobStatus, JobStore
from app.report_parser import parse_profilesets, parse_report
from app.schemas import (
    CandidateOut,
    JobStatusResponse,
    SimulateRequest,
    TopGearPreviewRequest,
    TopGearPreviewResponse,
    TopGearRequest,
)
from app.simc_runner import (
    REPORT_FILENAME,
    RESULTS_FILENAME,
    read_progress,
    run_simulation,
)

DATA_DIR = Path(os.environ.get("SIMCBOTS_DATA_DIR", "data"))
JOBS_DIR = DATA_DIR / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

job_store = JobStore(JOBS_DIR)
templates = Jinja2Templates(directory="app/templates")

# Keep strong references to in-flight background tasks so they aren't
# garbage-collected mid-run (asyncio only holds a weak reference otherwise).
_background_tasks: set[asyncio.Task] = set()

app = FastAPI(title="simcbots")


def _raw_report_url(job_id: str) -> str:
    return f"/reports/{job_id}/{REPORT_FILENAME}"


def _summary_url(job_id: str) -> str:
    return f"/report/{job_id}"


def _job_response(job) -> JobStatusResponse:
    running = job.status == JobStatus.RUNNING
    return JobStatusResponse(
        job_id=job.id,
        status=job.status.value,
        error=job.error,
        report_url=_raw_report_url(job.id) if job.status == JobStatus.DONE else None,
        summary_url=_summary_url(job.id) if job.status == JobStatus.DONE else None,
        progress=read_progress(job) if running else None,
        elapsed=(time.time() - job.started_at) if running and job.started_at else None,
    )


@app.post("/api/simulate", response_model=JobStatusResponse)
async def simulate(req: SimulateRequest) -> JobStatusResponse:
    job = await job_store.create()

    task = asyncio.create_task(run_simulation(job, req))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return _job_response(job)


@app.post("/api/topgear/preview", response_model=TopGearPreviewResponse)
async def topgear_preview(req: TopGearPreviewRequest) -> TopGearPreviewResponse:
    candidates = parse_candidates(req.profile)
    return TopGearPreviewResponse(
        candidates=[
            CandidateOut(
                index=c.index, slot=c.slot, name=c.name, ilevel=c.ilevel, source=c.source
            )
            for c in candidates
        ]
    )


@app.post("/api/topgear", response_model=JobStatusResponse)
async def topgear_run(req: TopGearRequest) -> JobStatusResponse:
    candidates = parse_candidates(req.profile)
    if req.selected is not None:
        wanted = set(req.selected)
        candidates = [c for c in candidates if c.index in wanted]
    if not candidates:
        raise HTTPException(
            status_code=400,
            detail="no gear candidates found — paste a /simc export that includes "
            "'### Gear from Bags' or '### Weekly Reward Choices' sections",
        )

    combined_profile, meta = topgear.build_input(req.profile, candidates)
    job = await job_store.create(kind="topgear")
    topgear.save_meta(job.dir, meta)

    sim_options = req.model_dump(exclude={"selected"}) | {"profile": combined_profile}
    sim_req = SimulateRequest(**sim_options)
    task = asyncio.create_task(run_simulation(job, sim_req))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return _job_response(job)


@app.get("/api/simulate/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str) -> JobStatusResponse:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_response(job)


@app.post("/api/simulate/{job_id}/cancel", response_model=JobStatusResponse)
async def cancel_job(job_id: str) -> JobStatusResponse:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
        # Order matters: run_simulation checks for CANCELLED after the process
        # exits, so the status must be set before the terminate signal lands.
        job.status = JobStatus.CANCELLED
        if job.process is not None:
            job.process.terminate()

    return _job_response(job)


@app.get("/report/{job_id}", response_class=HTMLResponse)
async def report_page(request: Request, job_id: str):
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
        return templates.TemplateResponse(
            request, "report_pending.html", {"status": job.status.value}
        )
    if job.status == JobStatus.CANCELLED:
        return templates.TemplateResponse(
            request, "report_error.html", {"title": "Simulation was cancelled.", "error": None}
        )
    if job.status == JobStatus.ERROR:
        return templates.TemplateResponse(request, "report_error.html", {"error": job.error})

    if job.kind == "topgear":
        results = parse_profilesets(job.dir / RESULTS_FILENAME)
        summary = topgear.summarize(results, topgear.load_meta(job.dir))
        return templates.TemplateResponse(
            request,
            "topgear.html",
            {"summary": summary, "raw_report_url": _raw_report_url(job.id)},
        )

    summary = parse_report(job.dir / RESULTS_FILENAME)
    return templates.TemplateResponse(
        request,
        "report.html",
        {"summary": summary, "raw_report_url": _raw_report_url(job.id)},
    )


app.mount("/reports", StaticFiles(directory=JOBS_DIR), name="reports")
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
