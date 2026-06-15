"""Core retrieval primitive — search_events().

This is the central API of the agent retrieval layer. It composes hard-constraint
filtering, soft-preference scoring, and pagination into a single callable function.
It is purely deterministic and does not call any LLM.

V2 public signature:
    search_events(events, *, intent, profile?, memory?, now?)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from agent_core._runtime_compat import (
    CAMPUS_ALIASES,
    date_window,
    extract_known_terms,
)
from agent_core.filters import apply_hard_constraints
from agent_core.freshness import has_future_events
from agent_core.query import (
    HardConstraints,
    Intent,
    Memory,
    Pagination,
    Profile,
    SearchQuery,
    SearchResult,
    SoftPreferences,
)
from agent_core.scoring import (  # noqa: E402
    extract_requested_campuses,
    score_and_sort,
)

DEFAULT_TIMEZONE = timezone(timedelta(hours=8))


# ===========================================================================
# V2 Public API — the recommended entry point
# ===========================================================================


def search_events(
    events: list[dict[str, Any]],
    *,
    intent: Intent | None = None,
    profile: Profile | None = None,
    memory: Memory | None = None,
    now: datetime | None = None,
    include_debug: bool = False,
    # --- deprecated: old SearchQuery path ---
    query: SearchQuery | None = None,
) -> SearchResult:
    """Search events with intent + profile + memory.

    This is the V2 public signature. Callers provide:
    - intent: what the user wants right now (request_text, date_scope, ...)
    - profile: standing user preferences (interest_tags, campus, ...)
    - memory: conversation context (V1 stub)
    - now: reference datetime (defaults to real time or AGENT_FIXED_NOW)

    The function internally derives HardConstraints and SoftPreferences from
    these inputs, then runs the deterministic filter→score→paginate pipeline.

    Args:
        events: List of event dicts in AGGREGATED_EVENT_FIELDS format.
        intent: Single-request user intent.
        profile: Standing user preferences (optional).
        memory: Conversation context (optional, V1 stub).
        now: Reference datetime. Falls back to AGENT_FIXED_NOW env var or real time.
        include_debug: If True, populate rejections in result.
        query: [Deprecated] Pre-built SearchQuery. Takes precedence if provided.

    Returns:
        SearchResult with paginated MatchedEvent items, totals, and freshness flag.
    """
    # --- Deprecated path: caller provided a pre-built SearchQuery ---
    if query is not None:
        return _search_events_legacy(
            events, query=query, now=now,
        )

    # --- Resolve time ---
    if now is None:
        now = _resolve_now()

    # --- Derive internal constraints from intent + profile + memory ---
    _intent = intent if intent is not None else Intent()
    _profile = profile or Profile()
    _memory = memory or Memory()
    internal = _build_query(
        intent=_intent,
        profile=_profile,
        memory=_memory,
        now=now,
        include_debug=include_debug,
    )

    return _search_events_legacy(events, query=internal, now=now)


# ===========================================================================
# Internal: derive constraints from intent + profile + memory
# ===========================================================================


def _build_query(
    *,
    intent: Intent,
    profile: Profile,
    memory: Memory,
    now: datetime,
    include_debug: bool,
) -> SearchQuery:
    """Derive HardConstraints + SoftPreferences from Intent + Profile + Memory.

    This is the bridge between the user-friendly V2 types and the internal
    filter/scoring engine. It encodes the system's default policies (e.g.
    require source evidence, exclude past events).
    """

    # --- Resolve date window ---
    window_start, window_end = date_window(intent.date_scope, now)

    # --- Resolve campuses ---
    requested = set(intent.explicit_campuses)

    # --- Hard constraints ---
    # System defaults: exclude past, require start_time, require source evidence
    # User preferences: excluded tags/keywords
    # Intent: date scope, explicit campuses
    hard = HardConstraints(
        start_time_after=window_start,
        start_time_before=window_end,
        exclude_past=True,
        require_start_time=True,
        campuses=tuple(requested) if requested else (),
        require_source_evidence=True,  # 可回溯来源 — system default
        exclude_tags=profile.excluded_tags + tuple(
            kw for kw in profile.excluded_keywords
        ),
    )

    # --- Soft preferences ---
    # Interest: profile.interest_tags + profile.activity_style_tags + intent extraction
    interest_terms = list(profile.interest_tags)
    interest_terms.extend(profile.activity_style_tags)
    interest_terms.extend(extract_known_terms(intent.request_text))

    # Time-of-day: profile.available_time + intent request_text
    time_pref = f"{profile.available_time} {intent.request_text}".strip()

    soft = SoftPreferences(
        interest_terms=tuple(dict.fromkeys(interest_terms)),  # dedup, preserve order
        preferred_campuses=profile.preferred_campuses,
        preferred_time_of_day=time_pref,
        text_search=intent.request_text,
        # Memory-derived soft adjustments
        penalty_event_ids=memory.recent_plan_event_ids,
        penalty_disliked_tags=memory.disliked_tags,
        penalty_negative_keywords=memory.negative_keywords,
        boost_liked_tags=memory.liked_tags,
    )

    return SearchQuery(
        hard=hard,
        soft=soft,
        pagination=Pagination(page=1, page_size=max(intent.max_items, 20)),
        include_debug=include_debug,
    )


# ===========================================================================
# Legacy path — called internally when SearchQuery is provided directly
# ===========================================================================


def _search_events_legacy(
    events: list[dict[str, Any]],
    *,
    query: SearchQuery,
    now: datetime | None = None,
) -> SearchResult:
    """Internal: run the full pipeline with a pre-built SearchQuery."""
    if now is None:
        now = _resolve_now()

    total_before_filter = len(events)

    # Phase 1: Hard constraint filtering
    rejections: list[dict[str, str]] = []
    filtered = apply_hard_constraints(
        events,
        constraint=query.hard,
        now=now,
        rejections=rejections,
    )

    # Phase 2: Soft preference scoring
    scored = score_and_sort(filtered, preferences=query.soft, now=now)

    # Phase 3: Pagination
    pagination = query.pagination
    start_idx = (pagination.page - 1) * pagination.page_size
    end_idx = start_idx + pagination.page_size
    page_items = scored[start_idx:end_idx] if start_idx < len(scored) else []

    # Phase 4: Staleness check
    is_stale = not has_future_events(events, now=now)

    result = SearchResult(
        items=page_items,
        total=len(scored),
        page=pagination.page,
        page_size=pagination.page_size,
        total_before_filter=total_before_filter,
        is_stale=is_stale,
    )

    if query.include_debug:
        result = SearchResult(
            items=result.items,
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            total_before_filter=result.total_before_filter,
            rejections=rejections,
            is_stale=result.is_stale,
        )

    return result


# ===========================================================================
# Query builders — convert plan_day / legacy parameters
# ===========================================================================


def query_for_plan_day(
    *,
    date_scope: str,
    now: datetime,
    profile: dict[str, Any],
    request_text: str,
) -> SearchQuery:
    """Build a SearchQuery from plan_day parameters (backward compat).

    Deprecated: prefer using search_events(intent=..., profile=...) directly.
    """
    intent = Intent(
        request_text=request_text,
        date_scope=date_scope,
        explicit_campuses=tuple(extract_requested_campuses(request_text)),
    )
    prof = Profile.from_dict(profile)
    return _build_query(
        intent=intent, profile=prof, memory=Memory(), now=now, include_debug=False,
    )


def normalize_string_list(value: Any) -> list[str]:
    """Normalize a list value to a list of non-empty strings."""
    from agent_core._runtime_compat import normalize_string_list as _nsl
    return _nsl(value)


# ===========================================================================
# Time resolution (delegated to shared provider)
# ===========================================================================

from agent_core.time_provider import resolve_now as _resolve_now  # noqa: E402
