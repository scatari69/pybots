import asyncio
import os
import re
import time

from app.jobs import Job, JobStatus
from app.schemas import SimulateRequest

# The Docker image builds this from simulationcraftorg/simc:latest (see Dockerfile),
# but a plain "simc" on PATH works fine for local, non-Docker development too.
SIMC_BINARY = os.environ.get("SIMC_BINARY", "simc")

# Truncate stored error output so a runaway log can't blow up the job response.
MAX_ERROR_CHARS = 4000

REPORT_FILENAME = "report.html"
RESULTS_FILENAME = "results.json"
LOG_FILENAME = "log.txt"

# simc rewrites its progress line with \r, e.g. "Generating Baseline: 42%" or
# "Simulating: 1234/10000"; both percent and N/M forms are matched.
_PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)%")
_FRACTION_RE = re.compile(r"(\d+)/(\d+)")


def build_args(req: SimulateRequest) -> list[str]:
    """CLI options placed after the input file override anything the profile set."""
    args = [
        "input.simc",
        f"html={REPORT_FILENAME}",
        f"json2={RESULTS_FILENAME}",
        f"iterations={req.iterations}",
        f"fight_style={req.fight_style}",
        f"desired_targets={req.desired_targets}",
        f"max_time={req.max_time}",
    ]
    if not req.raid_buffs:
        args.append("optimal_raid=0")
    if not req.bloodlust:
        args.append("override.bloodlust=0")
    if not req.consumables:
        args += [
            "flask=disabled",
            "food=disabled",
            "potion=disabled",
            "augmentation=disabled",
            "temporary_enchant=disabled",
        ]
    return args


def read_progress(job: Job) -> float | None:
    """Best-effort percent-complete, scraped from the tail of simc's log output."""
    log_path = job.dir / LOG_FILENAME
    try:
        with log_path.open("rb") as log_file:
            log_file.seek(0, os.SEEK_END)
            size = log_file.tell()
            log_file.seek(max(0, size - 4096))
            tail = log_file.read().decode(errors="replace")
    except OSError:
        return None

    # \r-rewritten progress lines all land in the file; only the last one matters.
    tail = tail.replace("\r", "\n")

    percent_matches = _PERCENT_RE.findall(tail)
    if percent_matches:
        return min(100.0, float(percent_matches[-1]))

    fraction_matches = _FRACTION_RE.findall(tail)
    if fraction_matches:
        current, total = fraction_matches[-1]
        if int(total) > 0:
            return min(100.0, int(current) / int(total) * 100)

    return None


async def run_simulation(job: Job, req: SimulateRequest, binary: str = SIMC_BINARY) -> None:
    """Write the profile to disk, shell out to simc, and update the job in place.

    Runs as a fire-and-forget asyncio task per job -- fine for a single-user,
    locally-hosted instance where a handful of sims run concurrently at most.
    """
    if job.status == JobStatus.CANCELLED:
        return

    job.status = JobStatus.RUNNING
    job.started_at = time.time()
    job.dir.mkdir(parents=True, exist_ok=True)

    input_path = job.dir / "input.simc"
    input_path.write_text(req.profile)

    log_path = job.dir / LOG_FILENAME

    with log_path.open("wb") as log_file:
        process = await asyncio.create_subprocess_exec(
            binary,
            *build_args(req),
            stdout=log_file,
            stderr=asyncio.subprocess.STDOUT,
            cwd=job.dir,
        )
        job.process = process
        returncode = await process.wait()
    job.process = None

    # The cancel endpoint sets CANCELLED before terminating the process; the
    # resulting nonzero exit must not be reported as an error.
    if job.status == JobStatus.CANCELLED:
        return

    if returncode == 0:
        job.status = JobStatus.DONE
    else:
        job.status = JobStatus.ERROR
        job.error = log_path.read_text(errors="replace")[-MAX_ERROR_CHARS:]
