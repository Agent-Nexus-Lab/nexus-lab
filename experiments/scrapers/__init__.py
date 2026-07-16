"""Scrapers package with lazy public imports.

Public API:
    ExporterClient     — HTTP client for wechat-article-exporter
    WeChatDataSource   — DataSource implementation backed by wechat-article-exporter
    AccountConfig      — account list entry dataclass
    load_account_list  — load target accounts from account_list.json
    cleanup_stale_events — remove expired events and orphaned text files
    generate_demo_events — generate ~20 future events for dev/test
"""

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


def __getattr__(name):
    if name in {"AccountConfig", "load_account_list"}:
        from scrapers.account_list import AccountConfig, load_account_list

        return {"AccountConfig": AccountConfig, "load_account_list": load_account_list}[name]
    if name == "cleanup_stale_events":
        from scrapers.cleanup import cleanup_stale_events

        return cleanup_stale_events
    if name in {"generate_demo_events", "write_demo_events"}:
        from scrapers.demo_data import generate_demo_events, write_demo_events

        return {
            "generate_demo_events": generate_demo_events,
            "write_demo_events": write_demo_events,
        }[name]
    if name in {"ExporterClient", "ExporterError"}:
        from scrapers.exporter_client import ExporterClient, ExporterError

        return {"ExporterClient": ExporterClient, "ExporterError": ExporterError}[name]
    if name == "WeChatDataSource":
        from scrapers.wechat_datasource import WeChatDataSource

        return WeChatDataSource
    raise AttributeError(name)
