# 校园日程 AI 助手工程架构设计（第二阶段 MVP 规划）

版本：v2.0  
日期：2026-06-11  
基于文档：[工程架构设计_MVP闭环版.md](工程架构设计_MVP闭环版.md)、[Agent训练营中期材料_NexusLab_AgentNexusLab/01_项目说明书.md](Agent训练营中期材料_NexusLab_AgentNexusLab/01_项目说明书.md)

## 1. 文档目标

第一阶段已经完成“用户输入需求 -> Agent 生成日程 -> 前端展示结果”的 MVP 闭环。第二阶段在当前 `main` 中期提交代码基础上，推进系统具备可持续产品能力：

```text
规划历史可查
用户反馈可存
轻量记忆可读
检索排序可被反馈影响
活动数据新鲜度可检查
最终 Demo 可稳定复现
```

第二阶段仍然坚持第一阶段的原则：

1. Agent 不做通用聊天，仍以 `plan-day` 日程规划任务为主。
2. 活动事实必须来自 Event DB 或来源证据，不让 LLM 编造活动。
3. 复杂长期记忆、向量记忆、多轮对话可以保留扩展位，但不作为 6 月中旬的首要交付。
4. 加载速度、字段对齐和 debug 稳定性作为每个功能的验收条件同步解决，不单独拉一条大优化线。

## 2. 第二阶段 MVP 成功标准

到第二阶段完成时，应满足以下可演示标准：

1. 用户可以查看自己过去生成过的日程规划。
2. 用户可以对推荐活动做最小反馈，例如喜欢、不感兴趣、查看来源、重新生成。
3. 后端可以保存反馈，并在下一次 `plan-day` 中读取最近反馈和最近推荐历史。
4. 检索层能根据轻量 memory 做最小个性化，例如降低近期重复活动、降低不感兴趣标签、提高喜欢标签。
5. 前端能展示历史规划入口和反馈入口。
6. 后台或调试接口能看见当前未来可用活动数量、过期活动数量、字段缺失情况和来源证据缺失情况。
7. 端到端 Demo 可以说明：系统具备“历史 + 反馈 + 记忆”能力，能够在后续生成中逐步贴近用户。

## 3. 第二阶段用户闭环

第一阶段闭环：

```text
填写 profile
  -> 输入需求
  -> 生成日程
  -> 查看结果和来源
```

第二阶段闭环：

```text
填写 profile
  -> 输入需求
  -> 生成日程
  -> 查看结果和来源
  -> 对活动做反馈
  -> 反馈写入 history / feedback / memory
  -> 下一次生成时读取记忆
  -> 避免重复推荐，并调整排序
  -> 用户可查看历史规划
```

第二阶段核心任务链：

```text
user request
-> parse_intent
-> load_profile
-> read_memory
-> search_events
-> filter_and_score
-> build_schedule
-> llm_rewrite_summary_and_reasons
-> save_plan
-> save_feedback_candidates
-> return_result
-> collect_feedback
-> update_memory
```

其中 `collect_feedback` 和 `update_memory` 是第二阶段新增重点。

## 4. 第二阶段范围边界

### 4.1 本阶段必须做

1. 规划历史列表与详情。
2. 活动级反馈保存。
3. 轻量 memory 读取与写入。
4. 检索排序接入 memory。
5. 数据新鲜度与字段质量检查。
6. 前端历史入口和反馈入口。
7. 10 条以上 query 回归测试和 3 条反馈闭环演示 case。

### 4.2 本阶段可以预留但不强求

1. 向量数据库记忆。
2. 完整多轮聊天。
3. 自动长期画像归纳。
4. 全自动微信公众号持续抓取。
5. 大规模并发、线上部署和权限系统。

### 4.3 本阶段延后事项

1. 完整重写现有 plan-day 主链路。
2. 将前端改造为通用聊天界面。
3. 将全部过滤和排序交给 LLM 决定。
4. 引入影响 Demo 稳定性的复杂记忆方案。

## 5. 当前代码基线

当前 `main` 已有核心表：

```text
users
user_profiles
sources
raw_documents
events
plan_runs
plans
plan_items
```

当前 `agent_core.search_events` 已预留输入：

```text
intent
profile
memory
now
```

