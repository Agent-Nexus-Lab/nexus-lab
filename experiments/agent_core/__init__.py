"""Agent Core — retrieval & tool layer for the campus schedule AI assistant.

Public API (V2):
- search_events(events, *, intent, profile?, memory?, now?)
- Intent / Profile / Memory — user-facing input types
- SearchResult / MatchedEvent — output types
- DataSource / DataSourceRegistry / FileTextSource — data source abstraction
- has_future_events / needs_refresh — freshness gating
"""

from agent_core.datasource import DataSource, DataSourceRegistry, FileTextSource
from agent_core.freshness import has_future_events, needs_refresh
from agent_core.pipeline import PlanDayPipeline
from agent_core.query import (
    HardConstraints,
    Intent,
    MatchedEvent,
    Memory,
    Pagination,
    Profile,
    SearchQuery,
    SearchResult,
    SoftPreferences,
)
from agent_core.search_events import query_for_plan_day, search_events

__all__ = [
    # Core search
    "search_events",
    "query_for_plan_day",
    # V2 Public types
    "Intent",
    "Profile",
    "Memory",
    # Result types
    "SearchResult",
    "MatchedEvent",
    # Internal types (kept for backward compat)
    "SearchQuery",
    "HardConstraints",
    "SoftPreferences",
    "Pagination",
    # Data sources
    "DataSource",
    "DataSourceRegistry",
    "FileTextSource",
    # Pipeline
    "PlanDayPipeline",
    # Freshness
    "has_future_events",
    "needs_refresh",
]
