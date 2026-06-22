"""Soft-preference scoring adapted from runtime.py score_candidates().

Scoring influences ranking but does NOT reject events. The five dimensions
mirror the existing runtime scoring with the same weights.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent_core._runtime_compat import (
    CAMPUS_ALIASES,
    KNOWN_INTEREST_TERMS,
    TERM_ALIASES,
    event_text,
    extract_known_terms,
    normalize_campus,
    normalize_string_list,
    parse_datetime,
    term_matches,
)

from agent_core.query import MatchedEvent, SoftPreferences  # noqa: E402


# ---------------------------------------------------------------------------
# Scoring weights (same as runtime.py)
# ---------------------------------------------------------------------------

WEIGHTS = {
    "interest_match": 0.30,
    "time_fit": 0.25,
    "campus_fit": 0.20,
    "source_reliability": 0.15,
    "freshness": 0.10,
}


# ---------------------------------------------------------------------------
# Individual scoring functions
# ---------------------------------------------------------------------------


def score_interest_match(
    event: dict[str, Any],
    preferences: SoftPreferences,
) -> tuple[float, list[str]]:
    """Score how well the event matches interest terms.

    Returns (score 0..1, list of matched terms).
    Mirrors runtime.py score_interest_match (line 498).
    """
    targets = list(preferences.interest_terms)
    if not targets:
        return 0.0, []

    haystack = event_text(event)
    matched = [term for term in targets if term_matches(term, haystack)]
    denominator = min(3, len(targets))
    return min(1.0, len(matched) / denominator), matched


def score_time_fit(
    start_time: datetime,
    preferences: SoftPreferences,
) -> float:
    """Score how well the event time fits the user's availability.

    Mirrors runtime.py score_time_fit (line 528).
    """
    text = preferences.preferred_time_of_day
    hour = start_time.hour + start_time.minute / 60.0

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


def score_campus_fit(
    event: dict[str, Any],
    preferences: SoftPreferences,
    *,
    home_campus: str | None = None,
    requested_campuses: set[str] | None = None,
) -> float:
    """Score how well the event campus matches user preferences.

    Mirrors runtime.py score_campus_fit (line 543).
    """
    event_campus = normalize_campus(event.get("campus"))
    preferred = {normalize_campus(c) for c in preferences.preferred_campuses}
    preferred.discard(None)
    home = normalize_campus(home_campus) if home_campus else None

    if requested_campuses:
        return 1.0 if event_campus in requested_campuses else 0.0
    if preferred and event_campus in preferred:
        return 1.0
    if home and event_campus == home:
        return 0.9
    if preferred or home:
        return 0.45
    return 0.6


def score_source_reliability(event: dict[str, Any]) -> float:
    """Score source reliability based on metadata completeness.

    Mirrors runtime.py score_source_reliability (line 560).
    """
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
    """Score how soon the event is happening.

    Mirrors runtime.py score_freshness (line 573).
    """
    from agent_core.freshness import event_freshness_score
    return event_freshness_score(start_time, now)


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------


def score_and_sort(
    events: list[dict[str, Any]],
    *,
    preferences: SoftPreferences,
    now: datetime,
    home_campus: str | None = None,
    requested_campuses: set[str] | None = None,
) -> list[MatchedEvent]:
    """Score all events against soft preferences, return sorted by score descending.

    This replaces the inline score_candidates() logic in runtime.py (line 313).
    """
    # --- Pre-processing: extract tags from liked/disliked event IDs ---
    extra_boost_tags: set[str] = set()
    extra_penalty_tags: set[str] = set()
    if preferences.boost_liked_event_ids or preferences.penalty_disliked_event_ids:
        for evt in events:
            eid = str(evt.get("event_id", ""))
            tags = tuple(t for t in (evt.get("tags") or []) if isinstance(t, str))
            if eid in preferences.boost_liked_event_ids:
                extra_boost_tags.update(tags)
            if eid in preferences.penalty_disliked_event_ids:
                extra_penalty_tags.update(tags)

    # Merge explicit tags with event-derived tags
    all_boost_tags = set(preferences.boost_liked_tags) | extra_boost_tags
    all_disliked_tags = set(preferences.penalty_disliked_tags) | extra_penalty_tags

    candidates: list[MatchedEvent] = []
    for event in events:
        start_time = parse_datetime(event.get("start_time"))
        if start_time is None:
            # Events without start_time get scored low but not rejected
            start_time = now

        interest_match, matched_terms = score_interest_match(event, preferences)

        components = {
            "interest_match": interest_match,
            "time_fit": score_time_fit(start_time, preferences),
            "campus_fit": score_campus_fit(
                event,
                preferences,
                home_campus=home_campus,
                requested_campuses=requested_campuses,
            ),
            "source_reliability": score_source_reliability(event),
            "freshness": score_freshness(start_time, now),
        }

        total_score = sum(WEIGHTS[k] * components[k] for k in WEIGHTS)

        # --- Memory-based soft adjustments with explainability ---
        mem_adjust: dict[str, float] = {}
        mem_matched_terms: list[str] = []
        mem_details: list[dict[str, Any]] = []

        event_id = str(event.get("event_id", ""))
        haystack = event_text(event)

        # 1. Repeat penalty
        if preferences.penalty_event_ids and event_id and event_id in preferences.penalty_event_ids:
            mem_adjust["repeat_penalty"] = -0.15
            mem_matched_terms.append(f"重复推荐:{event_id}")
            mem_details.append({
                "type": "repeat_penalty",
                "delta": -0.15,
                "matched": event_id,
                "matched_field": "event_id",
                "source": "recent_plan_event_ids",
                "reason": f"近期已推荐过活动 {event_id}",
            })

        # 2. Disliked tag penalty (tag aliases, from explicit + event-derived)
        if all_disliked_tags:
            matched_disliked: list[str] = []
            for tag in sorted(all_disliked_tags):
                if term_matches(tag, haystack):
                    # Determine which field matched
                    tag_lower = tag.casefold()
                    matched_field = "tags"
                    if tag_lower in (event.get("title") or "").casefold():
                        matched_field = "title"
                    elif tag_lower in (event.get("summary") or "").casefold():
                        matched_field = "summary"
                    source = "disliked_tags" if tag in preferences.penalty_disliked_tags else "disliked_event_ids"
                    matched_disliked.append(tag)
                    mem_matched_terms.append(f"排除:{tag}")
                    mem_details.append({
                        "type": "disliked_penalty",
                        "delta": -0.10,
                        "matched": tag,
                        "matched_field": matched_field,
                        "source": source,
                        "reason": "命中不感兴趣标签: " + tag,
                    })
            if matched_disliked:
                raw = -0.10 * len(matched_disliked)
                mem_adjust["disliked_penalty"] = round(max(-0.20, raw), 4)
            # Collect casefolded matched tags for keyword_penalty dedup
            matched_disliked_folded: set[str] = {t.casefold() for t in matched_disliked}
        else:
            matched_disliked_folded: set[str] = set()

        # 3. Negative keyword penalty (raw substring, no aliases)
        #    Skip keywords already penalized by disliked_penalty (dedup)
        if preferences.penalty_negative_keywords:
            txt = haystack.casefold()
            matched_kws: list[str] = []
            for kw in preferences.penalty_negative_keywords:
                if kw.casefold() in matched_disliked_folded:
                    continue  # already penalized via disliked_penalty
                if kw.casefold() in txt:
                    kw_lower = kw.casefold()
                    matched_field = "title" if kw_lower in (event.get("title") or "").casefold() else "summary"
                    matched_kws.append(kw)
                    mem_matched_terms.append(f"排除:{kw}")
                    mem_details.append({
                        "type": "keyword_penalty",
                        "delta": -0.10,
                        "matched": kw,
                        "matched_field": matched_field,
                        "source": "negative_keywords",
                        "reason": "命中负向关键词: " + kw,
                    })
            if matched_kws:
                raw = -0.10 * len(matched_kws)
                mem_adjust["keyword_penalty"] = round(max(-0.20, raw), 4)

        # 4. Liked tag boost (tag aliases, from explicit + event-derived)
        if all_boost_tags:
            matched_liked: list[str] = []
            for tag in sorted(all_boost_tags):
                if term_matches(tag, haystack):
                    tag_lower = tag.casefold()
                    matched_field = "tags"
                    if tag_lower in (event.get("title") or "").casefold():
                        matched_field = "title"
                    elif tag_lower in (event.get("summary") or "").casefold():
                        matched_field = "summary"
                    source = "liked_tags" if tag in preferences.boost_liked_tags else "liked_event_ids"
                    matched_liked.append(tag)
                    mem_matched_terms.append(f"喜欢:{tag}")
                    mem_details.append({
                        "type": "liked_boost",
                        "delta": 0.10,
                        "matched": tag,
                        "matched_field": matched_field,
                        "source": source,
                        "reason": "命中喜欢标签: " + tag,
                    })
            if matched_liked:
                raw = 0.10 * len(matched_liked)
                mem_adjust["liked_boost"] = round(min(0.20, raw), 4)

        # --- Compute total_memory_delta with cap [-0.30, +0.20] ---
        raw_delta = sum(mem_adjust.values())
        total_memory_delta = round(max(-0.30, min(0.20, raw_delta)), 4)

        # --- Build explanation ---
        explanation = _build_memory_explanation(mem_adjust, mem_matched_terms, total_memory_delta)

        # --- Build nested memory component ---
        memory_component: dict[str, Any] = {
            "total_memory_delta": total_memory_delta,
            "matched_memory_terms": mem_matched_terms,
            "explanation": explanation,
            "details": mem_details,
        }
        # Include individual adjustment keys (only non-zero ones)
        for k, v in mem_adjust.items():
            memory_component[k] = v

        # --- Final score ---
        final_score = total_score + total_memory_delta
        final_score = max(0.0, min(1.0, final_score))

        # --- score_components: 5 base dims + nested memory ---
        full_components: dict[str, Any] = {
            **components,
            "memory": memory_component,
        }

        candidates.append(MatchedEvent(
            event=event,
            score=round(final_score, 4),
            score_components={k: round(v, 4) if isinstance(v, (int, float)) else v
                              for k, v in full_components.items()},
            matched_terms=matched_terms,
        ))

    # Sort by score descending, then by start_time ascending, then by title
    return sorted(
        candidates,
        key=lambda m: (-m.score, parse_datetime(m.event.get("start_time")) or now, m.event.get("title") or ""),
    )


# ---------------------------------------------------------------------------
# Utility: build memory explanation text
# ---------------------------------------------------------------------------


def _build_memory_explanation(
    mem_adjust: dict[str, float],
    mem_matched_terms: list[str],
    total_memory_delta: float,
) -> str:
    """Build a human-readable Chinese explanation of memory adjustments."""
    if not mem_adjust:
        return ""

    parts: list[str] = []

    # Positive signals
    liked_terms = [t.replace("喜欢:", "") for t in mem_matched_terms if t.startswith("喜欢:")]
    if liked_terms:
        parts.append("命中喜欢标签: " + "、".join(liked_terms))

    # Negative tag signals
    if "disliked_penalty" in mem_adjust:
        # Collect terms that triggered disliked_penalty (tag matching, not keyword)
        # We use mem_matched_terms entries that are "排除:X" where X matches a tag-alias
        disliked = [t.replace("排除:", "") for t in mem_matched_terms if t.startswith("排除:")]
        if disliked:
            parts.append("命中不感兴趣标签: " + "、".join(disliked))

    # Keyword-specific signal (only if separate from disliked tags)
    if "keyword_penalty" in mem_adjust:
        parts.append("命中负向关键词")

    # Repeat
    if "repeat_penalty" in mem_adjust:
        parts.append("近期已推荐过，降权")

    if not parts:
        return ""

    # Conclusion
    if total_memory_delta > 0:
        conclusion = f"综合正向影响 +{total_memory_delta:.2f}"
    elif total_memory_delta < 0:
        conclusion = f"综合负向影响 {total_memory_delta:.2f}"
    else:
        conclusion = "正负影响抵消"

    return "；".join(parts) + f"。{conclusion}"


# ---------------------------------------------------------------------------
# Utility: extract requested campuses from request text
# ---------------------------------------------------------------------------


def extract_requested_campuses(text: str) -> set[str]:
    """Extract campus mentions from natural language text.

    Mirrors runtime.py extract_requested_campuses (line 578).
    """
    campuses: set[str] = set()
    for alias, campus in CAMPUS_ALIASES.items():
        if alias != "其他" and alias in text:
            campuses.add(campus)
    return campuses