当前 `Memory` 仍是轻量结构：

```text
session_id
recent_query_texts
recent_plan_event_ids
```

第二阶段沿用这些结构，并在其上增量扩展。

## 6. 第二阶段核心架构

```text
微信小程序
  -> Profile / Plan Input / Loading / Result / History / Feedback
  -> FastAPI Backend
  -> Agent Runtime
      -> parse_intent
      -> load_profile
      -> read_memory
      -> search_events(memory-aware)
      -> filter_and_score
      -> build_schedule
      -> rewrite_plan
      -> save_plan
      -> save_feedback_candidates
  -> PostgreSQL
      -> plans / plan_items / plan_runs
      -> user_event_feedback
      -> memory_items
      -> memory_audit_log
      -> events / sources / raw_documents
```

## 7. 数据模型增量设计

### 7.1 现有表字段修订建议

#### `plan_runs`

现有字段：

```text
id
user_id
status
request_text
started_at
ended_at
error_message
debug
```

第二阶段建议新增或标准化：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `date_scope` | string | 否 | `today/tomorrow/this_week/custom`，便于历史查询和统计 |
| `intent_json` | json | 否 | 本次 query 解析后的结构化 intent |
| `stage` | string | 否 | 当前阶段：`parse_intent/load_profile/read_memory/search_events/build_schedule/rewrite/save_plan/completed` |
| `debug` | json/text | 否 | 建议从字符串逐步改为 JSON 对象，保留 rejections、score_details、memory_used |
| `client_context` | json | 否 | 前端环境信息，例如页面、版本、调试开关 |

#### `plan_items`

现有字段：

```text
id
plan_id
event_id
start_time
end_time
reason_text
display_order
```

第二阶段建议新增：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `score` | float | 否 | 当前活动最终排序分 |
| `score_components` | json | 否 | 分数组成：兴趣、校区、时间、新鲜度、反馈加权 |
| `matched_terms` | json | 否 | 命中的关键词或标签 |
| `memory_reasons` | json | 否 | 受记忆影响的说明，例如“避免重复推荐” |

### 7.2 新增表：`user_event_feedback`

用途：保存用户对活动、计划条目或推荐结果的显式/隐式反馈。

```sql
id uuid primary key
user_id uuid references users(id)
event_id uuid references events(id)
plan_id uuid references plans(id)
plan_item_id uuid references plan_items(id)
run_id uuid references plan_runs(id)
feedback_type text
feedback_source text
comment text
weight numeric
metadata json
created_at timestamptz
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `id` | string | 是 | 反馈 ID |
| `user_id` | string | 是 | 用户 ID |
| `event_id` | string | 否 | 被反馈的活动 ID |
| `plan_id` | string | 否 | 反馈来自哪个 plan |
| `plan_item_id` | string | 否 | 反馈来自哪个活动卡片 |
| `run_id` | string | 否 | 反馈来自哪个生成任务 |
| `feedback_type` | string | 是 | 反馈类型，见下方枚举 |
| `feedback_source` | string | 是 | 来源：`result_card/source_page/history_page/system` |
| `comment` | string | 否 | 用户补充文本 |
| `weight` | number | 否 | 反馈权重，默认由后端按类型设置 |
| `metadata` | object | 否 | 前端上下文、按钮位置、原始标签等 |
| `created_at` | datetime | 是 | 反馈创建时间 |

`feedback_type` 枚举：

| 值 | 含义 | 默认影响 |
|---|---|---|
| `like` | 喜欢/感兴趣 | 提升相似标签 |
| `dislike` | 不感兴趣 | 降低相似标签 |
| `clicked_source` | 点击查看来源 | 轻微正反馈 |
| `saved` | 收藏/保存 | 正反馈 |
| `not_relevant` | 与需求不相关 | 负反馈 |
| `wrong_time` | 时间错误 | 数据质量问题 |
| `wrong_location` | 地点错误 | 数据质量问题 |
| `expired` | 活动过期 | 数据质量问题 |
| `joined` | 已参加/打算参加 | 强正反馈 |
| `regenerate` | 用户要求重新生成 | 计划级弱负反馈 |

### 7.3 新增表：`memory_items`

用途：保存可被下次计划读取的轻量记忆。本阶段先使用数据库 JSON，不强制引入向量库。

```sql
id uuid primary key
user_id uuid references users(id)
memory_type text
memory_scope text
content text
structured_content json
source_type text
source_ref text
confidence numeric
priority integer
status text
created_at timestamptz
updated_at timestamptz
last_used_at timestamptz
last_confirmed_at timestamptz
expires_at timestamptz
deleted_at timestamptz
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `id` | string | 是 | 记忆 ID |
| `user_id` | string | 是 | 用户 ID |
| `memory_type` | string | 是 | 记忆类型 |
| `memory_scope` | string | 是 | `session/short_term/long_term/derived` |
| `content` | string | 是 | 给用户和开发者看的自然语言描述 |
| `structured_content` | object | 否 | 机器可读结构 |
| `source_type` | string | 是 | `profile/feedback/plan/history/system` |
| `source_ref` | string | 否 | 来源 ID，例如 feedback_id、plan_id |
| `confidence` | number | 是 | 0-1，推断型记忆默认较低 |
| `priority` | integer | 是 | 进入上下文的优先级，默认 50 |
| `status` | string | 是 | `active/pending/rejected/deleted` |
| `created_at` | datetime | 是 | 创建时间 |
| `updated_at` | datetime | 是 | 更新时间 |
| `last_used_at` | datetime | 否 | 最近被 plan-day 使用的时间 |
| `last_confirmed_at` | datetime | 否 | 最近被用户确认的时间 |
| `expires_at` | datetime | 否 | 短期记忆过期时间 |
| `deleted_at` | datetime | 否 | 删除时间 |

