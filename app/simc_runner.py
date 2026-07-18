import asyncio
import os

from app.jobs import Job, JobStatus

# The Docker image builds this from simulationcraftorg/simc:latest (see Dockerfile),
# but a plain "simc" on PATH works fine for local, non-Docker development too.
SIMC_BINARY = os.environ.get("SIMC_BINARY", "simc")

# Truncate stored error output so a runaway log can't blow up the job response.
MAX_ERROR_CHARS = 4000


async def run_simulation(
    job: Job,
    profile_text: str,
    iterations: int,
    fight_style: str,
    binary: str = SIMC_BINARY,
) -> None:
    """Write the profile to disk, shell out to simc, and update the job in place.

    Runs as a fire-and-forget asyncio task per job -- fine for a single-user,
    locally-hosted instance where a handful of sims run concurrently at most.
    """
    job.status = JobStatus.RUNNING
    job.dir.mkdir(parents=True, exist_ok=True)

    input_path = job.dir / "input.simc"
    input_path.write_text(profile_text)

    report_path = job.dir / "report.html"
    log_path = job.dir / "log.txt"

    args = [
        input_path.name,
        f"html={report_path.name}",
        f"iterations={iterations}",
        f"fight_style={fight_style}",
    ]

    with log_path.open("wb") as log_file:
        process = await asyncio.create_subprocess_exec(
            binary,
            *args,
            stdout=log_file,
            stderr=asyncio.subprocess.STDOUT,
            cwd=job.dir,
        )
        returncode = await process.wait()

    if returncode == 0:
        job.status = JobStatus.DONE
    else:
        job.status = JobStatus.ERROR
        job.error = log_path.read_text(errors="replace")[-MAX_ERROR_CHARS:]
