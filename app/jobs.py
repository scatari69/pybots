import asyncio
import enum
import uuid
from dataclasses import dataclass
from pathlib import Path


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id: str
    dir: Path
    status: JobStatus = JobStatus.QUEUED
    error: str | None = None
    kind: str = "quick"  # "quick" | "topgear" — selects the report page renderer
    # Live subprocess handle while RUNNING; lets the cancel endpoint terminate it.
    process: asyncio.subprocess.Process | None = None
    started_at: float | None = None


class JobStore:
    """In-memory job registry. State is lost on process restart, which is fine
    for a single-user, locally-hosted instance."""

    def __init__(self, jobs_root: Path):
        self._jobs_root = jobs_root
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    async def create(self, kind: str = "quick") -> Job:
        job_id = uuid.uuid4().hex
        job = Job(id=job_id, dir=self._jobs_root / job_id, kind=kind)
        async with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)
