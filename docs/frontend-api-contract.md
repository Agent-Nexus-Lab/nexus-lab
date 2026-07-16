# Frontend API Contract

This document records the current miniprogram frontend dependencies on backend API fields.

## Base URL

```text
http://1.117.75.184:8000/api
```

## POST /api/profile

Frontend request fields:

| Field | Type | Note |
|---|---|---|
| `nickname` | string | Fixed to `微信用户` for T0 |
| `campus` | string | Single selected campus |
| `identity` | string | Single selected identity |
| `raw_preference_text` | string | Free-form preference text |
| `interest_tags` | string[] | Multi-selected interests |
| `preferred_campuses` | string[] | Currently derived from `campus` |
| `available_time` | string | Multi-selected times joined by `、` |
| `activity_style_tags` | string[] | Multi-selected activity styles |
| `profile_summary` | string | Empty string for now |

## POST /api/agent/plan-day

Frontend request fields:

| Field | Type | Note |
|---|---|---|
| `request_text` | string | Natural-language schedule request |
| `date_scope` | string | `today` / `tomorrow` / `this_week` |

Frontend response dependencies:

| Field | Note |
|---|---|
| `code` | `0` means success |
| `data.run_id` | Required for polling |
| `data.status` | Initial status, usually `queued` or `running` |

## GET /api/agent/runs/{run_id}

The frontend follows the MVP `plan_runs` state machine:

| `data.status` | Frontend behavior |
|---|---|
| `queued` | Keep loading and polling |
| `running` | Keep loading and polling |
| `completed` | Stop polling and navigate to the result page |
| `failed` | Stop polling and show `error_message` |

The frontend no longer treats non-empty `items` as a completed run. Completion is based on `status === "completed"`.

Optional runtime fields:

| Field | Frontend behavior |
|---|---|
| `data.stage` | Drives the Agent progress steps when present |
| `data.stage_message` | Highest-priority loading copy. If present, the frontend displays it directly |
| `data.progress` | Numeric progress in `0.0 - 1.0`; the frontend converts it to percent for display and still tolerates legacy `0 - 100` values |
| `data.cache_hit` | When `true`, loading displays `命中缓存，正在返回上次可复用结果` |
| `data.debug` | Shown in the loading failure state and result page when present and `ENABLE_DEBUG_VIEW` is enabled |
| `data.error_message` | Shown when the run enters `failed` |
| `data.plan_id` | Preserved for result feedback and history |
| `data.run_id` | Preserved for result feedback and history |

Reserved progress steps:

1. `正在理解需求`
2. `正在读取记忆`
3. `正在检索活动`
4. `正在编排日程`
5. `正在整理推荐理由`

Without `data.stage`, the loading page shows a generic queued/running state and does not simulate stage progress. Recognized stage aliases include `intent_parsing`, `load_profile`, `read_memory`, `load_memory`, `search_events`, `filter_and_score`, `build_schedule`, `rewrite_plan`, `save_plan`, and `cache_hit`.

The loading page also recognizes cache flags in these locations:

```text
data.cache_hit
data.debug.cache_hit
data.debug.cache.cache_hit
```

Failed runs should return `data.error_message` and, in development mode, one of these debug fields when available:

```text
debug.rejection_reason
debug.error_message
debug.error
debug.llm_rewrite.error
```

If `debug.rejections` is an array, the loading page renders each rejection as a structured failure item. If `debug.llm_rewrite.error` or `debug.rewrite_error` is present together with `used_fallback=true`, the loading page renders it as copy fallback information instead of treating it as the whole plan-day failure reason.

## GET /api/admin/data-health

The loading page debug panel displays collection health using these fields:

| Field | UI behavior |
|---|---|
| `total_events` | Total event count metric |
| `future_events_7d` | Future 7-day event count metric |
| `future_events_14d` | Future 14-day event count metric |
| `last_collection_time` | Rendered as the latest collection timestamp |
| `last_collection_result` | Rendered beside the latest timestamp |
| `sources_breakdown` | Rendered as `source count` summary |
| `alerts` | Rendered as warning chips/list |
| `collection_logs` | Optional list. If absent or empty, frontend shows `暂无采集日志记录` |

## Completed Result Fields

When `status === "completed"`, the frontend reads `data.items`. If `items` is `null` or not an array, it is rendered as an empty array.

| Backend field | UI usage | Fallback |
|---|---|---|
| `title` | Event title | `未命名活动` |
| `summary` | Event summary | `暂无简介` |
| `start_time` / `end_time` | Time range | `时间待确认` |
| `location` | Location | `地点待确认` |
| `campus` | Campus | `校区待确认` |
| `organizer` | Organizer | `主办方待确认` |
| `tags` | Tag chips | Empty when not an array |
| `source_url` | Source link | `暂无来源链接` |
| `reason_text` | Recommendation reason | `暂无推荐理由` |
| `display_order` | Order number | `0` |
| `quality_score` | Quality score | `待评估` |
| `event_id` | Feedback association | Empty string |
| `plan_item_id` | Feedback association | Empty string until backend provides it |
| `plan_id` | Feedback association | Falls back to top-level `plan_id` |
| `run_id` | Feedback association | Falls back to top-level `run_id` |

Time parsing supports ISO datetime strings, datetime strings with a space separator, and plain `HH:mm`.

## POST /api/feedback/event

The result page sends activity-level feedback from three entry points:

