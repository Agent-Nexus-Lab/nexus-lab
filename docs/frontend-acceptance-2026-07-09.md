# 2026-07-09 Frontend Acceptance Plan

This document records the frontend work for the July 9 task. The frontend must not fake backend collection success; it only displays real API fields and honest empty/failure states.

## Completed Frontend Surfaces

| Task | Frontend status |
|---|---|
| data-health before/after import | Loading page already renders `future_events_7d`, `future_events_14d`, `alerts`, `last_collection_time`, `last_collection_result` |
| collection_logs | Loading page renders batch, trigger method, source, fetched/extracted/imported counts, failure reason; empty logs show `暂无采集日志记录` |
| result card fields | Result page renders title, summary, time, location, source URL/name, tags, reason, quality score |
| source_url click | Result page opens source and sends `clicked_source` feedback in background |
| score reason | Result page renders semantic/memory/repeat penalty and `score_components` chips when provided |
| answer_composer | Result page renders summary, recommended_items, tradeoffs, follow_up_question when provided |
| memory_summary | New memory page calls `GET /api/memory`, displays active memory summary/items, and supports delete via `DELETE /api/memory/{memory_id}` |

## Memory Page Recording Script

1. Open the plan page or result page.
2. Tap `查看偏好记忆`.
3. If backend has no active memory, record the empty state.
4. If backend returns active memory, record content, memory strength, source summary, update time, decay/expiry, and cleanup reason.
5. Delete one memory item.
6. Confirm the page shows `已停止用于下一轮推荐理解`.
7. Regenerate a plan and check whether backend debug shows the deleted memory no longer participates in query rewrite. This final check depends on backend memory suppression implementation.

## Data Collection Recording Script

1. Before import, start a generation and pause on loading.
2. Record data-health values and alerts.
3. If collection logs are empty, record `暂无采集日志记录`.
4. After backend runs auto_collector commit / collection_cron, regenerate.
5. Record changed future event metrics and the latest collection log row.
6. If metrics do not change, record the backend reason instead of presenting it as success.

## Recommendation Recording Script

1. Generate a plan with a query that should hit newly imported activities.
2. On result page, record at least one new activity card.
3. Show source link, reason text, score reason chips, and answer_composer panel if returned.
4. Tap source link and confirm it opens.
5. Return and tap like/dislike to show feedback status.

## Current Dependency Boundary

Frontend is ready for the July 9 acceptance flow, but full success still depends on backend/search delivering:

```text
collection_logs real records
EventImportService imported activities
summary_embedding / score_components
answer_composer output
memory_summary or active memory items
memory deletion suppression in query rewrite
```
