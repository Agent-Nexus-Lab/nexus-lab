from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_TIMEZONE = timezone(timedelta(hours=8))
DEFAULT_EVENT_DURATION = timedelta(minutes=60)
SAME_CAMPUS_BUFFER_MINUTES = 15
UNKNOWN_COMMUTE_MINUTES = 60
MAX_PLAN_ITEMS = 4

CAMPUS_ALIASES = {
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

COMMUTE_MATRIX_MINUTES = {
    ("邯郸", "江湾"): 30,
    ("江湾", "邯郸"): 30,
    ("邯郸", "枫林"): 60,
    ("枫林", "邯郸"): 60,
}

KNOWN_INTEREST_TERMS = [
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

TERM_ALIASES = {
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

DATE_SCOPE_TITLES = {
    "today": "今天活动安排",
    "tomorrow": "明天活动安排",
    "this_week": "未来一周活动安排",
}


@dataclass(frozen=True)
class Candidate:
    event: dict[str, Any]
    start_time: datetime
    effective_end_time: datetime
    end_time_estimated: bool
    score: float
    score_components: dict[str, float]
    matched_terms: list[str]


def load_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_events(path: Path) -> list[dict[str, Any]]:
    payload = load_json_file(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError("events file must be a JSON object with an events array")
    return payload["events"]


def load_profile(path: Path) -> dict[str, Any]:
    payload = load_json_file(path)
    if not isinstance(payload, dict):
        raise ValueError("profile must be a JSON object")
    return payload


def parse_datetime(value: Any) -> datetime | None:
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


def parse_now(value: str | None) -> datetime:
    if value:
        parsed = parse_datetime(value)
        if parsed is None:
            raise ValueError("--now must be ISO 8601 with timezone, for example 2026-05-09T12:00:00+08:00")
        return parsed
    return datetime.now(DEFAULT_TIMEZONE)


def normalize_campus(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return CAMPUS_ALIASES.get(stripped, stripped.removesuffix("校区"))


def commute_minutes(from_campus: Any, to_campus: Any) -> int:
    source = normalize_campus(from_campus)
    target = normalize_campus(to_campus)
    if source and target and source == target:
        return SAME_CAMPUS_BUFFER_MINUTES
    if not source or not target:
        return UNKNOWN_COMMUTE_MINUTES
    return COMMUTE_MATRIX_MINUTES.get((source, target), UNKNOWN_COMMUTE_MINUTES)


def date_window(date_scope: str, now: datetime) -> tuple[datetime, datetime]:
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


def plan_day(
    *,
    events: list[dict[str, Any]],
    profile: dict[str, Any],
    request_text: str,
    date_scope: str,
    now: datetime,
    include_debug: bool = False,
    rewriter: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    window_start, window_end = date_window(date_scope, now)
    debug: dict[str, Any] = {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "rejections": [],
        "score_details": [],
        "commute_matrix_minutes": {
            "same_campus": SAME_CAMPUS_BUFFER_MINUTES,
            "邯郸->江湾": 30,
            "江湾->邯郸": 30,
            "邯郸->枫林": 60,
            "枫林->邯郸": 60,
            "unknown_cross_campus": UNKNOWN_COMMUTE_MINUTES,
        },
    }

    filtered = filter_candidates(
        events=events,
        profile=profile,
        request_text=request_text,
        now=now,
        window_start=window_start,
        window_end=window_end,
        rejections=debug["rejections"],
    )
    candidates = score_candidates(filtered, profile=profile, request_text=request_text, now=now)
    schedule = build_schedule(candidates, debug=debug)

    if not schedule:
        data: dict[str, Any] = {
            "run_id": run_id,
            "status": "failed",
            "plan_id": None,
            "title": None,
            "summary": None,
            "date_scope": date_scope,
            "items": None,
            "started_at": now.isoformat(),
            "ended_at": now.isoformat(),
            "error_message": "当前时间范围内没有找到匹配的活动",
        }
        if include_debug:
            data["debug"] = summarize_debug(debug, candidates)
        return {"code": 0, "data": data, "message": "ok"}

    data = {
        "run_id": run_id,
        "status": "completed",
        "plan_id": f"plan_{uuid.uuid4().hex[:8]}",
        "title": DATE_SCOPE_TITLES[date_scope],
        "summary": build_summary(schedule, profile, request_text),
        "date_scope": date_scope,
        "items": [render_item(candidate, index) for index, candidate in enumerate(schedule, start=1)],
        "started_at": now.isoformat(),
        "ended_at": now.isoformat(),
        "error_message": None,
    }
    if include_debug:
        data["debug"] = summarize_debug(debug, candidates, schedule)

    result = {"code": 0, "data": data, "message": "ok"}
    if rewriter is not None:
        result = apply_rewrite(result, rewriter, include_debug=include_debug)
    return result


def filter_candidates(
    *,
    events: list[dict[str, Any]],
    profile: dict[str, Any],
    request_text: str,
    now: datetime,
    window_start: datetime,
    window_end: datetime,
    rejections: list[dict[str, str]],
) -> list[dict[str, Any]]:
    requested_campuses = extract_requested_campuses(request_text)
    excluded_terms = normalize_string_list(profile.get("excluded_tags")) + normalize_string_list(profile.get("excluded_keywords"))
    filtered: list[dict[str, Any]] = []

    for event in events:
        event_id = str(event.get("event_id") or "")
        start_time = parse_datetime(event.get("start_time"))
        if start_time is None:
            reject(rejections, event, "missing_start_time")
            continue
        if start_time < now:
            reject(rejections, event, "past_event")
            continue
        if not (window_start <= start_time <= window_end):
            reject(rejections, event, "outside_date_scope")
            continue
        if not event.get("location") and not has_online_signal(event):
            reject(rejections, event, "missing_location")
            continue
        if not event.get("source_url") and not event.get("evidence_text"):
            reject(rejections, event, "missing_source_evidence")
            continue

        event_campus = normalize_campus(event.get("campus"))
        if requested_campuses and event_campus not in requested_campuses:
            reject(rejections, event, "campus_mismatch")
            continue
        if excluded_terms and text_matches_any(event_text(event), excluded_terms):
            reject(rejections, event, "excluded_preference")
            continue

        normalized = dict(event)
        normalized["event_id"] = event_id
        normalized["campus"] = event_campus or event.get("campus")
        filtered.append(normalized)
    return filtered


def score_candidates(
    events: list[dict[str, Any]],
    *,
    profile: dict[str, Any],
    request_text: str,
    now: datetime,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for event in events:
        start_time = parse_datetime(event.get("start_time"))
        if start_time is None:
            continue
        end_time = parse_datetime(event.get("end_time"))
        end_time_estimated = end_time is None or end_time <= start_time
        effective_end_time = end_time if end_time and end_time > start_time else start_time + DEFAULT_EVENT_DURATION
        interest_match, matched_terms = score_interest_match(event, profile, request_text)
        components = {
            "interest_match": interest_match,
            "time_fit": score_time_fit(start_time, profile, request_text),
            "campus_fit": score_campus_fit(event, profile, request_text),
            "source_reliability": score_source_reliability(event),
            "freshness": score_freshness(start_time, now),
        }
        score = (
            0.30 * components["interest_match"]
            + 0.25 * components["time_fit"]
            + 0.20 * components["campus_fit"]
            + 0.15 * components["source_reliability"]
            + 0.10 * components["freshness"]
        )
        candidates.append(
            Candidate(
                event=event,
                start_time=start_time,
                effective_end_time=effective_end_time,
                end_time_estimated=end_time_estimated,
                score=round(score, 4),
                score_components={key: round(value, 4) for key, value in components.items()},
                matched_terms=matched_terms,
            )
        )
    return sorted(candidates, key=lambda item: (-item.score, item.start_time, item.event.get("title") or ""))


def build_schedule(candidates: list[Candidate], *, debug: dict[str, Any], max_items: int | None = None) -> list[Candidate]:
    limit = max_items if max_items is not None else MAX_PLAN_ITEMS
    schedule: list[Candidate] = []
    for candidate in candidates:
        if len(schedule) >= limit:
            break
        conflict = schedule_conflict(schedule, candidate)
        if conflict:
            debug.setdefault("schedule_skips", []).append(
                {
                    "event_id": candidate.event.get("event_id"),
                    "title": candidate.event.get("title"),
                    "reason": conflict,
                }
            )
            continue
        schedule.append(candidate)
        schedule.sort(key=lambda item: item.start_time)
    return schedule


def schedule_conflict(schedule: list[Candidate], candidate: Candidate) -> str | None:
    timeline = sorted([*schedule, candidate], key=lambda item: item.start_time)
    for previous, current in zip(timeline, timeline[1:]):
        required_minutes = commute_minutes(previous.event.get("campus"), current.event.get("campus"))
        required_arrival_time = previous.effective_end_time + timedelta(minutes=required_minutes)
        if required_arrival_time > current.start_time:
            return (
                f"time_or_commute_conflict:{previous.event.get('event_id')}->{current.event.get('event_id')}"
                f":required_{required_minutes}min"
            )
    return None


def render_item(candidate: Candidate, display_order: int) -> dict[str, Any]:
    event = candidate.event
    item = {
        "event_id": event.get("event_id"),
        "title": event.get("title"),
        "summary": event.get("summary"),
        "start_time": event.get("start_time"),
        "end_time": event.get("end_time"),
        "location": event.get("location"),
        "campus": normalize_campus(event.get("campus")),
        "organizer": event.get("organizer"),
        "tags": event.get("tags") or [],
        "source_url": event.get("source_url"),
        "reason_text": build_reason_text(candidate),
        "display_order": display_order,
        "quality_score": round(candidate.score, 2),
    }
    return item


def build_summary(schedule: list[Candidate], profile: dict[str, Any], request_text: str) -> str:
    campuses = sorted({normalize_campus(item.event.get("campus")) for item in schedule if normalize_campus(item.event.get("campus"))})
    matched = sorted({term for item in schedule for term in item.matched_terms})
    campus_text = "、".join(campuses) if campuses else "多个校区"
    matched_text = "、".join(matched[:3]) if matched else "你的偏好"
    return f"为你安排了 {len(schedule)} 个活动，主要匹配 {matched_text}，地点集中在 {campus_text}。"


def build_reason_text(candidate: Candidate) -> str:
    parts: list[str] = []
    if candidate.matched_terms:
        parts.append(f"匹配 {', '.join(candidate.matched_terms[:3])}")
    campus = normalize_campus(candidate.event.get("campus"))
    if campus:
        parts.append(f"校区为{campus}")
    parts.append(f"规则评分 {candidate.score:.2f}")
    if candidate.end_time_estimated:
        parts.append("结束时间未明确，冲突检查按60分钟估算")
    return "；".join(parts) + "。"


def apply_rewrite(
    result: dict[str, Any],
    rewriter: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    include_debug: bool,
) -> dict[str, Any]:
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, dict) or data.get("status") != "completed":
        return result
    debug = data.setdefault("debug", {}) if include_debug else {}
    try:
        rewrite = rewriter(result)
    except Exception as exc:  # pragma: no cover - exercised by CLI usage
        if include_debug:
            debug["llm_error"] = str(exc)
        return result

    if isinstance(rewrite.get("summary"), str) and rewrite["summary"].strip():
        data["summary"] = rewrite["summary"].strip()

    items = data.get("items")
    if not isinstance(items, list):
        return result
    items_by_id = {item.get("event_id"): item for item in items if isinstance(item, dict)}
    invalid_ids: list[str] = []
    for reason in rewrite.get("reasons", []):
        if not isinstance(reason, dict):
            continue
        event_id = reason.get("event_id")
        text = reason.get("reason_text")
        if event_id not in items_by_id:
            invalid_ids.append(str(event_id))
            continue
        if isinstance(text, str) and text.strip():
            items_by_id[event_id]["reason_text"] = text.strip()
    if include_debug and invalid_ids:
        debug["llm_invalid_event_ids"] = invalid_ids
    return result


def summarize_debug(
    debug: dict[str, Any],
    candidates: list[Candidate],
    schedule: list[Candidate] | None = None,
) -> dict[str, Any]:
    rejections = debug.get("rejections", [])
    summary = dict(debug)
    summary["rejection_counts"] = dict(Counter(item.get("reason", "unknown") for item in rejections))
    summary["score_details"] = [
        {
            "event_id": candidate.event.get("event_id"),
            "title": candidate.event.get("title"),
            "score": candidate.score,
            "components": candidate.score_components,
            "matched_terms": candidate.matched_terms,
            "source_file": candidate.event.get("source_file"),
            "evidence_text": candidate.event.get("evidence_text"),
            "effective_end_time": candidate.effective_end_time.isoformat(),
            "end_time_estimated": candidate.end_time_estimated,
        }
        for candidate in candidates
    ]
    if schedule is not None:
        summary["selected_event_ids"] = [candidate.event.get("event_id") for candidate in schedule]
    return summary


def score_interest_match(event: dict[str, Any], profile: dict[str, Any], request_text: str) -> tuple[float, list[str]]:
    targets = build_interest_targets(profile, request_text)
    if not targets:
        return 0.0, []
    haystack = event_text(event)
    matched = [term for term in targets if term_matches(term, haystack)]
    denominator = min(3, len(targets))
    return min(1.0, len(matched) / denominator), matched


def build_interest_targets(profile: dict[str, Any], request_text: str) -> list[str]:
    terms: list[str] = []
    terms.extend(normalize_string_list(profile.get("interest_tags")))
    terms.extend(normalize_string_list(profile.get("activity_style_tags")))
    terms.extend(extract_known_terms(request_text))
    terms.extend(extract_known_terms(str(profile.get("profile_summary") or "")))
    return unique_terms(terms)


def extract_known_terms(text: str) -> list[str]:
    folded = text.casefold()
    return [term for term in KNOWN_INTEREST_TERMS if term.casefold() in folded]


def term_matches(term: str, haystack: str) -> bool:
    aliases = TERM_ALIASES.get(term, [term])
    folded = haystack.casefold()
    return any(alias.casefold() in folded for alias in aliases)


def score_time_fit(start_time: datetime, profile: dict[str, Any], request_text: str) -> float:
    text = f"{profile.get('available_time') or ''} {request_text}"
    hour = start_time.hour + start_time.minute / 60
    scores: list[float] = []
    if any(token in text for token in ["晚上", "晚间", "今晚", "夜间"]):
        scores.append(1.0 if 18 <= hour <= 22 else 0.7 if 17 <= hour < 18 or 22 < hour <= 23 else 0.2)
    if "下午" in text:
        scores.append(1.0 if 13 <= hour <= 18 else 0.5 if 12 <= hour < 13 or 18 < hour <= 19 else 0.2)
    if "上午" in text:
        scores.append(1.0 if 8 <= hour <= 12 else 0.4)
    if "周末" in text:
        scores.append(1.0 if start_time.weekday() >= 5 else 0.4)
    return max(scores) if scores else 0.7


def score_campus_fit(event: dict[str, Any], profile: dict[str, Any], request_text: str) -> float:
    event_campus = normalize_campus(event.get("campus"))
    requested = extract_requested_campuses(request_text)
    preferred = {normalize_campus(item) for item in normalize_string_list(profile.get("preferred_campuses"))}
    preferred.discard(None)
    home = normalize_campus(profile.get("campus"))
    if requested:
        return 1.0 if event_campus in requested else 0.0
    if preferred and event_campus in preferred:
        return 1.0
    if home and event_campus == home:
        return 0.9
    if preferred or home:
        return 0.45
    return 0.6


def score_source_reliability(event: dict[str, Any]) -> float:
    score = 0.35
    if event.get("source_url"):
        score += 0.35
    if event.get("evidence_text"):
        score += 0.2
    if event.get("source_file"):
        score += 0.1
    if event.get("source_name") or event.get("organizer"):
        score += 0.1
    return min(1.0, score)


def score_freshness(start_time: datetime, now: datetime) -> float:
    days_until = max(0.0, (start_time - now).total_seconds() / 86400)
    return max(0.0, 1.0 - min(days_until, 7.0) / 7.0)


def extract_requested_campuses(text: str) -> set[str]:
    campuses: set[str] = set()
    for alias, campus in CAMPUS_ALIASES.items():
        if alias != "其他" and alias in text:
            campuses.add(campus)
    return campuses


def has_online_signal(event: dict[str, Any]) -> bool:
    text = event_text(event)
    return any(token in text for token in ["线上", "直播", "腾讯会议", "Zoom"])


def event_text(event: dict[str, Any]) -> str:
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
    folded = text.casefold()
    return any(term.casefold() in folded for term in terms)


def normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def unique_terms(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def reject(rejections: list[dict[str, str]], event: dict[str, Any], reason: str) -> None:
    rejections.append(
        {
            "event_id": str(event.get("event_id") or ""),
            "title": str(event.get("title") or ""),
            "reason": reason,
        }
    )
