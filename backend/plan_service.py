from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_RUNTIME_DIR = Path(__file__).resolve().parents[1] / "experiments" / "agent_plan_runtime"
if str(_RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_DIR))

import experiments.agent_plan_runtime.runtime as _rt
import experiments.agent_plan_runtime.llm as _llm
from backend.cache_backend import InMemoryCache, RedisCache
from backend.plan_cache import PlanResultCache
from backend.rewrite_cache import RewriteCache
from backend.schemas import (
    CacheInfo,
    CandidateDetail,
    DebugInfo,
    LlmRewriteInfo,
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

# Lazy-initialized cache singletons
_plan_result_cache: Optional[PlanResultCache] = None
_rewrite_cache: Optional[RewriteCache] = None
_cache_backend_info: Optional[dict[str, Any]] = None


def _get_cache_backend():
    """Initialize cache backend once, preferring Redis with InMemory fallback."""
    global _plan_result_cache, _rewrite_cache, _cache_backend_info
    if _plan_result_cache is not None:
        return _plan_result_cache, _rewrite_cache, _cache_backend_info

    redis_url = os.getenv("REDIS_URL", "")
    redis_available = False
    using_fallback = False

    if redis_url:
        redis_backend = RedisCache(redis_url)
        redis_available = redis_backend.available()
        using_fallback = redis_backend.using_fallback
        backend = redis_backend
    else:
        backend = InMemoryCache()

    _cache_backend_info = {
        "redis_available": redis_available,
        "using_fallback": using_fallback or not redis_url,
    }
    _plan_result_cache = PlanResultCache(backend)
    _rewrite_cache = RewriteCache(backend)
    return _plan_result_cache, _rewrite_cache, _cache_backend_info


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
        raw_cache = raw_debug.get("cache")
        cache_info = None
        if isinstance(raw_cache, dict):
            cache_info = CacheInfo(
                cache_hit=raw_cache.get("cache_hit", False),
                cache_type=raw_cache.get("cache_type", "none"),
                plan_result_cache_hit=raw_cache.get("plan_result_cache_hit", False),
                rewrite_cache_hit=raw_cache.get("rewrite_cache_hit", False),
                redis_available=raw_cache.get("redis_available", False),
                using_fallback=raw_cache.get("using_fallback", False),
            )

        raw_llm_rewrite = raw_debug.get("llm_rewrite")
        llm_rewrite_info = None
        if isinstance(raw_llm_rewrite, dict):
            llm_rewrite_info = LlmRewriteInfo(
                used_fallback=raw_llm_rewrite.get("used_fallback", False),
                rewrite_error=raw_llm_rewrite.get("rewrite_error"),
                timeout_seconds=raw_llm_rewrite.get("timeout_seconds"),
                model_name=raw_llm_rewrite.get("model_name"),
                prompt_version=raw_llm_rewrite.get("prompt_version"),
            )

        raw_timings = raw_debug.get("timings_ms")

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
            cache=cache_info,
            llm_rewrite=llm_rewrite_info,
            timings_ms=raw_timings if isinstance(raw_timings, dict) else None,
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


def _compute_scoring_memory_hash(memory: dict[str, Any] | None) -> str:
    """Compute ScoringMemory hash from a memory dict, without needing the dataclass."""
    if not memory:
        return hashlib.md5(b"{}").hexdigest()[:12]
    payload = json.dumps(
        {
            "lt": sorted(memory.get("liked_tags", []) or []),
            "dt": sorted(memory.get("disliked_tags", []) or []),
            "nk": sorted(memory.get("negative_keywords", []) or []),
            "le": sorted(memory.get("liked_event_ids", []) or []),
            "de": sorted(memory.get("disliked_event_ids", []) or []),
            "rp": sorted(memory.get("recent_plan_event_ids", []) or []),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.md5(payload.encode()).hexdigest()[:12]


def _compute_display_memory_hash(memory: dict[str, Any] | None) -> str:
    """Compute DisplayMemory hash from a memory dict."""
    if not memory:
        return hashlib.md5(b"{}").hexdigest()[:12]
    payload = json.dumps(
        {
            "rq": list(memory.get("recent_query_texts", []) or []),
            "lt": sorted(memory.get("liked_tags", []) or []),
            "dt": sorted(memory.get("disliked_tags", []) or []),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.md5(payload.encode()).hexdigest()[:12]


def _patch_rewrite(result: dict[str, Any], rewrite: dict[str, Any]) -> dict[str, Any]:
    """Apply cached or LLM rewrite output to the result data."""
    data = result.setdefault("data", {})
    data["summary"] = rewrite.get("summary", data.get("summary"))
    reasons = rewrite.get("reasons", [])
    items = data.get("items")
    if isinstance(items, list) and isinstance(reasons, list):
        for i, reason in enumerate(reasons):
            if i < len(items) and isinstance(items[i], dict) and isinstance(reason, dict):
                items[i]["reason_text"] = reason.get("reason_text", items[i].get("reason_text", ""))
    return result


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
    use_search_events: bool = True,
) -> PlanDayResponse:
    if now is None:
        now = datetime.now(_rt.DEFAULT_TIMEZONE)

    plan_cache, rewrite_cache_inst, cache_info = _get_cache_backend()
    resolved_model = llm_model or os.getenv("LLM_MODEL") or os.getenv("MAAS_MODEL") or "deepseek-v4-pro"
    profile_id = str(profile.get("campus", "")) + ":" + str(profile.get("profile_summary", ""))[:32]

    query_hash = PlanResultCache.compute_query_hash(request_text)
    event_snapshot_hash = PlanResultCache.compute_event_snapshot_hash(events)
    scoring_mem_hash = _compute_scoring_memory_hash(memory)

    plan_cache_key = plan_cache.build_key(
        profile_id=profile_id,
        query_hash=query_hash,
        date_scope=date_scope,
        scoring_memory_hash=scoring_mem_hash,
        event_snapshot_hash=event_snapshot_hash,
    )

    debug_cache: dict[str, Any] = {
        "cache_hit": False,
        "cache_type": "none",
        "plan_result_cache_hit": False,
        "rewrite_cache_hit": False,
        "redis_available": cache_info["redis_available"] if cache_info else False,
        "using_fallback": cache_info["using_fallback"] if cache_info else False,
    }
    debug_llm_rewrite: dict[str, Any] = {
        "used_fallback": False,
        "rewrite_error": None,
        "timeout_seconds": llm_timeout,
        "model_name": resolved_model,
        "prompt_version": _llm.PROMPT_VERSION,
    }

    # 1. Check plan_result_cache
    cached_result = plan_cache.get(plan_cache_key)
    if cached_result is not None:
        debug_cache["cache_hit"] = True
        debug_cache["cache_type"] = "plan_result"
        debug_cache["plan_result_cache_hit"] = True
        result: dict[str, Any] = {"code": 0, "data": cached_result, "message": "ok"}
        if include_debug:
            data = result.setdefault("data", {})
            existing_debug = data.get("debug") if isinstance(data.get("debug"), dict) else {}
            existing_debug["cache"] = debug_cache
            existing_debug["llm_rewrite"] = debug_llm_rewrite
            data["debug"] = existing_debug
        return _plan_day_to_response(result)

    # 2. Run plan_day without LLM rewrite (scoring + scheduling)
    result = _rt.plan_day(
        events=events,
        profile=profile,
        request_text=request_text,
        date_scope=date_scope,
        now=now,
        include_debug=include_debug,
        rewriter=None,
        memory=memory,
        use_search_events=use_search_events,
    )

    # 3. LLM rewrite phase with rewrite_cache
    if enable_llm_rewrite:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        items = data.get("items") if isinstance(data.get("items"), list) else []
        plan_items_hash = RewriteCache.compute_plan_items_hash(items)
        display_mem_hash = _compute_display_memory_hash(memory)

        rewrite_key = rewrite_cache_inst.build_key(
            plan_items_hash=plan_items_hash,
            display_memory_hash=display_mem_hash,
            prompt_version=_llm.PROMPT_VERSION,
            model_name=resolved_model,
        )

        cached_rewrite = rewrite_cache_inst.get(rewrite_key)
        if cached_rewrite is not None:
            debug_cache["cache_hit"] = True
            debug_cache["cache_type"] = "rewrite"
            debug_cache["rewrite_cache_hit"] = True
            _patch_rewrite(result, cached_rewrite)
        else:
            t_rewrite_start = time.perf_counter()
            try:
                rewrite_output = _llm.rewrite_with_maas(
                    result,
                    base_url=llm_base_url,
                    model=llm_model,
                    timeout=llm_timeout,
                )
                rewrite_cache_inst.set(rewrite_key, rewrite_output)
                _patch_rewrite(result, rewrite_output)
            except Exception as exc:
                debug_llm_rewrite["used_fallback"] = True
                debug_llm_rewrite["rewrite_error"] = str(exc)
                # Template summary and reasons from build_summary/render_item stay in place
            rewrite_elapsed = (time.perf_counter() - t_rewrite_start) * 1000
            if include_debug:
                debug = result.get("data", {}).get("debug") if isinstance(result.get("data"), dict) else None
                if isinstance(debug, dict):
                    timings = debug.get("timings_ms") or {}
                    if isinstance(timings, dict):
                        timings["llm_rewrite"] = round(rewrite_elapsed)

    # 4. Cache the final result in plan_result_cache
    final_data = result.get("data") if isinstance(result.get("data"), dict) else {}
    plan_cache.set(plan_cache_key, dict(final_data))

    # 5. Attach cache + llm_rewrite debug
    if include_debug:
        data = result.setdefault("data", {})
        existing_debug = data.get("debug") if isinstance(data.get("debug"), dict) else {}
        existing_debug["cache"] = debug_cache
        existing_debug["llm_rewrite"] = debug_llm_rewrite
        data["debug"] = existing_debug

    return _plan_day_to_response(result)


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
