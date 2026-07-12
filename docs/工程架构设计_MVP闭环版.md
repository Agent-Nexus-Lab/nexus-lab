# 校园日程 AI 助手工程架构设计（MVP 闭环版）

版本：v1.0  
日期：2026-05-15  
基于文档：[工程架构设计.md](工程架构设计.md)、[工程架构设计_精简版.md](工程架构设计_精简版.md)

## 1. 文档目标

这份文档只服务一个目标：

```text
尽快做出一个能跑通的 MVP Demo
```

MVP Demo 的定义是：

```text
用户输入自己的偏好和某天/本周的安排需求
  -> 系统从校园活动库中检索候选活动
  -> 按时间、地点、兴趣、可信度做基础筛选
  -> 生成一份可展示的日程结果
  -> 在小程序中展示活动卡片与推荐理由
  -> 保存历史结果供再次查看
```

本版文档不再追求“大而全”的平台设计，而是围绕这条主线，整理出适合 4-5 人团队并行开发的最小工程方案。

## 2. MVP 成功标准

只要满足以下条件，就可以认为 MVP Demo 跑通：

1. 小程序可以录入用户偏好。
2. 后端可以稳定读到一批可用的校园活动数据。
3. 用户输入一句需求后，系统可以返回 1 份日程结果。
4. 日程结果至少包含 2 到 4 个结构化活动卡片。
5. 每个活动卡片都能展示标题、时间、地点、推荐理由、来源链接。
6. 结果可以保存为历史日程，并可再次查看。
7. 整条链路可以在演示中稳定跑通，不依赖人工临场补数据。

## 3. MVP 用户闭环

```text
首次进入小程序
  -> 输入偏好信息
  -> 进入日程页
  -> 输入“今天/明天/这周我想怎么安排”
  -> 点击“生成日程”
  -> 查看生成中状态
  -> 查看结果页与活动卡片
  -> 保存为历史日程
  -> 在历史页重新查看
```

这个闭环就是项目主线。所有模块设计、接口设计、团队分工和开发顺序都必须围绕它展开。

## 4. MVP 核心架构

### 4.1 一句话架构

```text
Data Sources -> Ingestion -> Event DB
                                |
WeChat Mini Program -> FastAPI -> Plan Runtime -> Retrieval/Filter -> Plan Builder -> Response -> Saved Plans
```

### 4.2 宏观模块图

```text
+---------------------------+
|       微信小程序           |
| 偏好页 / 日程页 / 结果页 / 历史页 |
+-------------+-------------+
              |
              v
+-------------+-------------+
|        FastAPI Backend     |
| API / 鉴权 / 状态查询 / 历史保存 |
+------+--------------+------+
       |              |
       |              v
       |    +---------+---------+
       |    |   Plan Runtime    |
       |    | load profile      |
       |    | search events     |
       |    | filter & score    |
       |    | build schedule    |
       |    +---------+---------+
       |              |
       v              v
+------+-------+  +---+-----------------+
| PostgreSQL   |  | Redis               |
| users/events |  | run state / cache   |
| plans/items  |  +---------------------+
+------+-------+
       ^
       |
+------+------------------------------+
|         Worker / Ingestion          |
| fetch / parse / normalize / dedupe  |
+------+------------------------------+
       ^
       |
+------+------------------------------+
| 校园官网 / 院系网站 / RSS / 人工录入 |
+-------------------------------------+
```

### 4.3 架构原则

1. 先把 Event DB 做出来，再做推荐和生成。
2. Agent 不做通用聊天，只做 `plan-day` 任务编排。
3. 前端只做输入、展示、状态反馈，不在小程序端拼 prompt。
4. 后端先单体实现，代码按模块分层，部署先不拆微服务。
5. 能规则化的尽量规则化，LLM 只用于必要的生成和轻量规划。

## 5. MVP 必做模块

### 5.1 小程序前端

负责用户可见闭环，先做 4 个页面：

1. 偏好输入页  
   输入校区、身份、兴趣、常见空闲时间、活动风格。

2. 日程输入页  
   输入本次需求，例如“今晚想安排点 AI 相关但别太累的活动”。

3. 生成结果页  
   展示生成中状态、最终日程摘要、活动卡片、推荐理由。

4. 历史日程页  
   展示过去生成过的结果列表，并可进入详情查看。

前端目标不是做聊天界面，而是做一个清晰的“任务输入 -> 结果展示”界面。

### 5.2 后端 API

负责承接小程序请求、触发规划流程、返回结果、保存历史。

MVP 后端的核心职责：

1. 接收用户偏好与日程请求。
2. 读取用户画像。
3. 拉取候选活动。
4. 调用规划流程生成结果。
5. 保存日程结果和条目。
6. 提供运行状态与历史查询接口。

### 5.3 Plan Runtime

这里不接入 `Pi Agent`，而是使用轻量自研编排层。

MVP 只需要一个很薄的流程：

```text
load_profile
  -> search_events
  -> filter_by_time_campus_interest
  -> score_candidates
  -> build_schedule
  -> save_plan
  -> return_result
```