| UI entry | `feedback_type` | Behavior |
|---|---|---|
| `喜欢` | `like` | Optimistically marks the card as liked; rolls back on failure |
| `不感兴趣` | `dislike` | Optimistically marks the card as reduced; rolls back on failure |
| `查看来源` | `clicked_source` | Sends feedback in the background, then opens the source page |

Frontend request fields:

| Field | Type | Note |
|---|---|---|
| `event_id` | string | From item `event_id`; may fall back to item `id` during transition |
| `plan_id` | string | From item or top-level result |
| `plan_item_id` | string | From item `plan_item_id`; empty if backend has not added it |
| `run_id` | string | From item or top-level result |
| `feedback_type` | string | `like` / `dislike` / `clicked_source` |
| `feedback_source` | string | Fixed to `result_card` |
| `metadata` | object | Includes feedback type, title, tags, source URL, display order |

## History Placeholder

The miniprogram now has a placeholder `pages/history/history` entry. Until `GET /api/plans` is stable, the page reads a local `planHistoryDraft` list written after a successful completed run. The fields mirror the planned history list shape: `plan_id`, `run_id`, `title`, `date_scope`, `request_text`, `item_count`, `status`, and `created_at`.

## Streaming Plan-Day Flow

The user-facing generation flow now tries chunked streaming first and falls back to the stable polling flow when streaming is unavailable.

Preferred path:

```text
POST /api/agent/stream-plan-day
```

The miniprogram calls `api.streamPlanDay()` with `wx.request({ enableChunked: true })` and listens through `task.onChunkReceived`. The loading page accepts common streaming shapes:

```text
{"stage":"search_events","stage_message":"正在检索活动","progress":45}
data: {"status":"running","stage":"build_schedule"}
{"status":"completed","items":[...]}
{"status":"failed","error_message":"..."}
```

Fallback path:

```text
POST /api/agent/plan-day
GET /api/agent/runs/{run_id}
```

If `/api/agent/stream-plan-day` returns HTTP 404/500, the WeChat base library does not support `onChunkReceived`, or the stream closes without a completed result, the loading page creates a normal run and continues polling. This keeps the formal demo stable while allowing real-time stage/message updates when the backend stream is ready.

`pages/stream-demo/stream-demo` remains as a dev-only diagnostic page for testing arbitrary chunked endpoints.

## 2026-07-08 Display Contract Addendum

The second-week frontend display work adds tolerant rendering for collection and recommendation explanation fields.

### Collection Logs

`GET /api/admin/data-health` may include `collection_logs`. The loading page now accepts these field aliases:

| UI Display | Field Aliases |
|---|---|
| Batch | `batch_id`, `id`, `log_id` |
| Trigger time | `triggered_at`, `started_at`, `created_at`, `collection_time`, `time` |
| Trigger method | `trigger_method`, `trigger`, `triggered_by`, `mode` |
| Source | `source_name`, `source`, `account`, `source_url` |
| Fetched articles | `fetched_count`, `fetched_articles`, `article_count`, `fetchedArticleCount` |
| Extracted events | `extracted_count`, `extracted_events`, `event_draft_count`, `extractedEventCount` |
| Imported events | `imported_count`, `inserted_count`, `upserted_count`, `importedEventCount` |
| Failure reason | `failure_reason`, `error_message`, `error`, `failed_reason` |

If `collection_logs` is missing or empty, the frontend renders `暂无采集日志记录` and does not fake a successful collection.

### Result Explanations

Result cards now preserve `source_name`, render `source_url` as a clickable source entry when it is an HTTP URL, and reserve visible slots for scoring explanations.

Accepted optional fields:

```text
score_components, semantic_interest_match, interest_match, semantic_similarity,
memory_reason, memory_boost, memory_penalty, repeat_penalty, penalty_reason,
rejection_reason, score_reasons, reasons
```

Top-level result data may include `answer_composer` with:

```text
summary, recommended_items, tradeoffs, follow_up_question
```

If these fields are absent, the UI hides the composer/explanation panels and keeps the current card display unchanged.

## 2026-07-09 Memory Summary Display

The miniprogram now includes `pages/memory/memory` for the frontend part of the memory_summary acceptance task.

### GET /api/memory

The page calls:

```text
GET /api/memory?status=active&page=1&page_size=50
```

Accepted response shape:

| Field | UI behavior |
|---|---|
| `data.items` | Active memory list. Missing or non-array values render as empty state |
| `memory_id` | Used for delete action |
| `memory_type` | Rendered as human-readable memory title; `memory_summary` is preferred as the summary card |
| `memory_scope` | Rendered in the memory item subtitle |
| `content` | Main memory text. Fallback: `暂无记忆内容` |
| `structured_content.memory_strength` / `structured_content.strength` / `confidence` | Rendered as strength percent |
| `structured_content.source_refs` / `source_ref` | Rendered as source summary |
| `structured_content.expires_after_turns` / `expires_at` | Rendered as decay or expiry text |
| `structured_content.cleanup_reason` | Rendered as cleanup/deletion explanation |
| `updated_at` | Rendered as latest update time |

If no `memory_summary` item exists yet, the page still displays the first active memory item as a temporary active-memory summary and clearly states that backend may still only return tag/event-level memory.

### DELETE /api/memory/{memory_id}

The page supports deleting an active memory item. On success it shows:

```text
已停止用于下一轮推荐理解
```

The frontend expects the backend to mark the memory as deleted/suppressed so it no longer participates in the next query rewrite. If the backend has not implemented suppression yet, the UI still records the user-facing success state returned by the API.
