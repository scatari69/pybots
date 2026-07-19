from pydantic import BaseModel, Field


class SimulateRequest(BaseModel):
    profile: str = Field(..., description="Raw simc profile/APL text to simulate")
    iterations: int = Field(10000, ge=1, le=100000)
    fight_style: str = "Patchwerk"
    desired_targets: int = Field(1, ge=1, le=20, description="Number of training dummies")
    max_time: int = Field(300, ge=10, le=1800, description="Fight length in seconds")
    bloodlust: bool = True
    raid_buffs: bool = True
    consumables: bool = True


class TopGearRequest(SimulateRequest):
    # Indices into the parsed candidate list (see /api/topgear/preview);
    # omitted or null means "sim everything found".
    selected: list[int] | None = None


class CandidateOut(BaseModel):
    index: int
    slot: str
    name: str
    ilevel: int | None
    source: str


class TopGearPreviewRequest(BaseModel):
    profile: str


class TopGearPreviewResponse(BaseModel):
    candidates: list[CandidateOut]


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    error: str | None = None
    report_url: str | None = None
    summary_url: str | None = None
    progress: float | None = Field(None, description="Percent complete while running, if known")
    elapsed: float | None = Field(None, description="Seconds since the sim started running")
