"""WeChat DataSource — runtime-callable event source backed by wechat-article-exporter.

Full pipeline:
    1. get auth-key from exporter server
    2. search account → get fakeid
    3. fetch article list from appmsgpublish API
    4. download each article content as JSON
    5. convert to pipeline text format (.txt files)
    6. run MaaS extraction CLI to produce structured events
    7. aggregate events into DataSource cache

Can be registered with DataSourceRegistry so PlanDayPipeline can consume it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_core._runtime_compat import parse_datetime
from agent_core._schema_compat import build_aggregated_event
from agent_core.datasource import DataSource

from scrapers.account_list import AccountConfig
from scrapers.exporter_client import ExporterClient, ExporterError

_EXPERIMENTS_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEXTS_DIR = _EXPERIMENTS_ROOT / "agent_maas_cli" / "texts"
DEFAULT_OUTPUTS_DIR = _EXPERIMENTS_ROOT / "agent_maas_cli" / "outputs"
MAAS_CLI_PATH = _EXPERIMENTS_ROOT / "agent_maas_cli" / "cli.py"


class WeChatDataSource(DataSource):
    """DataSource backed by wechat-article-exporter for a single WeChat account.

    Implements the DataSource ABC — can be registered with DataSourceRegistry
    and consumed by PlanDayPipeline.
    """

    def __init__(
        self,
        account: AccountConfig,
        *,
        exporter_client: ExporterClient | None = None,
        texts_dir: Path | None = None,
        cache_path: Path | None = None,
        max_articles: int = 5,
    ):
        self._account = account
        self._source_id = f"weixin_{account.id}"
        self._source_name = account.name
        self._client = exporter_client or ExporterClient()
        self._texts_dir = texts_dir or DEFAULT_TEXTS_DIR
        self._cache_path = cache_path or (
            DEFAULT_OUTPUTS_DIR / f"{self._source_id}_cache.json"
        )
        self._max_articles = max_articles
        self._last_fetched_at: datetime | None = None
        self._cached_events: list[dict[str, Any]] = []
        self._load_cache()

    # ── DataSource interface ────────────────────────────────────────

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
        """Run the full pipeline: scrape → download → extract → aggregate.

        Incremental by default — skips previously fetched articles unless
        force=True. New articles are appended to the cache.
        """
        # 1. Fetch and convert new articles (raw scrape)
        new_texts = self.fetch_raw_articles(force=force)

        if not new_texts:
            self._update_last_fetched()
            return list(self._cached_events)

        # 2. Run MaaS extraction on new text files
        try:
            self._run_maas_extraction()
        except Exception:
            pass  # extraction failure doesn't invalidate cache

        # 3. Reload events from events.json to pick up new extractions
        events_file = DEFAULT_OUTPUTS_DIR / "events.json"
        if events_file.exists():
            try:
                data = json.loads(events_file.read_text(encoding="utf-8"))
                for ev in data.get("events", []):
                    # Only add events whose source_file matches our new texts
                    sf = ev.get("source_file", "")
                    if any(sf == t.name for t in new_texts):
                        if not any(
                            c.get("event_id") == ev.get("event_id")
                            for c in self._cached_events
                        ):
                            self._cached_events.append(ev)
            except Exception:
                pass

        self._update_last_fetched()
        self._save_cache()
        return list(self._cached_events)

    def fetch_raw_articles(self, *, force: bool = False) -> list[Path]:
        """Fetch and convert articles without running MaaS extraction.

        Returns list of Paths to newly written text files.
        """
        self._texts_dir.mkdir(parents=True, exist_ok=True)

        # Track already-fetched URLs via cache
        cached_urls: set[str] = set()
        if not force:
            for ev in self._cached_events:
                u = ev.get("source_url", "")
                if u:
                    cached_urls.add(u)

        # Get auth key
        auth_key = self._client.get_auth_key()
        if not auth_key:
            raise ExporterError(
                "No active session. Please login at http://localhost:3000 first."
            )

        # Search account
        acct = self._client.search_account(auth_key, self._account.keyword)
        if not acct:
            print(f"  [wechat:{self._source_id}] account '{self._account.keyword}' not found",
                  file=sys.stderr)
            return []
        fakeid = acct["fakeid"]

        # Get article list
        articles = self._client.get_article_list(auth_key, fakeid, self._max_articles)
        if not articles:
            print(f"  [wechat:{self._source_id}] no articles found", file=sys.stderr)
            return []

        new_files: list[Path] = []
        for article in articles:
            url = article.get("link", "")
            if url in cached_urls:
                continue

            try:
                content = self._client.download_article(url)
                text_path = self._client.convert_to_text(content, self._texts_dir)
                new_files.append(text_path)
                time.sleep(0.3)  # polite delay
            except Exception as exc:
                print(f"  [wechat:{self._source_id}] download failed: {exc}",
                      file=sys.stderr)

        return new_files

    # ── internal ────────────────────────────────────────────────────

    def _load_cache(self) -> None:
        if self._cache_path.exists():
            try:
                data = json.loads(self._cache_path.read_text(encoding="utf-8"))
                self._cached_events = data.get("events", [])
                last = data.get("last_fetched_at")
                if last:
                    self._last_fetched_at = datetime.fromisoformat(last)
            except Exception:
                self._cached_events = []
                self._last_fetched_at = None

    def _save_cache(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(
            json.dumps(
                {
                    "events": self._cached_events,
                    "last_fetched_at": (
                        self._last_fetched_at.isoformat()
                        if self._last_fetched_at
                        else None
                    ),
                    "source_id": self._source_id,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
            + "\n",
            encoding="utf-8",
        )

    def _update_last_fetched(self) -> None:
        self._last_fetched_at = datetime.now().astimezone()

    def _run_maas_extraction(self) -> None:
        """Run the MaaS CLI in batch mode to extract events from text files."""
        result = subprocess.run(
            [
                sys.executable,
                str(MAAS_CLI_PATH),
                "--input-dir",
                str(self._texts_dir),
                "--write-output",
                "--incremental",
            ],
            cwd=str(MAAS_CLI_PATH.parent),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"  [wechat:{self._source_id}] MaaS extraction warning",
                  file=sys.stderr)
