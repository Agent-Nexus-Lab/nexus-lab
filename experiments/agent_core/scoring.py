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

        # --- Memory-based additive adjustments (soft, do NOT reject) ---
        adjust: dict[str, float] = {}

        # Repeat penalty: -0.15 if this event was recently recommended
        if preferences.penalty_event_ids:
            event_id = str(event.get("event_id", ""))
            if event_id and event_id in preferences.penalty_event_ids:
                adjust["repeat_penalty"] = -0.15

        # Disliked / liked / keyword adjustments — compute haystack once
        haystack: str | None = None

        def _ensure_haystack() -> str:
            nonlocal haystack
            if haystack is None:
                haystack = event_text(event)
            return haystack

        # Disliked tag penalty: -0.10 per matched tag, cap -0.20
        if preferences.penalty_disliked_tags:
            disliked_matches = sum(
                1 for tag in preferences.penalty_disliked_tags
                if term_matches(tag, _ensure_haystack())
            )
            if disliked_matches:
                adjust["disliked_penalty"] = round(-0.10 * min(disliked_matches, 2), 4)

        # Negative keyword penalty: -0.10 per matched keyword, cap -0.20
        if preferences.penalty_negative_keywords:
            txt = _ensure_haystack().casefold()
            kw_matches = sum(
                1 for kw in preferences.penalty_negative_keywords
                if kw.casefold() in txt
            )
            if kw_matches:
                adjust["keyword_penalty"] = round(-0.10 * min(kw_matches, 2), 4)

        # Liked tag boost: +0.10 per matched tag, cap +0.20
        if preferences.boost_liked_tags:
            liked_matches = sum(
                1 for tag in preferences.boost_liked_tags
                if term_matches(tag, _ensure_haystack())
            )
            if liked_matches:
                adjust["liked_boost"] = round(0.10 * min(liked_matches, 2), 4)

        # Apply adjustments and clamp to [0, 1]
        final_score = total_score + sum(adjust.values())
        final_score = max(0.0, min(1.0, final_score))

        # Merge base components + memory adjustments into score_components
        full_components = {**components, **adjust}

        candidates.append(MatchedEvent(
            event=event,
            score=round(final_score, 4),
            score_components={k: round(v, 4) for k, v in full_components.items()},
            matched_terms=matched_terms,
        ))

    # Sort by score descending, then by start_time ascending, then by title
    return sorted(
        candidates,
        key=lambda m: (-m.score, parse_datetime(m.event.get("start_time")) or now, m.event.get("title") or ""),
    )


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
