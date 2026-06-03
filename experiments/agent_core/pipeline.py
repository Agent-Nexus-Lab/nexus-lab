"""End-to-end pipeline: datasource → search → plan_day.

Orchestrates the full flow from data sources through retrieval to plan building.
Replaces the manual event loading + filter/score chain in runtime.py plan_day().
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent_core.time_provider import resolve_now
from agent_core.datasource import DataSourceRegistry
from agent_core.query import SearchQuery, SearchResult
from agent_core.search_events import search_events, query_for_plan_day


class PlanDayPipeline:
    """Orchestrates the full plan-day flow: datasource → search → plan build.

    Usage:
        registry = DataSourceRegistry()
        registry.register(my_source)
        pipeline = PlanDayPipeline(registry)
        result = pipeline.run(query=search_query, now=now)
    """

    def __init__(self, registry: DataSourceRegistry):
        self._registry = registry

    def run(
        self,
        *,
        query: SearchQuery,
        now: datetime | None = None,
        force_refresh: bool = False,
    ) -> SearchResult:
        """Run the full pipeline.

        1. Collect events from all registered datasources (refresh stale ones)
        2. Run search_events with the given query
        3. Return SearchResult
        """
        if now is None:
            now = resolve_now()

        events = self._registry.collect_all_events(force_refresh=force_refresh)
        return search_events(events, query=query, now=now)

    def run_plan_day(
        self,
        *,
        profile: dict[str, Any],
        request_text: str,
        date_scope: str,
        now: datetime | None = None,
        force_refresh: bool = False,
    ) -> SearchResult:
        """Convenience method: build SearchQuery from plan-day params, then run.

        This is the drop-in entry point for existing plan_day() callers.
        """
        if now is None:
            now = resolve_now()

        query = query_for_plan_day(
            date_scope=date_scope,
            now=now,
            profile=profile,
            request_text=request_text,
        )
        return self.run(query=query, now=now, force_refresh=force_refresh)