这个 Runtime 不是通用 Agent 平台，而是一个围绕 `plan-day` 的任务编排器。

### 5.4 数据采集与入库

MVP 的目标不是覆盖全部来源，而是做出稳定可用的活动库。

建议先接入：

1. 2 到 3 个校园官网或学院官网来源。
2. 1 到 2 个稳定的 RSS/RSSHub 来源。
3. 1 个后台人工录入入口，作为演示前补数据的保底手段。

数据链路：

```text
source
  -> fetch raw page/feed
  -> extract title/time/location/url
  -> normalize fields
  -> dedupe
  -> save raw_documents
  -> publish events
```

### 5.5 存储与缓存

MVP 只用两类基础设施：

1. PostgreSQL  
   保存用户、画像、来源、原始文档、活动、日程结果。

2. Redis  
   保存运行状态、短期缓存、可选的任务队列状态。

## 6. LLM 使用策略

MVP 里 LLM 只做两类事情：

1. 根据候选活动生成自然语言日程说明。
2. 在给定候选活动集合内组织安排顺序和推荐理由。

以下能力优先用代码完成：

1. 时间过滤。
2. 地点过滤。
3. 校区过滤。
4. 基础兴趣标签匹配。
5. 候选活动排序。
6. 冲突检查。
7. 历史结果保存。

一句话原则：

```text
先检索和过滤，再让 LLM 组织表达；不要让 LLM 代替规则和数据库事务。
```

## 7. 最小数据模型

MVP 不需要把完整会话系统做得太重，先围绕业务主线保留以下数据表。

### 7.1 `users`

保存基础用户信息。

关键字段：

```text
id
nickname
campus
created_at
updated_at
```

### 7.2 `user_profiles`

保存用户偏好画像。

关键字段：

```text
user_id
raw_preference_text
interest_tags
preferred_campuses
available_time
activity_style_tags
profile_summary
updated_at
```

### 7.3 `sources`

保存活动数据来源。

关键字段：

```text
id
name
source_type
base_url
feed_url
is_active
last_crawled_at
```

### 7.4 `raw_documents`

保存原始抓取内容，便于回溯。

关键字段：

```text
id
source_id
url
title
content_text
fetched_at
content_hash
status
```

### 7.5 `events`

保存结构化活动数据，是整个 MVP 的核心表。

关键字段：

```text
id
title
summary
start_time
end_time
location
campus
organizer
source_id
source_url
tags
quality_score
verification_status
is_user_visible
created_at
updated_at
```

### 7.6 `plan_runs`

保存一次生成任务的运行状态，用于前端展示“生成中”和轮询结果。

关键字段：

```text
id
user_id
status
request_text
started_at
ended_at
error_message
```

状态建议：

1. `queued`
2. `running`
3. `completed`
4. `failed`

### 7.7 `plans`

保存一次成功生成的日程结果。

关键字段：

```text
id
run_id
user_id
title
date_scope
summary
created_at
```

### 7.8 `plan_items`

保存日程中的每一个活动条目。

关键字段：

```text
id
plan_id
event_id
start_time
end_time
reason_text
display_order
```

## 8. 最小接口设计

MVP 先把接口数量控制住，避免团队联调复杂化。

### 8.1 用户与画像

```text
POST /api/profile
GET  /api/profile
PUT  /api/profile
```

### 8.2 日程生成

```text
POST /api/agent/plan-day
GET  /api/agent/runs/{run_id}
```

`POST /api/agent/plan-day` 输入：

```json
{
  "request_text": "今晚想安排点 AI 相关但别太累的活动",
  "date_scope": "today"
}
```

返回：

```json
{
  "run_id": "uuid",
  "status": "running"
}
```

`GET /api/agent/runs/{run_id}` 返回：

```json
{
  "run_id": "uuid",
  "status": "completed",
  "plan_id": "uuid",
  "summary": "今晚为你安排了 3 个偏轻松的 AI 相关活动",
  "items": [
    {
      "event_id": "uuid",
      "title": "AI 讲座：大模型应用",
      "start_time": "2026-05-15T19:00:00+08:00",
      "location": "江湾校区教学楼 205",
      "reason_text": "时间合适，主题匹配，地点较近",
      "source_url": "https://example.com/event"
    }
  ]
}
```

### 8.3 历史日程

```text
GET /api/plans
GET /api/plans/{plan_id}
```

### 8.4 后台最小接口

```text
GET  /api/admin/sources
POST /api/admin/sources
POST /api/admin/import-url
GET  /api/admin/events
```

后台接口的目标不是做完整运营系统，而是给团队调试、补数据、查问题。

## 9. 日程生成流程

MVP 的核心流程建议固定如下：

```text
1. 读取用户画像
2. 解析 date_scope 和 request_text
3. 从 events 表召回候选活动
4. 按时间、校区、兴趣、可信度做过滤
5. 按规则分数排序
6. 选择 2 到 4 个可组合活动
7. 生成日程说明与推荐理由
8. 保存 plans 和 plan_items
9. 返回前端结果
```

