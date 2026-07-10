# Frontend Acceptance Notes — 2026-07-06

This document records the frontend-side acceptance fixtures for the July 4-5 follow-up tasks.

## Branch Baseline

Current baseline branch:

```text
feature/agent-core-mvp
```

The frontend uses the same `GET /api/agent/runs/{run_id}` contract as the backend schema:

```text
progress: 0.0 - 1.0
```

The loading page converts `progress` to a percent for the progress bar and label. Legacy `0 - 100` values are still tolerated.

## Progress Scale Fixture

Run status sample:

```json
{
  "status": "running",
  "stage": "search_events",
  "stage_message": "正在检索活动",
  "progress": 0.3,
  "cache_hit": false
}
```

Expected frontend display:

```text
progress = 30
progressText = 30%
active step = 正在检索活动
```

This specifically guards against showing `0.3%`, `1%`, or the clamp fallback `8%`.

## Cache Hit Fixture

Run status sample:

```json
{
  "status": "running",
  "stage": "cache_hit",
  "stage_message": "命中缓存，正在返回结果",
  "progress": 0.92,
  "cache_hit": true,
  "debug": {
    "cache": {
      "cache_hit": true,
      "cache_type": "plan_result",
      "cache_key": "demo-cache-key",
      "cache_ttl_seconds": 86400
    }
  }
}
```

Expected frontend display:

```text
statusLabel = 命中缓存
currentMessage = 命中缓存，正在返回结果
progressText = 92%
```

## Failed State Fixture

Run status sample:

```json
{
  "status": "failed",
  "error_message": "候选活动不足",
  "debug": {
    "rejection_reason": "未来 7 天可用活动不足",
    "rejections": [
      {
        "code": "no_future_events",
        "reason": "没有足够的未来活动"
      },
      {
        "code": "campus_filter_empty",
        "reason": "校区过滤后候选为空"
      }
    ]
  }
}
```

Expected frontend display:

```text
errorMessage = 候选活动不足：未来 7 天可用活动不足
failureDetails contains:
- 没有足够的未来活动
- 校区过滤后候选为空
```

## Rewrite Fallback Fixture

Run status sample:

```json
{
  "status": "running",
  "stage": "rewrite_plan",
  "progress": 0.8,
  "debug": {
    "used_fallback": true,
    "rewrite_error": "LLM timeout",
    "timeout_seconds": 8,
    "prompt_version": "rewrite-v1"
  }
}
```

Expected frontend display:

```text
rewriteNotice = 推荐文案已降级为模板生成，原因：LLM timeout，超时：8s，prompt：rewrite-v1
```

This is not rendered as a whole plan-day failure.

## Data Health Fixtures

Healthy sample:

```json
{
  "total_events": 120,
  "future_events_7d": 18,
  "future_events_14d": 35,
  "sources_breakdown": {
    "wechat": 80,
    "manual": 40
  },
  "last_collection_time": "2026-07-06T10:00:00+08:00",
  "last_collection_result": "success",
  "is_healthy": true,
  "alerts": [],
  "collection_logs": [
    {
      "source_name": "复旦大学",
      "status": "success",
      "created_at": "2026-07-06T10:00:00+08:00"
    }
  ]
}
```

Expected frontend display:

```text
healthLabel = 健康
sourceSummary = wechat 80 / manual 40
collection log = success / 复旦大学
```

Warning sample:

```json
{
  "total_events": 8,
  "future_events_7d": 2,
  "future_events_14d": 3,
  "sources_breakdown": {},
  "last_collection_time": null,
  "last_collection_result": "unknown",
  "is_healthy": false,
  "alerts": ["未来 7 天活动数量过少"],
  "collection_logs": []
}
```

Expected frontend display:

```text
healthLabel = 需关注
alert = 未来 7 天活动数量过少
collection log = 暂无采集日志记录
```

Backend unreachable sample:

```text
GET /api/admin/data-health fails
```

Expected frontend display:

```text
dataHealth = null
dataHealthError = error message
badge = 未连接
```
