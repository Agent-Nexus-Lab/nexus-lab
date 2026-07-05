from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Profile(BaseModel):
    nickname: str = ""
    campus: Optional[str] = None
    identity: Optional[str] = None
    raw_preference_text: Optional[str] = None
    interest_tags: list[str] = Field(default_factory=list)
    preferred_campuses: list[str] = Field(default_factory=list)
    available_time: Optional[str] = None
    activity_style_tags: list[str] = Field(default_factory=list)
    excluded_tags: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)
    profile_summary: Optional[str] = None


class EventInput(BaseModel):
    event_id: Optional[str] = None
    source_file: Optional[str] = None
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    title: str
    summary: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None
    campus: Optional[str] = None
    organizer: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    evidence_text: Optional[str] = None


class PlanDayRequest(BaseModel):
    events: list[EventInput]
    profile: Profile
    request_text: str
    date_scope: str = "today"
    now: Optional[str] = None
    include_debug: bool = False
    enable_llm_rewrite: bool = False


class PlanItem(BaseModel):
    event_id: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None
    campus: Optional[str] = None
    organizer: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    source_url: Optional[str] = None
    reason_text: Optional[str] = None
    display_order: int = 0
    quality_score: float = 0.0


class CandidateDetail(BaseModel):
    event_id: Optional[str] = None
    title: Optional[str] = None
    score: float = 0.0
    components: dict[str, Any] = Field(default_factory=dict)
    matched_terms: list[str] = Field(default_factory=list)
    source_file: Optional[str] = None
    evidence_text: Optional[str] = None
    effective_end_time: Optional[str] = None
    end_time_estimated: bool = False


class RejectionRecord(BaseModel):
    event_id: str = ""
    title: str = ""
    reason: str = ""


class ScheduleConflictRecord(BaseModel):
    event_id: Optional[str] = None
    title: Optional[str] = None
    reason: str = ""


class CommuteMatrix(BaseModel):
    same_campus: int = 15
    handan_to_jiangwan: int = 30
    jiangwan_to_handan: int = 30
    handan_to_fenglin: int = 60
    fenglin_to_handan: int = 60
    unknown: int = 60


class CacheInfo(BaseModel):
    cache_hit: bool = False
    cache_type: str = "none"  # "none" | "plan_result" | "rewrite"
    plan_result_cache_hit: bool = False
    rewrite_cache_hit: bool = False
    redis_available: bool = False
    using_fallback: bool = False


class LlmRewriteInfo(BaseModel):
    model_config = {"protected_namespaces": ()}

    used_fallback: bool = False
    rewrite_error: Optional[str] = None
    timeout_seconds: Optional[float] = None
    model_name: Optional[str] = None
    prompt_version: Optional[str] = None


class DebugInfo(BaseModel):
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    rejections: list[RejectionRecord] = Field(default_factory=list)
    rejection_counts: dict[str, int] = Field(default_factory=dict)
    score_details: list[CandidateDetail] = Field(default_factory=list)
    schedule_skips: list[ScheduleConflictRecord] = Field(default_factory=list)
    selected_event_ids: list[Optional[str]] = Field(default_factory=list)
    commute_matrix: CommuteMatrix = Field(default_factory=CommuteMatrix)
    llm_error: Optional[str] = None
    llm_invalid_event_ids: list[str] = Field(default_factory=list)
    cache: Optional[CacheInfo] = None
    llm_rewrite: Optional[LlmRewriteInfo] = None
    timings_ms: Optional[dict[str, float]] = None


class PlanDayData(BaseModel):
    run_id: Optional[str] = None
    status: str = "completed"
    plan_id: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    date_scope: Optional[str] = None
    items: Optional[list[PlanItem]] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    error_message: Optional[str] = None
    debug: Optional[DebugInfo] = None


class PlanDayResponse(BaseModel):
    code: int = 0
    data: PlanDayData = Field(default_factory=PlanDayData)
    message: str = "ok"


class RewriteReason(BaseModel):
    event_id: str
    reason_text: str


class RewriteOutput(BaseModel):
    summary: str
    reasons: list[RewriteReason] = Field(default_factory=list)
