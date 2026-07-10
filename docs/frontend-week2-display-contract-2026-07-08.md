# 2026-07-08 Frontend Display Contract

This note closes the frontend part of the July second-week handoff. It records the fields the miniprogram is ready to display without faking successful collection data.

## Data Health Panel

`GET /api/admin/data-health` is displayed on the loading page in development mode.

Required or preferred fields:

| Field | Empty State | Success State | Failure/Warning State |
|---|---|---|---|
| `future_events_7d` | Show `0` or backend value | Show metric card | If alerts mention low count, show alert chip |
| `future_events_14d` | Show `0` or backend value | Show metric card | If alerts mention low count, show alert chip |
| `alerts` | No alert list | Show no warning if empty | Render every alert from backend |
| `last_collection_time` | `暂无记录` | `MM-DD HH:mm` | Keep raw value if date parsing fails |
| `last_collection_result` | `unknown` | Render beside timestamp | Alert if backend marks failed-like status |
| `sources_breakdown` | `暂无来源统计` | Render as `source count` summary | Still render if partial |

## Collection Logs

The frontend expects `collection_logs` to be optional. If absent or empty, it renders `暂无采集日志记录` and does not pretend that collection succeeded.

Preferred log fields:

| Display | Accepted Backend Field Names |
|---|---|
| Batch | `batch_id`, `id`, `log_id` |
| Trigger time | `triggered_at`, `started_at`, `created_at`, `collection_time`, `time` |
| Trigger method | `trigger_method`, `trigger`, `triggered_by`, `mode` |
| Source | `source_name`, `source`, `account`, `source_url` |
| Fetched articles | `fetched_count`, `fetched_articles`, `article_count`, `fetchedArticleCount` |
| Extracted events | `extracted_count`, `extracted_events`, `event_draft_count`, `extractedEventCount` |
| Imported events | `imported_count`, `inserted_count`, `upserted_count`, `importedEventCount` |
| Failure reason | `failure_reason`, `error_message`, `error`, `failed_reason` |

## Result Cards

Result cards display the stable event fields:

```text
title, summary, start_time, end_time, location, campus, organizer, tags,
source_name, source_url, reason_text, quality_score, score, event_id,
plan_id, plan_item_id, run_id
```

Fallback behavior:

| Missing Field | UI Fallback |
|---|---|
| `title` | `未命名活动` |
| `summary` | `暂无简介` |
| `start_time` / `end_time` | `时间待确认` |
| `location` | `地点待确认` |
| `campus` | `校区待确认` |
| `organizer` | `主办方待确认` |
| `source_url` | `暂无来源链接` |
| `reason_text` | `暂无推荐理由` |
| `quality_score` | falls back to `score`, then `待评估` |

`source_url` renders as a clickable source entry when it starts with `http://` or `https://`. Opening it also sends `clicked_source` feedback in the background.

## Recommendation Explanation Slots

The result page is ready for these optional explanation fields:

| Field | UI Behavior |
|---|---|
| `score_components` | Render up to six compact score chips |
| `semantic_interest_match` / `interest_match` / `semantic_similarity` | Render as semantic match reason |
| `memory_reason` / `memory_boost` / `memory_penalty` | Render as memory reason |
| `repeat_penalty` / `penalty_reason` / `rejection_reason` | Render as down-rank reason |
| `score_reasons` / `reasons` | Render as extra explanation chips |

The page also accepts an optional `answer_composer` object:

```json
{
  "summary": "string",
  "recommended_items": ["string"],
  "tradeoffs": ["string"],
  "follow_up_question": "string"
}
```

If no composer fields are present, the panel is hidden.

## Recording Script

Use these scripts when the backend links are ready.

### Script A: Before Collection

1. Open the miniprogram and start a plan request.
2. On loading, pause long enough to show `data-health`.
3. Capture `future_events_7d`, `future_events_14d`, alerts, and `暂无采集日志记录` if logs are still empty.
4. State clearly that this is pre-collection state, not a successful collection proof.

### Script B: After Collection

1. Ask backend to trigger `auto_collector commit` or `collection_cron` once.
2. Generate again.
3. On loading, show `data-health` metrics after import.
4. Show the latest collection log row with batch, trigger method, source, fetched/extracted/imported counts, and failure reason if any.

### Script C: Recommendation Result

1. Continue to the result page.
2. Show at least one newly imported activity if backend search/scoring returns it.
3. Show title, summary, time, location, source link, score reason, and feedback buttons.
4. Click `查看来源`; confirm the source opens and the app remains usable.
5. Return and click `不感兴趣`; confirm success toast or capture the failure toast for backend debugging.

## Current Boundary

Frontend does not implement EventImportService, cron, embeddings, or actual collection success. Those are backend/search responsibilities. The frontend only reflects the fields returned by the API and keeps empty/failure states honest.
