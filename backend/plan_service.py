from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_RUNTIME_DIR = Path(__file__).resolve().parents[1] / "experiments" / "agent_plan_runtime"
if str(_RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_DIR))

import experiments.agent_plan_runtime.runtime as _rt
import experiments.agent_plan_runtime.llm as _llm
from backend.schemas import (
    CandidateDetail,
    DebugInfo,
    PlanDayResponse,
    RejectionRecord,
    RewriteOutput,
    ScheduleConflictRecord,
)

_COMMUTE_MATRIX_KEY_MAP = {
    "same_campus": "same_campus",
    "邯郸->江湾": "handan_to_jiangwan",
    "江湾->邯郸": "jiangwan_to_handan",
    "邯郸->枫林": "handan_to_fenglin",
    "枫林->邯郸": "fenglin_to_handan",
    "unknown_cross_campus": "unknown",
}


def _events_to_dicts(events) -> list[dict[str, Any]]:
    result = []
    for e in events:
        if hasattr(e, "model_dump"):
            result.append(e.model_dump(exclude_none=True))
        elif isinstance(e, dict):
            result.append(dict(e))
        else:
            result.append({"title": str(e)})
    return result


def _profile_to_dict(profile) -> dict[str, Any]:
    if hasattr(profile, "model_dump"):
        return profile.model_dump(exclude_none=True)
    if isinstance(profile, dict):
        return dict(profile)
    return {}


def _plan_day_to_response(result: dict[str, Any]) -> PlanDayResponse:
    raw_data = result.get("data") or {}
    raw_debug = raw_data.get("debug") if isinstance(raw_data, dict) else None

    items = raw_data.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                item.setdefault("reason_text", item.get("reason_text") or "")
                item.setdefault("display_order", item.get("display_order") or 0)
                item.setdefault("quality_score", item.get("quality_score") or 0.0)

    debug = None
    if raw_debug:
        debug = DebugInfo(
            window_start=raw_debug.get("window_start"),
            window_end=raw_debug.get("window_end"),
            rejections=[
                RejectionRecord(
                    event_id=str(r.get("event_id", "")),
                    title=str(r.get("title", "")),
                    reason=str(r.get("reason", "")),
                )
                for r in raw_debug.get("rejections", [])
            ],
            rejection_counts=raw_debug.get("rejection_counts", {}),
            score_details=[
                CandidateDetail(
                    event_id=c.get("event_id"),
                    title=c.get("title"),
                    score=c.get("score", 0.0),
                    components=c.get("components", {}),
                    matched_terms=c.get("matched_terms", []),
                    source_file=c.get("source_file"),
                    evidence_text=c.get("evidence_text"),
                    effective_end_time=c.get("effective_end_time"),
                    end_time_estimated=c.get("end_time_estimated", False),
                )
                for c in raw_debug.get("score_details", [])
            ],
            schedule_skips=[
                ScheduleConflictRecord(
                    event_id=s.get("event_id"),
                    title=s.get("title"),
                    reason=str(s.get("reason", "")),
                )
                for s in raw_debug.get("schedule_skips", [])
            ],
            selected_event_ids=raw_debug.get("selected_event_ids", []),
            commute_matrix={
                _COMMUTE_MATRIX_KEY_MAP.get(k, k): v
                for k, v in raw_debug.get("commute_matrix_minutes", {}).items()
            },
            llm_error=raw_debug.get("llm_error"),
            llm_invalid_event_ids=raw_debug.get("llm_invalid_event_ids", []),
        )

    return PlanDayResponse(
        code=result.get("code", 0),
        data={
            "run_id": raw_data.get("run_id"),
            "status": raw_data.get("status", "failed"),
            "plan_id": raw_data.get("plan_id"),
            "title": raw_data.get("title"),
            "summary": raw_data.get("summary"),
            "date_scope": raw_data.get("date_scope"),
            "items": items,
            "started_at": raw_data.get("started_at"),
            "ended_at": raw_data.get("ended_at"),
            "error_message": raw_data.get("error_message"),
            "debug": debug.model_dump() if debug else None,
        },
        message=result.get("message", "ok"),
    )


def filter_events(
    *,
    events: list[dict[str, Any]],
    profile: dict[str, Any],
    request_text: str,
    now: datetime,
    window_start: datetime,
    window_end: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rejections: list[dict[str, str]] = []
    filtered = _rt.filter_candidates(
        events=events,
        profile=profile,
        request_text=request_text,
        now=now,
        window_start=window_start,
        window_end=window_end,
        rejections=rejections,
    )
    return filtered, rejections


def score_events(
    events: list[dict[str, Any]],
    *,
    profile: dict[str, Any],
    request_text: str,
    now: datetime,
) -> list[_rt.Candidate]:
    return _rt.score_candidates(events, profile=profile, request_text=request_text, now=now)


def detect_commute_conflict(
    schedule: list[_rt.Candidate],
    candidate: _rt.Candidate,
) -> str | None:
    return _rt.schedule_conflict(schedule, candidate)


def arrange_schedule(
    candidates: list[_rt.Candidate],
    *,
    max_items: int = 4,
) -> tuple[list[_rt.Candidate], list[dict[str, Any]]]:
    debug: dict[str, Any] = {}
    schedule = _rt.build_schedule(candidates, debug=debug, max_items=max_items)
    return schedule, debug.get("schedule_skips", [])


def plan_day_service(
    *,
    events: list[dict[str, Any]],
    profile: dict[str, Any],
    request_text: str,
    date_scope: str = "today",
    now: Optional[datetime] = None,
    include_debug: bool = False,
    enable_llm_rewrite: bool = False,
    llm_base_url: Optional[str] = None,
    llm_model: Optional[str] = None,
    llm_timeout: Optional[float] = None,
    memory: dict[str, Any] | None = None,
) -> PlanDayResponse:
    if now is None:
        now = datetime.now(_rt.DEFAULT_TIMEZONE)

    rewriter = None
    if enable_llm_rewrite:
        def _rewrite(result: dict[str, Any]) -> dict[str, Any]:
            return _llm.rewrite_with_maas(
                result,
                base_url=llm_base_url,
                model=llm_model,
                timeout=llm_timeout,
            )

        rewriter = _rewrite

    result = _rt.plan_day(
        events=events,
        profile=profile,
        request_text=request_text,
        date_scope=date_scope,
        now=now,
        include_debug=include_debug,
        rewriter=rewriter,
        memory=memory,
    )
    return _plan_day_to_response(result)


def commute_minutes(from_campus: str, to_campus: str) -> int:
    return _rt.commute_minutes(from_campus, to_campus)


def normalize_campus_name(campus: str) -> str | None:
    return _rt.normalize_campus(campus)


def rewrite_schedule(
    result: dict[str, Any],
    *,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
) -> RewriteOutput:
    rewrite = _llm.rewrite_with_maas(
        result,
        base_url=base_url,
        model=model,
        timeout=timeout,
    )

    return RewriteOutput(
        summary=rewrite.get("summary", ""),
        reasons=[
            {"event_id": str(r.get("event_id", "")), "reason_text": str(r.get("reason_text", ""))}
            for r in rewrite.get("reasons", [])
        ],
    )
