# Frontend Closure — 2026-07-06

## Baseline

Branch:

```text
feature/agent-core-mvp
```

Baseline before frontend patch:

```text
0703c82 test(agent-core): real cache_hit assertions + memory ranking evidence + collector skeleton
```

## July 2 Frontend Items

Completed:

- Feedback request body is aligned with `FeedbackEventRequest`.
- Payload includes `event_id`, `plan_id`, `plan_item_id`, `run_id`, `feedback_type`, `feedback_source`, and `metadata`.
- `feedback_source` is `result_card`.
- Failure toast says `反馈提交失败，请稍后再试`.
- Optimistic feedback UI rolls back on request failure.

Evidence:

- `miniprogram/pages/result/result.js`
- `docs/frontend-api-contract.md`

## July 2-3 Frontend Items

Completed:

- Loading page reads `stage`, `stage_message`, `progress`, `cache_hit`, `error_message`, and `debug`.
- Formal generation flow tries `POST /api/agent/stream-plan-day` first.
- If chunked streaming is unavailable, it falls back to `POST /api/agent/plan-day` and `GET /api/agent/runs/{run_id}` polling.
- Stream diagnostic page remains available at `pages/stream-demo/stream-demo`.

Evidence:

- `miniprogram/pages/loading/loading.js`
- `miniprogram/utils/api.js`
- `docs/frontend-api-contract.md`
- `docs/流式生成可行性调研.md`

## July 4-5 Frontend Items

Completed:

- Progress is now interpreted according to backend schema `0.0 - 1.0` and displayed as percent.
- Legacy `0 - 100` progress values are still tolerated.
- Failed state renders `debug.rejections` as structured failure reasons.
- `debug.llm_rewrite.error` / `rewrite_error` with fallback is rendered as copy degradation, not as whole plan-day failure.
- Data-health panel displays `last_collection_time`, `last_collection_result`, `sources_breakdown`, `alerts`, `future_events_7d`, and `future_events_14d`.
- If `collection_logs` is missing or empty, frontend displays `暂无采集日志记录`.
- Backend unreachable data-health state still displays `未连接`.

Evidence:

- `miniprogram/pages/loading/loading.js`
- `miniprogram/pages/loading/loading.wxml`
- `miniprogram/pages/loading/loading.wxss`
- `docs/frontend-acceptance-2026-07-06.md`

## Still Not Fully Verified

- Real WeChat DevTools or phone recording is not produced in this commit.
- Real backend screenshots depend on a running backend returning the target `stage`, `cache`, `failed`, and `data-health` samples.

Impact:

- The frontend code is ready for live verification.
- Final acceptance still needs one run against the current backend to capture screenshots or recording.

## Checks Run

```text
node --check miniprogram/pages/loading/loading.js
node --check miniprogram/pages/plan/plan.js
node --check miniprogram/pages/result/result.js
node --check miniprogram/utils/api.js
node -e "JSON.parse(require('fs').readFileSync('miniprogram/app.json','utf8')); JSON.parse(require('fs').readFileSync('miniprogram/pages/stream-demo/stream-demo.json','utf8'));"
git diff --check
```
