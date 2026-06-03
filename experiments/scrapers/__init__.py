"""Scrapers package — WeChat article scraping and event extraction pipeline.

Public API:
    ExporterClient     — HTTP client for wechat-article-exporter
    WeChatDataSource   — DataSource implementation backed by wechat-article-exporter
    AccountConfig      — account list entry dataclass
    load_account_list  — load target accounts from account_list.json
    cleanup_stale_events — remove expired events and orphaned text files
    generate_demo_events — generate ~20 future events for dev/test
"""

from scrapers.account_list import AccountConfig, load_account_list
from scrapers.cleanup import cleanup_stale_events
from scrapers.demo_data import generate_demo_events, write_demo_events
from scrapers.exporter_client import ExporterClient, ExporterError
from scrapers.wechat_datasource import WeChatDataSource

__all__ = [
    "AccountConfig",
    "ExporterClient",
    "ExporterError",
    "WeChatDataSource",
    "cleanup_stale_events",
    "generate_demo_events",
    "load_account_list",
    "write_demo_events",
]
