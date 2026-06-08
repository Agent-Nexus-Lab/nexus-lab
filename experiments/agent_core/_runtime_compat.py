"""Shared utility functions extracted from agent_plan_runtime/runtime.py.

These functions were previously imported via sys.path.insert() hacks from
agent_core modules.  Extracting them here makes agent_core self-contained
and eliminates the fragile cross-package dependency.

All functions are pure utilities with no agent_core-specific imports.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

# ===========================================================================
# Constants
# ===========================================================================

DEFAULT_TIMEZONE = timezone(timedelta(hours=8))

CAMPUS_ALIASES: dict[str, str] = {
    "邯郸": "邯郸",
    "邯郸校区": "邯郸",
    "江湾": "江湾",
    "江湾校区": "江湾",
    "枫林": "枫林",
    "枫林校区": "枫林",
    "张江": "张江",
    "张江校区": "张江",
    "其他": "其他",
}

KNOWN_INTEREST_TERMS: list[str] = [
    "AI",
    "人工智能",
    "大模型",
    "创业",
    "产品",
    "天文",
    "观星",
    "戏剧",
    "工作坊",
    "分享会",
    "学术",
    "参观",
    "展览",
    "图书馆",
    "体育",
    "游泳",
    "音乐",
    "吉他",
    "猫",
    "职业",
    "就业",
    "公益",
    "社交",
    "互动",
    "轻松",
    "实践",
    "理论",
    "正式",
    "自由",
    "讲座",
    "沙龙",
    "比赛",
    "演出",
    "聚会",
    "课程",
    "本研融通",
    "返校日",
]

TERM_ALIASES: dict[str, list[str]] = {
    "AI": ["AI", "ai", "人工智能", "大模型", "机器学习", "计算机", "技术"],
    "人工智能": ["AI", "ai", "人工智能", "大模型", "机器学习", "计算机", "技术"],
    "创业": ["创业", "创新创业", "产品", "商业"],
    "职业": ["职业", "就业", "生涯", "HR", "简历"],
    "就业": ["就业", "职业", "生涯", "HR", "简历"],
    "天文": ["天文", "观星", "星空", "望远镜"],
    "观星": ["观星", "天文", "星空", "望远镜"],
    "戏剧": ["戏剧", "剧社", "编演", "剧组"],
    "图书馆": ["图书馆", "文图", "理图", "阅读", "图书"],
    "体育": ["体育", "运动", "游泳"],
    "游泳": ["游泳", "泳池", "运动"],
    "轻松": ["轻松", "自由", "互动", "趣味"],
    "互动": ["互动", "工作坊", "沙龙", "小游戏", "自由交流"],
    "实践": ["实践", "实战", "工作坊", "训练营"],
    "学术": ["学术", "讲座", "论坛", "科研"],
}

# ===========================================================================
# Time helpers
# ===========================================================================


def parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO 8601 datetime string, defaulting to DEFAULT_TIMEZONE
    if no timezone is present."""
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=DEFAULT_TIMEZONE)
    return parsed


def date_window(date_scope: str, now: datetime) -> tuple[datetime | None, datetime | None]:
    """Return (start, end) datetime window for the given date_scope.

    Valid scopes: "today", "tomorrow", "this_week".
    """
    if date_scope == "today":
        end = datetime.combine(now.date(), time.max, tzinfo=now.tzinfo)
        return now, end
    if date_scope == "tomorrow":
        tomorrow = now.date() + timedelta(days=1)
        start = datetime.combine(tomorrow, time.min, tzinfo=now.tzinfo)
        end = datetime.combine(tomorrow, time.max, tzinfo=now.tzinfo)
        return start, end
    if date_scope == "this_week":
        return now, now + timedelta(days=7)
    raise ValueError("date_scope must be one of: today, tomorrow, this_week")


# ===========================================================================
# Campus helpers
# ===========================================================================


def normalize_campus(value: Any) -> str | None:
    """Normalize a campus name to its canonical form."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return CAMPUS_ALIASES.get(stripped, stripped.removesuffix("校区"))


# ===========================================================================
# Text helpers
# ===========================================================================


def event_text(event: dict[str, Any]) -> str:
    """Build a searchable text string from an event dict."""
    tags = event.get("tags") if isinstance(event.get("tags"), list) else []
    values = [
        event.get("title"),
        event.get("summary"),
        event.get("location"),
        event.get("campus"),
        event.get("organizer"),
        event.get("source_name"),
        " ".join(str(tag) for tag in tags),
    ]
    return " ".join(str(value) for value in values if value)


def text_matches_any(text: str, terms: list[str]) -> bool:
    """Check if *any* term case-insensitively appears in text."""
    folded = text.casefold()
    return any(term.casefold() in folded for term in terms)


def has_online_signal(event: dict[str, Any]) -> bool:
    """Return True if the event appears to be online-only."""
    text = event_text(event)
    return any(token in text for token in ["线上", "直播", "腾讯会议", "Zoom"])


def normalize_string_list(value: Any) -> list[str]:
    """Normalize a list of strings, stripping whitespace and filtering empties."""
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def unique_terms(values: list[str]) -> list[str]:
    """Deduplicate a list of strings case-insensitively, preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


# ===========================================================================
# Interest / term helpers
# ===========================================================================


def extract_known_terms(text: str) -> list[str]:
    """Extract known interest terms found in text."""
    folded = text.casefold()
    return [term for term in KNOWN_INTEREST_TERMS if term.casefold() in folded]


def term_matches(term: str, haystack: str) -> bool:
    """Check if term (with aliases) matches haystack case-insensitively."""
    aliases = TERM_ALIASES.get(term, [term])
    folded = haystack.casefold()
    return any(alias.casefold() in folded for alias in aliases)
