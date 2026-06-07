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
| `data.stage` | Proposed field: drives the reserved Agent progress steps when present |
| `data.debug` | Shown in the loading failure state and result page when present and `ENABLE_DEBUG_VIEW` is enabled |
| `data.error_message` | Shown when the run enters `failed` |

Reserved progress steps:

1. `正在理解需求`
2. `正在检索活动`
3. `正在编排日程`
4. `正在整理结果`

`data.stage` is reserved for backend alignment and is not part of the current runtime schema yet. Without it, the loading page shows a generic queued/running state and does not simulate stage progress. Recognized stage aliases include `intent_parsing`, `load_profile`, `load_memory`, `search_events`, `build_schedule`, `rewrite_plan`, and `save_plan`.

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

Time parsing supports ISO datetime strings, datetime strings with a space separator, and plain `HH:mm`.
