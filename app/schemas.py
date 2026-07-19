from pydantic import BaseModel, Field


class SimulateRequest(BaseModel):
    profile: str = Field(..., description="Raw simc profile/APL text to simulate")
    iterations: int = 10000
    fight_style: str = "Patchwerk"


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    error: str | None = None
    report_url: str | None = None
    summary_url: str | None = None