### 9.1 候选过滤规则

第一版先做基础规则：

1. 只保留未来活动。
2. 优先保留用户偏好校区的活动。
3. 优先保留与兴趣标签匹配的活动。
4. 去掉明显时间冲突的活动组合。
5. 低可信或字段缺失严重的活动不进入主推荐。

### 9.2 排序建议

先用简单加权公式，不做复杂模型：

```text
score =
  0.30 * interest_match
+ 0.25 * time_fit
+ 0.20 * campus_fit
+ 0.15 * source_reliability
+ 0.10 * freshness
```

这样做的目的不是最优，而是先稳定、可解释、可调试。

## 10. 前端页面建议

### 10.1 偏好输入页

展示内容：

1. 校区选择。
2. 身份选择。
3. 兴趣标签。
4. 空闲时间描述。
5. 活动风格描述。

### 10.2 日程输入页

展示内容：

1. 文本输入框。
2. 今天 / 明天 / 本周快捷选项。
3. 生成按钮。

### 10.3 结果页

展示内容：

1. 生成状态。
2. 本次日程摘要。
3. 活动卡片列表。
4. 每个活动的推荐理由。
5. 保存成功提示。

### 10.4 历史页

展示内容：

1. 历史日程列表。
2. 每条历史的标题与摘要。
3. 点击进入详情查看活动条目。

## 11. 团队分工建议（4-5 人）

为了避免互相等待，建议按主链路分工，而不是只按“前端/后端/AI”粗分。

### 11.1 角色 1：数据采集与入库

负责：

1. `sources` 管理。
2. 抓取和解析来源页面或 feed。
3. 清洗字段并写入 `raw_documents`、`events`。
4. 处理去重和基础可见性控制。

交付物：

1. 稳定可查的 `events` 表。
2. 最少 20 到 50 条可演示活动数据。

### 11.2 角色 2：检索排序与日程生成

负责：

1. `search_events` 逻辑。
2. 时间、地点、兴趣过滤。
3. 候选排序。
4. `build_schedule` 逻辑。
5. LLM 结果组装。

交付物：

1. 可以根据用户需求返回结构化日程结果。

### 11.3 角色 3：后端 API 与运行状态

负责：

1. FastAPI 接口。
2. `plan_runs`、`plans`、`plan_items` 存储。
3. 运行状态查询。
4. 历史结果接口。
5. 与前端约定返回 JSON。

交付物：

1. 前后端可稳定联调的 API。

### 11.4 角色 4：小程序前端

负责：

1. 偏好页。
2. 日程输入页。
3. 结果页。
4. 历史页。
5. 调用 API 并渲染结果。

交付物：

1. 能完整走通演示闭环的小程序。

### 11.5 角色 5：联调、测试、后台与 Demo 保障

如果有第 5 人，建议不要单开新功能线，而是负责：

1. 补后台最小工具页。
2. 做接口联调。
3. 准备演示数据。
4. 做 Demo 脚本和回归测试。
5. 跟踪 Bug 和进度。

## 12. 开发顺序建议

### 阶段 1：活动库打底

目标：

1. 可以录入来源。
2. 可以抓到并入库活动。
3. `events` 表里有稳定演示数据。

### 阶段 2：API 骨架打通

目标：

1. `POST /api/profile` 可用。
2. `POST /api/agent/plan-day` 可以返回假数据。
3. 小程序能把输入提交到后端。

### 阶段 3：真实生成链路接入

目标：

1. 从真实 `events` 中检索活动。
2. 完成过滤、排序、日程生成。
3. 保存 `plans` 和 `plan_items`。

### 阶段 4：联调和演示打磨

目标：

1. 结果页展示完整活动卡片。
2. 历史页可查看。
3. 生成失败时能提示。
4. 进行多轮演示彩排。

## 13. MVP 运行与部署

MVP 建议统一使用 Docker Compose：

```text
frontend
backend
worker
postgres
redis
nginx
```

建议原则：

1. 后端先单体部署。
2. worker 与 backend 分进程。
3. PostgreSQL 和 Redis 单独容器。
4. 不要一开始上 Kubernetes。

## 14. Demo 演示建议

最终演示流程建议固定为：

```text
1. 进入小程序
2. 展示已填写的偏好
3. 输入一句日程需求
4. 点击“生成日程”
5. 展示生成中状态
6. 展示 1 份完整日程结果
7. 点开活动卡片查看时间、地点、来源
8. 进入历史页查看刚才生成的结果
```

只要这一条能稳定跑通，MVP Demo 就成立。

## 15. 一句话结论

这次项目不再以“做一个完整 Agent 平台”为目标，而是以“做一个能稳定产出校园日程结果的 MVP Demo”为目标。

工程上最重要的不是功能铺开，而是先完成下面这条主线：

```text
活动入库 -> 检索筛选 -> 日程生成 -> 小程序展示 -> 历史保存
```

团队所有工作都应该围绕这条主线推进。
