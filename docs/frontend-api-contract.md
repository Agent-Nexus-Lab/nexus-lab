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
| `data.progress` | Numeric progress. If present, the frontend uses it after clamping into a safe UI range |
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

| UI action | `feedback_type` | Behavior |
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
| `weight` | number | `1`, `-1`, or `0.2` |
| `metadata` | object | Includes action, title, tags, source URL, display order |

## History Placeholder

The miniprogram now has a placeholder `pages/history/history` entry. Until `GET /api/plans` is stable, the page reads a local `planHistoryDraft` list written after a successful completed run. The fields mirror the planned history list shape: `plan_id`, `run_id`, `title`, `date_scope`, `request_text`, `item_count`, `status`, and `created_at`.

## Streaming Exploration

The formal plan-day flow still uses:

```text
POST /api/agent/plan-day
GET /api/agent/runs/{run_id}
```

For the phase-2 exploration line, the miniprogram includes a dev-only page:

```text
pages/stream-demo/stream-demo
```

This page calls `api.streamRuntimeDemo()` with `wx.request({ enableChunked: true })` and listens through `task.onChunkReceived`. It is not linked from the user-facing flow and should only be used after the backend provides a dev-only chunked endpoint such as `/api/agent/stream-demo`.

Current conclusion for acceptance:

```text
Main path: keep polling.
Exploration path: verify whether the current WeChat base library and real device can receive chunks stably.
If chunked HTTP is unstable, use stage/progress polling for this phase and evaluate WebSocket in the next phase.
```
