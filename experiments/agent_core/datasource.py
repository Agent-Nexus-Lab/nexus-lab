"""DataSource abstraction — runtime-callable event sources.

Each DataSource encapsulates the full pipeline: scrape raw content → extract
structured events → aggregate. The DataSourceRegistry manages all registered
sources and provides a unified collect_all_events() entry point.

V1 implementation:
- FileTextSource: wraps extraction from existing text files (fast path)
- WeChatSource: wraps scrape (fetch_weixin.py) + extract (cli.py) via subprocess
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_core._runtime_compat import parse_datetime
from agent_core._schema_compat import (
    AGGREGATED_EVENT_FIELDS,
    EVENT_FIELDS,
    build_aggregated_event,
    validate_events_file,
)
from agent_core.time_provider import resolve_now

_EXPERIMENTS_ROOT = Path(__file__).resolve().parents[1]

# Default paths relative to experiments/
DEFAULT_TEXTS_DIR = _EXPERIMENTS_ROOT / "agent-maas-cli" / "texts"
DEFAULT_OUTPUTS_DIR = _EXPERIMENTS_ROOT / "agent-maas-cli" / "outputs"
DEFAULT_EVENTS_PATH = DEFAULT_OUTPUTS_DIR / "events.json"


# ---------------------------------------------------------------------------
# DataSource ABC
# ---------------------------------------------------------------------------


class DataSource(ABC):
    """A callable source of campus events.

    Each DataSource knows how to:
    - Discover and/or scrape event data from its source
    - Extract structured events from raw text
    - Cache results
    - Report staleness status
    """

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Unique identifier, e.g. 'weixin_fd_tianxie'."""
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable name, e.g. '复旦天协'."""
        ...

    @abstractmethod
    def fetch_events(self, *, force: bool = False) -> list[dict[str, Any]]:
        """Retrieve events from this source.

        Returns a list of event dicts in AGGREGATED_EVENT_FIELDS format.
        Returns [] on transient failure (caller may retry).
        Must update self.last_fetched_at on success.
        """
        ...

    @property
    def freshness_ttl(self) -> timedelta:
        """How long fetched data is considered fresh. Default 24 hours."""
        return timedelta(hours=24)

    @property
    @abstractmethod
    def last_fetched_at(self) -> datetime | None:
        """When fetch_events() last succeeded, or None if never."""
        ...

    def is_stale(self, now: datetime | None = None) -> bool:
        """Return True if data has not been refreshed within freshness_ttl."""
        if self.last_fetched_at is None:
            return True
        if now is None:
            now = resolve_now()
        return (now - self.last_fetched_at) > self.freshness_ttl

    def has_future_events(self, events: list[dict[str, Any]], now: datetime | None = None) -> bool:
        """Check if cached events include any future events."""
        from agent_core.freshness import has_future_events as _has_future
        return _has_future(events, now=now)


# ---------------------------------------------------------------------------
# FileTextSource — wraps extraction from existing text files
# ---------------------------------------------------------------------------


class FileTextSource(DataSource):
    """DataSource backed by text files in agent-maas-cli/texts/.

    This is the fast path: text files are already scraped (e.g., by fetch_weixin.py).
    The source wraps the MaaS extraction step only.
    """

    def __init__(
        self,
        source_id: str,
        source_name: str,
        *,
        texts_dir: Path | None = None,
        cache_path: Path | None = None,
    ):
        self._source_id = source_id
        self._source_name = source_name
        self._texts_dir = Path(texts_dir) if texts_dir else DEFAULT_TEXTS_DIR
        self._cache_path = Path(cache_path) if cache_path else (self._texts_dir.parent / "outputs" / f"{source_id}_cache.json")
        self._last_fetched_at: datetime | None = None
        self._cached_events: list[dict[str, Any]] = []

        # Load cache if exists
        if self._cache_path.exists():
            try:
                payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
                self._cached_events = payload.get("events", [])
                if payload.get("last_fetched_at"):
                    self._last_fetched_at = datetime.fromisoformat(payload["last_fetched_at"])
            except (json.JSONDecodeError, KeyError, ValueError):
                self._cached_events = []
                self._last_fetched_at = None

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def source_name(self) -> str:
        return self._source_name

    @property
    def last_fetched_at(self) -> datetime | None:
        return self._last_fetched_at

    def fetch_events(self, *, force: bool = False) -> list[dict[str, Any]]:
        """Extract events from all text files in the texts directory.

        For each .txt file, calls the MaaS extraction CLI. New events
        are appended to the cache; previously extracted files are skipped
        unless force=True.
        """
        if not self._texts_dir.exists():
            return list(self._cached_events)

        text_files = sorted(self._texts_dir.glob("*.txt"))
        if not text_files:
            self._update_last_fetched()
            return list(self._cached_events)

        # Track which source_files are already in cache (incremental)
        cached_files: set[str] = set()
        if not force:
            for ev in self._cached_events:
                sf = ev.get("source_file", "")
                if sf:
                    cached_files.add(sf)

        new_events: list[dict[str, Any]] = []
        for text_file in text_files:
            if text_file.name in cached_files:
                continue

            try:
                extracted = self._extract_from_file(text_file)
                for ev in extracted.get("events", []):
                    new_events.append(
                        build_aggregated_event(
                            ev,
                            event_id=str(uuid.uuid4()),
                            source_file=text_file.name,
                            source_name=extracted.get("source_name") or self._source_name,
                            source_url=extracted.get("source_url"),
                        )
                    )
            except Exception:
                # Transient failure — skip this file, try next
                continue

        if new_events:
            self._cached_events.extend(new_events)
            self._save_cache()

        self._update_last_fetched()
        return list(self._cached_events)

    def _extract_from_file(self, text_file: Path) -> dict[str, Any]:
        """Run MaaS extraction on a single text file via CLI subprocess.

        Returns the normalized extraction result (source_name, source_url, events, warnings).
        """
        cli_path = self._texts_dir.parent / "cli.py"
        if not cli_path.exists():
            raise FileNotFoundError(f"MaaS CLI not found: {cli_path}")

        result = subprocess.run(
            [
                sys.executable,
                str(cli_path),
                "--input", str(text_file),
                "--source-name", self._source_name,
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=120,  # MaaS API can be slow
            cwd=str(cli_path.parent),
        )

        if result.returncode != 0:
            raise RuntimeError(f"MaaS extraction failed for {text_file.name}: {result.stderr}")

        return json.loads(result.stdout)

    def _update_last_fetched(self) -> None:
        self._last_fetched_at = resolve_now()

    def _save_cache(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(
            json.dumps(
                {
                    "events": self._cached_events,
                    "last_fetched_at": self._last_fetched_at.isoformat() if self._last_fetched_at else None,
                    "source_id": self._source_id,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# DataSourceRegistry
# ---------------------------------------------------------------------------


class DataSourceRegistry:
    """Manages all registered DataSources and provides unified event collection."""

    def __init__(self) -> None:
        self._sources: dict[str, DataSource] = {}

    def register(self, source: DataSource) -> None:
        """Register a data source."""
        self._sources[source.source_id] = source

    def get(self, source_id: str) -> DataSource | None:
        """Get a registered source by ID."""
        return self._sources.get(source_id)

    @property
    def source_ids(self) -> list[str]:
        return list(self._sources.keys())

    def collect_all_events(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Fetch events from all registered sources.

        If force_refresh is False, stale sources are refreshed; fresh sources
        return cached results.

        Returns all events aggregated from all sources, in AGGREGATED_EVENT_FIELDS format.
        """
        all_events: list[dict[str, Any]] = []
        for source in self._sources.values():
            if force_refresh or source.is_stale():
                events = source.fetch_events(force=force_refresh)
            else:
                events = source.fetch_events(force=False)
            all_events.extend(events)
        return all_events

    def check_freshness(self) -> dict[str, bool]:
        """Return {source_id: is_stale} for all registered sources."""
        now = resolve_now()
        return {sid: src.is_stale(now=now) for sid, src in self._sources.items()}

    def all_fresh(self) -> bool:
        """Return True if all registered sources are fresh."""
        return not any(self.check_freshness().values())
