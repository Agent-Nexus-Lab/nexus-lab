"""search_events input/output type definitions.

Public API (V2):
  search_events(events, *, intent, profile?, memory?, now?)

Internal types (derived from intent+profile+memory):
  HardConstraints, SoftPreferences, SearchQuery — kept for backward compat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ===========================================================================
# V2 Public API types — what callers provide to search_events()
# ===========================================================================


@dataclass(frozen=True)
class Intent:
    """Single-request user intent — what the user wants *right now*."""

    request_text: str = ""                          # natural language request
    date_scope: str = "this_week"                   # today / tomorrow / this_week
    explicit_campuses: tuple[str, ...] = ()         # campuses mentioned in request text
    max_items: int = 4                              # desired number of results


@dataclass(frozen=True)
class Profile:
    """Standing user preferences — loaded from user profile store."""

    campus: str = ""                                # home campus (邯郸/江湾/枫林/张江/其他)
    interest_tags: tuple[str, ...] = ()
    preferred_campuses: tuple[str, ...] = ()
    available_time: str = ""                        # e.g. "晚上和周末下午"
    activity_style_tags: tuple[str, ...] = ()
    profile_summary: str = ""
    excluded_tags: tuple[str, ...] = ()             # tags that trigger rejection
    excluded_keywords: tuple[str, ...] = ()         # keywords that trigger rejection

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Profile:
        """Build a Profile from the existing profile JSON dict format."""
        if d is None:
            return cls()
        return cls(
            campus=str(d.get("campus") or ""),
            interest_tags=tuple(_ns(d.get("interest_tags"))),
            preferred_campuses=tuple(_ns(d.get("preferred_campuses"))),
            available_time=str(d.get("available_time") or ""),
            activity_style_tags=tuple(_ns(d.get("activity_style_tags"))),
            profile_summary=str(d.get("profile_summary") or ""),
            excluded_tags=tuple(_ns(d.get("excluded_tags"))),
            excluded_keywords=tuple(_ns(d.get("excluded_keywords"))),
        )


@dataclass(frozen=True)
class Memory:
    """Conversation context — carries session-level signals into scoring."""

    session_id: str = ""
    recent_query_texts: tuple[str, ...] = ()        # recent requests (for dedup/refinement)
    liked_tags: tuple[str, ...] = ()                # tags the user has liked → soft boost
    disliked_tags: tuple[str, ...] = ()             # tags the user dislikes → soft penalty
    negative_keywords: tuple[str, ...] = ()         # keywords to penalize → soft penalty
    liked_event_ids: tuple[str, ...] = ()           # events user liked → similar get boost
    disliked_event_ids: tuple[str, ...] = ()        # events user disliked → similar get penalty
    recent_plan_event_ids: tuple[str, ...] = ()     # already-recommended event_ids → repeat penalty

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Memory:
        """Build Memory from the dict returned by read_memory()."""
        if d is None:
            return cls()
        return cls(
            session_id=str(d.get("session_id") or ""),
            recent_query_texts=tuple(d.get("recent_query_texts") or ()),
            liked_tags=tuple(d.get("liked_tags") or ()),
            disliked_tags=tuple(d.get("disliked_tags") or ()),
            negative_keywords=tuple(d.get("negative_keywords") or ()),
            liked_event_ids=tuple(d.get("liked_event_ids") or ()),
            disliked_event_ids=tuple(d.get("disliked_event_ids") or ()),
            recent_plan_event_ids=tuple(d.get("recent_plan_event_ids") or ()),
        )


# ===========================================================================
# Memory subsets — for cache key generation (Scoring vs Display)
# ===========================================================================


@dataclass(frozen=True)
class ScoringMemory:
    """Memory subset that affects event scoring/ranking.

    Used in plan_result_cache key — when these fields are unchanged,
    the sorted result is identical and can be served from cache.
    """

    liked_tags: tuple[str, ...] = ()
    disliked_tags: tuple[str, ...] = ()
    negative_keywords: tuple[str, ...] = ()
    liked_event_ids: tuple[str, ...] = ()
    disliked_event_ids: tuple[str, ...] = ()
    recent_plan_event_ids: tuple[str, ...] = ()

    @classmethod
    def from_memory(cls, m: Memory) -> ScoringMemory:
        return cls(
            liked_tags=m.liked_tags,
            disliked_tags=m.disliked_tags,
            negative_keywords=m.negative_keywords,
            liked_event_ids=m.liked_event_ids,
            disliked_event_ids=m.disliked_event_ids,
            recent_plan_event_ids=m.recent_plan_event_ids,
        )

    def cache_hash(self) -> str:
        import hashlib
        import json

        return hashlib.md5(
            json.dumps(
                {
                    "lt": sorted(self.liked_tags),
                    "dt": sorted(self.disliked_tags),
                    "nk": sorted(self.negative_keywords),
                    "le": sorted(self.liked_event_ids),
                    "de": sorted(self.disliked_event_ids),
                    "rp": sorted(self.recent_plan_event_ids),
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()[:12]


@dataclass(frozen=True)
class DisplayMemory:
    """Memory subset that affects LLM summary/reason wording.

    Used in rewrite_cache key — when these fields are unchanged,
    LLM-generated text can be reused for the same plan items.
    """

    recent_query_texts: tuple[str, ...] = ()
    liked_tags: tuple[str, ...] = ()
    disliked_tags: tuple[str, ...] = ()

    @classmethod
    def from_memory(cls, m: Memory) -> DisplayMemory:
        return cls(
            recent_query_texts=m.recent_query_texts,
            liked_tags=m.liked_tags,
            disliked_tags=m.disliked_tags,
        )

    def cache_hash(self) -> str:
        import hashlib
        import json

        return hashlib.md5(
            json.dumps(
                {
                    "rq": list(self.recent_query_texts),
                    "lt": sorted(self.liked_tags),
                    "dt": sorted(self.disliked_tags),
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()[:12]


# ===========================================================================
# Internal types — derived from Intent + Profile + Memory by search_events()
# ===========================================================================


@dataclass(frozen=True)
class HardConstraints:
    """[Internal] Conditions that MUST be met. Events failing these are rejected."""

    start_time_after: datetime | None = None
    start_time_before: datetime | None = None
    exclude_past: bool = True
    require_start_time: bool = True
    campuses: tuple[str, ...] = ()
    require_location: bool = False
    require_source_evidence: bool = False
    exclude_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SoftPreferences:
    """[Internal] Conditions that influence scoring but do NOT cause rejection."""

    interest_terms: tuple[str, ...] = ()
    preferred_campuses: tuple[str, ...] = ()
    preferred_time_of_day: str = ""
    text_search: str = ""
    boost_tags: tuple[str, ...] = ()
    # Memory-derived soft adjustments (penalties / boosts from conversation context)
    penalty_event_ids: tuple[str, ...] = ()
    penalty_disliked_tags: tuple[str, ...] = ()
    penalty_negative_keywords: tuple[str, ...] = ()
    boost_liked_tags: tuple[str, ...] = ()
    boost_liked_event_ids: tuple[str, ...] = ()
    penalty_disliked_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Pagination:
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class SearchQuery:
    """[Internal] Complete derived query — built from Intent+Profile+Memory."""

    hard: HardConstraints = field(default_factory=HardConstraints)
    soft: SoftPreferences = field(default_factory=SoftPreferences)
    pagination: Pagination = field(default_factory=Pagination)
    include_debug: bool = False


# ===========================================================================
# Result types — what search_events() returns
# ===========================================================================


@dataclass(frozen=True)
class MatchedEvent:
    """A single event after filtering and scoring."""

    event: dict[str, Any]
    score: float = 0.0
    score_components: dict[str, Any] = field(default_factory=dict)
    matched_terms: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SearchResult:
    """The output of search_events()."""

    items: list[MatchedEvent]
    total: int
    page: int
    page_size: int
    total_before_filter: int
    rejections: list[dict[str, str]] = field(default_factory=list)
    is_stale: bool = False
    timings_ms: dict[str, float] = field(default_factory=dict)


# ===========================================================================
# Helpers
# ===========================================================================


def _ns(value: Any) -> list[str]:
    """Normalize a list-ish value to a list of non-empty strings."""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]