`memory_type` 枚举：

| 值 | 含义 |
|---|---|
| `explicit_interest` | 用户明确兴趣 |
| `explicit_availability` | 用户明确时间偏好 |
| `location_preference` | 校区/地点偏好 |
| `activity_style` | 活动风格偏好 |
| `negative_preference` | 不喜欢的主题、地点或类型 |
| `recent_plan_summary` | 最近规划摘要 |
| `recent_event_history` | 最近推荐活动记录 |
| `feedback_summary` | 反馈归纳出的偏好 |

`structured_content` 建议结构：

```json
{
  "tags": ["AI", "讲座"],
  "campuses": ["邯郸"],
  "time_preference": "晚上",
  "event_ids": ["event_1", "event_2"],
  "negative_tags": ["太累", "强社交"],
  "reason": "用户多次 dislike 体育类活动",
  "evidence_count": 2
}
```

### 7.4 新增表：`memory_audit_log`

用途：记录记忆创建、确认、删除和自动更新，避免系统“偷偷记住”用户。

```sql
id uuid primary key
user_id uuid references users(id)
memory_item_id uuid references memory_items(id)
action text
before_state json
after_state json
actor text
reason text
created_at timestamptz
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `id` | string | 是 | 审计日志 ID |
| `user_id` | string | 是 | 用户 ID |
| `memory_item_id` | string | 否 | 关联记忆 ID |
| `action` | string | 是 | `create/update/confirm/reject/delete/use` |
| `before_state` | object | 否 | 操作前状态 |
| `after_state` | object | 否 | 操作后状态 |
| `actor` | string | 是 | `user/system/admin` |
| `reason` | string | 否 | 操作原因 |
| `created_at` | datetime | 是 | 操作时间 |

### 7.5 新增表：`event_quality_snapshots`

用途：支持数据新鲜度和字段质量验收。

```sql
id uuid primary key
snapshot_date date
total_events integer
future_events integer
expired_events integer
missing_time_count integer
missing_location_count integer
missing_source_url_count integer
missing_evidence_count integer
visible_events integer
stale_events integer
metadata json
created_at timestamptz
```

## 8. 统一 API 约定

所有接口统一响应：

```json
{
  "code": 0,
  "data": {},
  "message": "ok"
}
```

错误响应：

```json
{
  "code": 40001,
  "data": null,
  "message": "profile not found"
}
```

分页字段：

```json
{
  "page": 1,
  "page_size": 20,
  "total": 100
}
```

时间字段统一使用 ISO 8601 带时区字符串：

```text
2026-06-11T19:00:00+08:00
```

## 9. 第二阶段对外接口设计

### 9.1 用户画像

沿用第一阶段接口：

```text
POST /api/profile
GET  /api/profile
PUT  /api/profile
```

`ProfileData` 建议补充只读字段：

```json
{
  "user_id": "uuid",
  "nickname": "张三",
  "campus": "邯郸",
  "identity": "本科",
  "raw_preference_text": "我喜欢 AI、讲座，尽量不要太累",
  "interest_tags": ["AI", "讲座"],
  "preferred_campuses": ["邯郸", "江湾"],
  "available_time": "晚上和周末下午",
  "activity_style_tags": ["轻松", "低强度"],
  "profile_summary": "偏好 AI 相关、轻松、邯郸附近活动",
  "memory_summary": "近期不希望重复推荐毕业典礼类活动",
  "created_at": "2026-06-11T10:00:00+08:00",
  "updated_at": "2026-06-11T10:00:00+08:00"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `memory_summary` | string | 否 | 第二阶段新增，只读，由 memory 聚合生成 |

### 9.2 创建日程生成任务

```text
POST /api/agent/plan-day
```

请求：

```json
{
  "request_text": "明晚想安排点 AI 相关但别太累的活动",
  "date_scope": "tomorrow",
  "max_items": 4,
  "include_debug": false,
  "enable_memory": true,
  "enable_llm_rewrite": true,
  "client_context": {
    "source_page": "plan_input",
    "frontend_version": "0.2.0",
    "timezone": "Asia/Shanghai"
  },
  "idempotency_key": "optional-client-generated-key"
}
```

请求字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `request_text` | string | 是 | 无 | 用户自然语言需求，最长 500 |
| `date_scope` | string | 是 | 无 | `today/tomorrow/this_week/custom` |
| `max_items` | integer | 否 | 4 | 期望返回活动数，范围 1-6 |
| `include_debug` | boolean | 否 | false | 是否返回 debug |
| `enable_memory` | boolean | 否 | true | 是否读取 memory |
| `enable_llm_rewrite` | boolean | 否 | true | 是否启用 LLM 改写 |
| `client_context` | object | 否 | `{}` | 前端上下文 |
| `idempotency_key` | string | 否 | null | 防重复提交 |

响应：

```json
{
  "code": 0,
  "data": {
    "run_id": "uuid",
    "status": "queued",
    "stage": "queued",
    "poll_after_ms": 1000
  },
  "message": "ok"
}
```

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | string | 本次任务 ID |
| `status` | string | `queued/running/completed/failed` |
| `stage` | string | 当前阶段 |
| `poll_after_ms` | integer | 前端建议轮询间隔 |

### 9.3 查询运行状态

```text
GET /api/agent/runs/{run_id}
```

Query 参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `include_debug` | boolean | 否 | false | 是否返回 debug |

响应：

```json
{
  "code": 0,
  "data": {
    "run_id": "uuid",
    "status": "completed",
    "stage": "completed",
    "progress": 1.0,
    "plan_id": "uuid",
    "title": "明天活动安排",
    "summary": "为你安排了 2 个活动，偏轻松并贴近 AI 相关兴趣。",
    "date_scope": "tomorrow",
    "request_text": "明晚想安排点 AI 相关但别太累的活动",
    "memory_used": {
      "enabled": true,
      "recent_plan_event_ids": ["event_a"],
      "boost_tags": ["AI"],
      "downrank_tags": ["强社交"],
      "excluded_event_ids": ["event_a"]
    },
    "items": [
      {
        "plan_item_id": "uuid",
        "event_id": "uuid",
        "title": "AI 讲座：大模型应用",
        "summary": "介绍大模型在校园场景中的应用。",
        "start_time": "2026-06-12T19:00:00+08:00",
        "end_time": "2026-06-12T20:30:00+08:00",
        "location": "邯郸校区光华楼",
        "campus": "邯郸",
        "organizer": "信息学院",
        "tags": ["AI", "讲座"],
        "source_name": "信息学院公众号",
        "source_url": "https://example.com/event",
        "evidence_text": "讲座将于 6 月 12 日 19:00 在光华楼举行。",
        "reason_text": "主题匹配 AI 兴趣，时间在晚上，地点位于偏好校区。",
        "display_order": 1,
        "quality_score": 0.8,
        "score": 0.86,
        "score_components": {
          "interest_match": 0.3,
          "time_fit": 0.2,
          "campus_fit": 0.2,
          "freshness": 0.1,
          "memory_boost": 0.06
        },
        "matched_terms": ["AI", "大模型"],
        "feedback_summary": {
          "liked": false,
          "disliked": false,
          "clicked_source": false
        }
      }
    ],
    "started_at": "2026-06-11T10:00:00+08:00",
    "ended_at": "2026-06-11T10:00:08+08:00",
    "error_message": null,
    "debug": {
      "rejections": [],
      "rejection_counts": {},
      "score_details": [],
      "schedule_skips": [],
      "selected_event_ids": ["uuid"],
      "is_stale": false
    }
  },
  "message": "ok"
}
```

核心字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `stage` | string | 比 `status` 更细的运行阶段 |
| `progress` | number | 0-1，用于前端进度 |
| `memory_used` | object | 本次实际使用的轻量记忆 |
| `items[*].plan_item_id` | string | 反馈时使用 |
| `items[*].score_components` | object | 可解释排序 |
| `items[*].feedback_summary` | object | 当前用户对此活动的反馈状态 |

### 9.4 历史规划列表

```text
GET /api/plans
```

Query 参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `page` | integer | 否 | 1 | 页码 |
| `page_size` | integer | 否 | 20 | 每页数量 |
| `date_scope` | string | 否 | null | 按 date_scope 过滤 |
| `from_date` | string | 否 | null | 创建时间下界 |
| `to_date` | string | 否 | null | 创建时间上界 |

响应：

```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "plan_id": "uuid",
        "run_id": "uuid",
        "title": "明天活动安排",
        "date_scope": "tomorrow",
        "request_text": "明晚想安排点 AI 相关但别太累的活动",
        "summary": "为你安排了 2 个活动。",
        "item_count": 2,
        "created_at": "2026-06-11T10:00:08+08:00"
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 20
  },
  "message": "ok"
}
```

### 9.5 历史规划详情

```text
GET /api/plans/{plan_id}
```

响应字段同 `GET /api/agent/runs/{run_id}` completed 状态中的 plan 部分，必须包含：

```text
plan_id
run_id
title
date_scope
request_text
summary
items
created_at
```

### 9.6 提交活动反馈

```text
POST /api/feedback/event
```

请求：

```json
{
  "event_id": "uuid",
  "plan_id": "uuid",
  "plan_item_id": "uuid",
  "run_id": "uuid",
  "feedback_type": "dislike",
  "feedback_source": "result_card",
  "comment": "这个活动和 AI 关系不大",
  "metadata": {
    "title": "某活动",
    "tags": ["毕业季"],
    "position": 1
  }
}
```

请求字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `event_id` | string | 是 | 被反馈活动 ID |
| `plan_id` | string | 否 | 关联 plan |
| `plan_item_id` | string | 否 | 关联 plan item |
| `run_id` | string | 否 | 关联 run |
| `feedback_type` | string | 是 | 见 `user_event_feedback.feedback_type` |
| `feedback_source` | string | 是 | `result_card/source_page/history_page/system` |
| `comment` | string | 否 | 用户补充 |
| `metadata` | object | 否 | 上下文 |

响应：

```json
{
  "code": 0,
  "data": {
    "feedback_id": "uuid",
    "memory_candidate_ids": ["uuid"],
    "message": "feedback saved"
  },
  "message": "ok"
}
```

### 9.7 提交计划级反馈

```text
POST /api/feedback/plan
```

请求：

```json
{
  "plan_id": "uuid",
  "run_id": "uuid",
  "feedback_type": "regenerate",
  "comment": "整体太偏毕业季了，希望更多 AI 活动",
  "metadata": {
    "visible_event_ids": ["event_a", "event_b"]
  }
}
```

`feedback_type` 枚举：

```text
like
dislike
regenerate
too_many_conflicts
not_enough_items
not_relevant
```

### 9.8 查看我的记忆

```text
GET /api/memory
```

Query 参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `status` | string | 否 | `active` | `active/pending/rejected/deleted/all` |
| `memory_scope` | string | 否 | null | 过滤 scope |
| `page` | integer | 否 | 1 | 页码 |
| `page_size` | integer | 否 | 20 | 每页数量 |

响应：

```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "memory_id": "uuid",
        "memory_type": "negative_preference",
        "memory_scope": "short_term",
        "content": "用户近期不希望重复推荐毕业季活动",
        "structured_content": {
          "negative_tags": ["毕业季"],
          "event_ids": ["event_a"]
        },
        "source_type": "feedback",
        "source_ref": "feedback_id",
        "confidence": 0.7,
        "priority": 60,
        "status": "active",
        "created_at": "2026-06-11T10:00:00+08:00",
        "updated_at": "2026-06-11T10:00:00+08:00",
        "expires_at": "2026-06-18T10:00:00+08:00"
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 20
  },
  "message": "ok"
}
```

### 9.9 确认或拒绝记忆

```text
POST /api/memory/{memory_id}/confirm
POST /api/memory/{memory_id}/reject
DELETE /api/memory/{memory_id}
```

确认请求：

```json
{
  "comment": "这个偏好是对的"
}
```

响应：

```json
{
  "code": 0,
  "data": {
    "memory_id": "uuid",
    "status": "active",
    "last_confirmed_at": "2026-06-11T10:00:00+08:00"
  },
  "message": "ok"
}
```

### 9.10 数据质量概览

```text
GET /api/admin/events/quality-summary
```

Query 参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `now` | string | 否 | 当前时间 | 调试用 |
| `campus` | string | 否 | null | 校区过滤 |
| `source_id` | string | 否 | null | 来源过滤 |

响应：

```json
{
  "code": 0,
  "data": {
    "total_events": 120,
    "future_events": 42,
    "expired_events": 70,
    "visible_events": 80,
    "stale_events": 15,
    "missing_time_count": 5,
    "missing_location_count": 12,
    "missing_source_url_count": 8,
    "missing_evidence_count": 20,
    "by_campus": [
      {
        "campus": "邯郸",
        "future_events": 18,
        "expired_events": 30
      }
    ],
    "by_source": [
      {
        "source_id": "uuid",
        "source_name": "信息学院公众号",
        "future_events": 6,
        "missing_evidence_count": 2
      }
    ],
    "generated_at": "2026-06-11T10:00:00+08:00"
  },
  "message": "ok"
}
```

## 10. Runtime 内部服务接口

### 10.1 `read_memory`

输入：

```json
{
  "user_id": "uuid",
  "request_text": "明晚想安排点 AI 相关但别太累的活动",
  "intent": {
    "date_scope": "tomorrow",
    "interest_tags": ["AI"],
    "style_tags": ["轻松"],
    "preferred_campuses": ["邯郸"]
  },
  "limit": 20,
  "now": "2026-06-11T10:00:00+08:00"
}
```

输出：

```json
{
  "session_id": "uuid",
  "recent_query_texts": ["明天有什么 AI 活动"],
  "recent_plan_event_ids": ["event_a", "event_b"],
  "liked_tags": ["AI", "讲座"],
  "disliked_tags": ["毕业季"],
  "preferred_campuses": ["邯郸"],
  "negative_keywords": ["太累", "强社交"],
  "memory_items": [
    {
      "memory_id": "uuid",
      "memory_type": "negative_preference",
      "content": "用户近期不希望重复推荐毕业季活动",
      "confidence": 0.7,
      "priority": 60
    }
  ]
}
```

### 10.2 `search_events`

输入：

```json
{
  "events": [],
  "intent": {
    "request_text": "明晚想安排点 AI 相关但别太累的活动",
    "date_scope": "tomorrow",
    "explicit_campuses": ["邯郸"],
    "max_items": 4
  },
  "profile": {
    "campus": "邯郸",
    "interest_tags": ["AI", "讲座"],
    "preferred_campuses": ["邯郸"],
    "available_time": "晚上",
    "activity_style_tags": ["轻松"],
    "profile_summary": "偏好 AI 相关、轻松活动"
  },
  "memory": {
    "session_id": "uuid",
    "recent_query_texts": ["明天有什么 AI 活动"],
    "recent_plan_event_ids": ["event_a"],
    "liked_tags": ["AI"],
    "disliked_tags": ["毕业季"],
    "negative_keywords": ["太累"]
  },
  "now": "2026-06-11T10:00:00+08:00",
  "include_debug": true
}
```

输出：

```json
{
  "items": [
    {
      "event": {},
      "score": 0.86,
      "score_components": {
        "interest_match": 0.3,
        "time_fit": 0.2,
        "campus_fit": 0.2,
        "freshness": 0.1,
        "memory_boost": 0.06,
        "repeat_penalty": 0.0
      },
      "matched_terms": ["AI", "大模型"]
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "total_before_filter": 50,
  "rejections": [
    {
      "event_id": "event_a",
      "title": "已推荐过的活动",
      "reason": "recently_recommended"
    }
  ],
  "is_stale": false
}
```

### 10.3 `save_feedback_candidates`

输入：

```json
{
  "user_id": "uuid",
  "run_id": "uuid",
  "plan_id": "uuid",
  "items": [
    {
      "event_id": "uuid",
      "title": "AI 讲座",
      "tags": ["AI", "讲座"],
      "score": 0.86,
      "reason_text": "主题匹配"
    }
  ],
  "memory_used": {
    "liked_tags": ["AI"],
    "disliked_tags": ["毕业季"]
  }
}
```

输出：

```json
{
  "feedback_candidate_ids": ["uuid"],
  "memory_candidate_ids": ["uuid"]
}
```

说明：本阶段的 `save_feedback_candidates` 不要求自动写入长期记忆，只需要为前端反馈和后续记忆更新保留上下文。

### 10.4 `update_memory_from_feedback`

输入：

```json
{
  "user_id": "uuid",
  "feedback_id": "uuid",
  "feedback_type": "dislike",
  "event": {
    "event_id": "uuid",
    "title": "毕业季活动",
    "tags": ["毕业季"]
  },
  "plan_context": {
    "request_text": "明晚想安排点 AI 相关但别太累的活动",
    "date_scope": "tomorrow"
  }
}
```

输出：

```json
{
  "created_memory_ids": ["uuid"],
  "updated_memory_ids": [],
  "audit_log_ids": ["uuid"]
}
```

## 11. 前端页面与字段需求

### 11.1 结果页新增字段

活动卡片需要保留：

```text
plan_id
plan_item_id
run_id
event_id
title
summary
start_time
end_time
location
campus
organizer
tags
source_url
source_name
reason_text
score
score_components
feedback_summary
```

新增按钮：

```text
查看来源 -> POST clicked_source feedback
喜欢 -> POST like feedback
不感兴趣 -> POST dislike feedback
重新生成 -> POST plan-level regenerate feedback，然后重新调用 plan-day
```

### 11.2 历史页字段

列表项：

```text
plan_id
title
request_text
summary
date_scope
item_count
created_at
```

详情页：

```text
PlanDetailData + items + source_url + feedback_summary
```

### 11.3 我的记忆页第一版

本阶段可以只做调试/半隐藏页面，但字段需提前对齐：

```text
memory_id
memory_type
memory_scope
content
confidence
status
created_at
confirm button
delete button
```

## 12. 验收用 Demo 脚本

第二阶段答辩前至少准备以下演示：

### Case 1：历史规划

```text
生成一次日程
  -> 进入历史页
  -> 打开刚才的计划
  -> 活动卡片、来源、推荐理由仍可查看
```

### Case 2：不感兴趣反馈

```text
生成一次日程
  -> 对某活动点击“不感兴趣”
  -> 再次生成相似需求
  -> 系统减少重复或降低相似活动排序
```

### Case 3：查看来源反馈

```text
生成一次日程
  -> 点击查看来源
  -> 后端记录 clicked_source
  -> 历史或 debug 中可查到该反馈
```

### Case 4：数据新鲜度

```text
打开数据质量接口或后台
  -> 展示未来活动数量
  -> 展示字段缺失和来源证据缺失
  -> 说明为什么当前推荐质量受数据规模限制
```

## 13. 结论

第二阶段 MVP 的核心是让第一阶段闭环具备可持续迭代能力：

```text
历史让结果可复用
反馈让系统可学习
记忆让推荐不再从零开始
数据质量让结果可解释
```
