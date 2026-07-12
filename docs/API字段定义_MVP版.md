# 校园日程 AI 助手 — API 字段定义（MVP 版）

版本：v1.0  
日期：2026-05-18  
用途：后端定接口、前端/数据/算法三方并行开工的契约文档

---

## 1. 通用约定

### 1.1 Base URL

```
开发环境: http://localhost:8000/api
```

### 1.2 认证

MVP 阶段暂用微信 `openid` 作为用户标识，通过请求头传递：

```http
Authorization: Bearer <openid>
```

后端通过该 Header 解析当前用户，`user_id` 由服务端内部映射。

### 1.3 通用响应格式

成功：

```json
{
  "code": 0,
  "data": { ... },
  "message": "ok"
}
```

失败：

```json
{
  "code": <error_code>,
  "data": null,
  "message": "<human-readable error message>"
}
```

### 1.4 时间格式

所有时间字段统一使用 **ISO 8601 带时区**：

```
2026-05-18T19:00:00+08:00
```

### 1.5 分页

列表接口统一使用：

| query 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `page` | int | 1 | 页码，从 1 开始 |
| `page_size` | int | 20 | 每页条数，最大 50 |

分页响应格式：

```json
{
  "code": 0,
  "data": {
    "items": [ ... ],
    "total": 47,
    "page": 1,
    "page_size": 20
  }
}
```

---

## 2. 用户画像 API

### 2.1 创建/更新画像 — `POST /api/profile`

请求体：

```json
{
  "nickname": "张三",
  "campus": "江湾",
  "identity": "本科生",
  "raw_preference_text": "喜欢AI和创业相关活动，晚上有空，不喜欢太学术的",
  "interest_tags": ["AI", "创业", "产品"],
  "preferred_campuses": ["江湾", "邯郸"],
  "available_time": "工作日晚上和周末下午",
  "activity_style_tags": ["轻松", "互动", "实践"],
  "profile_summary": "CS专业大三，关注AI应用落地，偏好晚间非学术类活动"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `nickname` | string | 是 | 用户昵称，最长 32 字符 |
| `campus` | string | 是 | 主校区，枚举见附录 A |
| `identity` | string | 否 | 身份：`本科生`/`硕士生`/`博士生`/`教职工`/`其他` |
| `raw_preference_text` | string | 否 | 用户自由描述偏好的原始文本 |
| `interest_tags` | string[] | 否 | 兴趣标签，每个最长 20 字符 |
| `preferred_campuses` | string[] | 否 | 偏好校区列表 |
| `available_time` | string | 否 | 空闲时间文字描述 |
| `activity_style_tags` | string[] | 否 | 偏好的活动风格标签 |
| `profile_summary` | string | 否 | 结构化画像摘要（后端/算法生成） |

响应（200）：

```json
{
  "code": 0,
  "data": {
    "user_id": "u_abc123",
    "nickname": "张三",
    "campus": "江湾",
    "identity": "本科生",
    "raw_preference_text": "喜欢AI和创业相关活动，晚上有空，不喜欢太学术的",
    "interest_tags": ["AI", "创业", "产品"],
    "preferred_campuses": ["江湾", "邯郸"],
    "available_time": "工作日晚上和周末下午",
    "activity_style_tags": ["轻松", "互动", "实践"],
    "profile_summary": "CS专业大三，关注AI应用落地，偏好晚间非学术类活动",
    "created_at": "2026-05-18T10:00:00+08:00",
    "updated_at": "2026-05-18T10:00:00+08:00"
  },
  "message": "ok"
}
```

### 2.2 获取画像 — `GET /api/profile`

无请求体。

响应（200）：格式同 `POST /api/profile` 返回的 `data`。

未创建画像时返回：

```json
{
  "code": 0,
  "data": null,
  "message": "ok"
}
```

### 2.3 更新画像 — `PUT /api/profile`

请求体、响应格式同 `POST /api/profile`。支持部分更新（只传需要修改的字段）。

---

## 3. 日程生成 API

### 3.1 生成日程 — `POST /api/agent/plan-day`

请求体：

```json
{
  "request_text": "今晚想安排点AI相关但别太累的活动",
  "date_scope": "today"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `request_text` | string | 是 | 用户自然语言需求描述，最长 500 字符 |
| `date_scope` | string | 是 | 时间范围，枚举：`today`/`tomorrow`/`this_week` |

响应（202 Accepted）：

```json
{
  "code": 0,
  "data": {
    "run_id": "run_3f7a9b2c",
    "status": "queued"
  },
  "message": "ok"
}
```

错误响应（400）：

```json
{
  "code": 1001,
  "data": null,
  "message": "用户画像未创建，请先提交偏好信息"
}
```

### 3.2 查询运行状态 — `GET /api/agent/runs/{run_id}`

路径参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `run_id` | string | `POST /api/agent/plan-day` 返回的 run_id |

响应（200）— 运行中：

```json
{
  "code": 0,
  "data": {
    "run_id": "run_3f7a9b2c",
    "status": "running",
    "plan_id": null,
    "summary": null,
    "items": null,
    "started_at": "2026-05-18T20:00:01+08:00",
    "error_message": null
  },
  "message": "ok"
}
```

响应（200）— 已完成：

```json
{
  "code": 0,
  "data": {
    "run_id": "run_3f7a9b2c",
    "status": "completed",
    "plan_id": "plan_d5e8f1a3",
    "title": "今晚 AI 轻量活动安排",
    "summary": "今晚为你安排了 3 个偏轻松的 AI 相关活动，都在江湾校区，步行可达。",
    "date_scope": "today",
    "items": [
      {
        "event_id": "evt_001",
        "title": "AI 讲座：大模型在产业中的应用",
        "summary": "邀请业界专家分享大模型落地案例，适合对AI应用感兴趣的同学",
        "start_time": "2026-05-18T19:00:00+08:00",
        "end_time": "2026-05-18T20:30:00+08:00",
        "location": "江湾校区教学楼A205",
        "campus": "江湾",
        "organizer": "计算机学院",
        "tags": ["AI", "讲座", "产业"],
        "source_url": "https://www.example.edu.cn/events/123",
        "reason_text": "主题高度匹配你的 AI 兴趣标签，时间在晚间符合你的空闲时段，步行 5 分钟可达",
        "display_order": 1,
        "quality_score": 0.85
      },
      {
        "event_id": "evt_002",
        "title": "AI 创业沙龙：从实验室到产品",
        "summary": "小型圆桌讨论，聊聊如何把AI论文变成可用的产品",
        "start_time": "2026-05-18T20:00:00+08:00",
        "end_time": "2026-05-18T21:30:00+08:00",
        "location": "江湾校区创业空间1楼",
        "campus": "江湾",
        "organizer": "创新创业中心",
        "tags": ["AI", "创业", "沙龙"],
        "source_url": "https://www.example.edu.cn/events/456",
        "reason_text": "同时匹配 AI 和创业两个兴趣标签，互动形式契合你偏好的活动风格",
        "display_order": 2,
        "quality_score": 0.82
      }
    ],
    "started_at": "2026-05-18T20:00:01+08:00",
    "ended_at": "2026-05-18T20:00:05+08:00",
    "error_message": null
  },
  "message": "ok"
}
```

响应（200）— 失败：

```json
{
  "code": 0,
  "data": {
    "run_id": "run_3f7a9b2c",
    "status": "failed",
    "plan_id": null,
    "summary": null,
    "items": null,
    "started_at": "2026-05-18T20:00:01+08:00",
    "ended_at": "2026-05-18T20:00:03+08:00",
    "error_message": "当前时间范围内没有找到匹配的活动"
  },
  "message": "ok"
}
```

**status 枚举：**

| 值 | 说明 |
|---|---|
| `queued` | 已入队，等待执行 |
| `running` | 正在生成中 |
| `completed` | 生成成功 |
| `failed` | 生成失败 |

**Item 字段说明：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `event_id` | string | 活动唯一 ID |
| `title` | string | 活动标题 |
| `summary` | string | 活动简介 |
| `start_time` | string | 开始时间，ISO 8601 |
| `end_time` | string | 结束时间，ISO 8601 |
| `location` | string | 活动地点 |
| `campus` | string | 所属校区 |
| `organizer` | string | 主办方 |
| `tags` | string[] | 活动标签 |
| `source_url` | string | 活动来源链接 |
| `reason_text` | string | LLM 生成的推荐理由 |
| `display_order` | int | 展示顺序，从 1 开始 |
| `quality_score` | float | 活动质量分，0~1 |

---

## 4. 历史日程 API

### 4.1 历史日程列表 — `GET /api/plans`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `page` | int | 否 | 页码，默认 1 |
| `page_size` | int | 否 | 每页条数，默认 20，最大 50 |

响应（200）：

```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "plan_id": "plan_d5e8f1a3",
        "title": "今晚 AI 轻量活动安排",
        "date_scope": "today",
        "summary": "今晚为你安排了 3 个偏轻松的 AI 相关活动，都在江湾校区，步行可达。",
        "item_count": 3,
        "created_at": "2026-05-18T20:00:05+08:00"
      },
      {
        "plan_id": "plan_a1b2c3d4",
        "title": "本周活动推荐",
        "date_scope": "this_week",
        "summary": "本周为你找到 4 个匹配的活动，涵盖AI讲座和创业沙龙。",
        "item_count": 4,
        "created_at": "2026-05-17T15:30:00+08:00"
      }
    ],
    "total": 2,
    "page": 1,
    "page_size": 20
  },
  "message": "ok"
}
```

列表项字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `plan_id` | string | 日程唯一 ID |
| `title` | string | 日程标题 |
| `date_scope` | string | 时间范围：`today`/`tomorrow`/`this_week` |
| `summary` | string | 日程摘要说明 |
| `item_count` | int | 包含的活动数量 |
| `created_at` | string | 创建时间 |

### 4.2 历史日程详情 — `GET /api/plans/{plan_id}`

响应（200）：

```json
{
  "code": 0,
  "data": {
    "plan_id": "plan_d5e8f1a3",
    "title": "今晚 AI 轻量活动安排",
    "date_scope": "today",
    "summary": "今晚为你安排了 3 个偏轻松的 AI 相关活动，都在江湾校区，步行可达。",
    "items": [
      {
        "event_id": "evt_001",
        "title": "AI 讲座：大模型在产业中的应用",
        "summary": "邀请业界专家分享大模型落地案例",
        "start_time": "2026-05-18T19:00:00+08:00",
        "end_time": "2026-05-18T20:30:00+08:00",
        "location": "江湾校区教学楼A205",
        "campus": "江湾",
        "organizer": "计算机学院",
        "tags": ["AI", "讲座", "产业"],
        "source_url": "https://www.example.edu.cn/events/123",
        "reason_text": "主题高度匹配你的 AI 兴趣标签，时间在晚间符合你的空闲时段，步行 5 分钟可达",
        "display_order": 1,
        "quality_score": 0.85
      }
    ],
    "created_at": "2026-05-18T20:00:05+08:00"
  },
  "message": "ok"
}
```

Item 字段同 3.2 节中的 item 定义。

---

## 5. 后台管理 API

### 5.1 来源列表 — `GET /api/admin/sources`

响应（200）：

```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "source_id": "src_001",
        "name": "计算机学院官网",
        "source_type": "web",
        "base_url": "https://cs.example.edu.cn",
        "feed_url": null,
        "is_active": true,
        "last_crawled_at": "2026-05-18T08:00:00+08:00",
        "event_count": 12
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 20
  },
  "message": "ok"
}
```

### 5.2 创建来源 — `POST /api/admin/sources`

请求体：

```json
{
  "name": "计算机学院官网",
  "source_type": "web",
  "base_url": "https://cs.example.edu.cn",
  "feed_url": null,
  "is_active": true
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | 是 | 来源名称 |
| `source_type` | string | 是 | 枚举：`web`/`rss`/`manual` |
| `base_url` | string | source_type=web 时必填 | 网站根 URL |
| `feed_url` | string | source_type=rss 时必填 | RSS/Atom feed URL |
| `is_active` | bool | 否 | 是否启用，默认 true |

响应（201）：

```json
{
  "code": 0,
  "data": {
    "source_id": "src_001",
    "name": "计算机学院官网",
    "source_type": "web",
    "base_url": "https://cs.example.edu.cn",
    "feed_url": null,
    "is_active": true,
    "created_at": "2026-05-18T20:00:00+08:00"
  },
  "message": "ok"
}
```

### 5.3 手动导入活动 — `POST /api/admin/import-url`

请求体：

```json
{
  "url": "https://cs.example.edu.cn/news/2026/05/ai-talk",
  "source_id": "src_001"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `url` | string | 是 | 要抓取的活动页面 URL |
| `source_id` | string | 否 | 关联的来源 ID，不传则自动匹配 |

响应（202）：

```json
{
  "code": 0,
  "data": {
    "document_id": "doc_abc",
    "url": "https://cs.example.edu.cn/news/2026/05/ai-talk",
    "status": "queued"
  },
  "message": "ok"
}
```

### 5.4 活动列表 — `GET /api/admin/events`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `page` | int | 否 | 默认 1 |
| `page_size` | int | 否 | 默认 20 |
| `source_id` | string | 否 | 按来源筛选 |
| `campus` | string | 否 | 按校区筛选 |
| `is_user_visible` | bool | 否 | 是否对用户可见 |
| `verification_status` | string | 否 | `verified`/`unverified`/`rejected` |
| `q` | string | 否 | 标题/摘要模糊搜索 |

响应（200）：

```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "event_id": "evt_001",
        "title": "AI 讲座：大模型在产业中的应用",
        "summary": "邀请业界专家分享大模型落地案例",
        "start_time": "2026-05-18T19:00:00+08:00",
        "end_time": "2026-05-18T20:30:00+08:00",
        "location": "江湾校区教学楼A205",
        "campus": "江湾",
        "organizer": "计算机学院",
        "source_name": "计算机学院官网",
        "source_url": "https://www.example.edu.cn/events/123",
        "tags": ["AI", "讲座", "产业"],
        "quality_score": 0.85,
        "verification_status": "verified",
        "is_user_visible": true,
        "created_at": "2026-05-17T10:00:00+08:00"
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 20
  },
  "message": "ok"
}
```

### 5.5 活动信息抽取中间结构 — Agent/Data 内部

该结构用于“多条信息源原文 -> 活动候选事件集”的内部流转，可作为 LLM 抽取、人工复核和后续入库前的中间格式。它不是面向前端的公开 API 响应，也不同于 3.2 节的 `plan-day` 运行结果。

MaaS 单条抽取阶段可以保留 `warnings` 供调试；正式测评/交接文件只输出一个 `events.json`，顶层只包含 `events`。

示例：

```json
{
  "events": [
    {
      "event_id": "550e8400-e29b-41d4-a716-446655440000",
      "source_file": "1.txt",
      "source_name": "复旦天协",
      "source_url": null,
      "title": "路边天文 | 春末夏初，群星交替",
      "summary": "5月15日20:00在光草东北角举办路边天文观测活动，包含春季星空讲解和望远镜观测。",
      "start_time": "2026-05-15T20:00:00+08:00",
      "end_time": null,
      "location": "光草东北角",
      "campus": "邯郸",
      "organizer": "复旦天协",
      "tags": ["天文", "观星"],
      "evidence_text": "时间：今晚（5.15）20:00开始\n地点：光草东北角"
    }
  ]
}
```

顶层字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `events` | object[] | 从全部输入信息源中抽取出的活动候选 |

`events[*]` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `event_id` | string | 活动候选唯一 ID，UUIDv4；由聚合脚本生成，**仅用于本次流转的临时标识**。正式入库时由数据侧根据内容去重后生成持久化主键 |
| `source_file` | string | 本地测评或批量导入时的来源文件名，用于回溯原文 |
| `source_name` | string/null | 信息源名称，例如学院官网、社团账号、公众号名称；无法确定时为 null |
| `source_url` | string/null | 信息源原文 URL；无法确定时为 null |
| `title` | string | 活动标题 |
| `summary` | string/null | 活动事实简介，不写推荐理由 |
| `start_time` | string/null | 开始时间，ISO 8601 带时区；无法确定完整日期时间时为 null |
| `end_time` | string/null | 结束时间，ISO 8601 带时区；无法确定时为 null |
| `location` | string/null | 活动地点 |
| `campus` | string | 所属校区，枚举见附录 A；原文未明确校区时默认 `邯郸`；同一活动明确涉及多个校区时拆为多条 event，每条只填一个校区 |
| `organizer` | string/null | 主办/承办/组织/发布方，无法确定时为 null |
| `tags` | string[] | 从原文主题或活动类型抽取的标签 |
| `evidence_text` | string/null | 支持该活动抽取的原文片段，便于人工复核和回溯 |

以下字段不由抽取模型或聚合脚本生成，应在入库、审核或推荐阶段产生：

| 字段 | 产生阶段 |
|---|---|
| `quality_score` | 来源可信度、字段完整度、人工审核或规则评分阶段生成 |
| `verification_status` | 审核流程生成 |
| `is_user_visible` | 发布/审核逻辑生成 |
| `created_at` / `updated_at` | 数据库写入时生成 |
| `reason_text` / `display_order` | `plan-day` 推荐结果生成阶段产生 |

---

---

## 5.6 活动检索 — `POST /api/agent/search-events`（新增，MVP doc 中未定义）

`search_events` 是 agent 检索层的核心原语，供 plan runtime 和其他内部模块调用。它将查询条件明确分离为**硬约束**（不满足则 reject）和**软偏好**（影响打分，不造成 reject）。

### 请求体

```json
{
  "hard": {
    "start_time_after": "2026-06-01T00:00:00+08:00",
    "start_time_before": "2026-06-07T23:59:59+08:00",
    "exclude_past": true,
    "require_start_time": true,
    "campuses": ["邯郸", "江湾"],
    "require_location": false,
    "require_source_evidence": false,
    "exclude_tags": []
  },
  "soft": {
    "interest_terms": ["天文", "讲座", "AI"],
    "preferred_campuses": ["江湾"],
    "preferred_time_of_day": "晚上",
    "text_search": "天文",
    "boost_tags": ["社团"]
  },
  "pagination": {
    "page": 1,
    "page_size": 20
  },
  "include_debug": false
}
```

### 字段说明

**`hard`（硬约束）— 必须满足，不满足则直接拒绝：**

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `start_time_after` | string/null | null | 活动开始时间不早于此（ISO 8601 含时区） |
| `start_time_before` | string/null | null | 活动开始时间不晚于此（ISO 8601 含时区） |
| `exclude_past` | bool | true | 拒绝 start_time < now 的过去活动 |
| `require_start_time` | bool | true | 拒绝 start_time 为 null 的活动 |
| `campuses` | string[] | [] | 允许的校区列表；空=不限制 |
| `require_location` | bool | false | 拒绝无地点且非线上的活动 |
| `require_source_evidence` | bool | false | 拒绝无 source_url 且无 evidence_text 的活动 |
| `exclude_tags` | string[] | [] | 活动文本含这些标签则直接拒绝 |

**`soft`（软偏好）— 影响打分排序，不造成拒绝：**

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `interest_terms` | string[] | [] | 兴趣词，匹配越多得分越高（权重 0.30） |
| `preferred_campuses` | string[] | [] | 偏好校区，匹配加分（权重 0.20） |
| `preferred_time_of_day` | string | "" | 时间偏好："晚上"/"下午"/"上午"/"周末"（权重 0.25） |
| `text_search` | string | "" | 全文搜索词（权重 0.30） |
| `boost_tags` | string[] | [] | 匹配标签额外加分 |

**打分权重（与 plan runtime 对齐）：**

| 维度 | 权重 |
|---|---|
| `interest_match` | 0.30 |
| `time_fit` | 0.25 |
| `campus_fit` | 0.20 |
| `source_reliability` | 0.15 |
| `freshness` | 0.10 |

### 响应体

```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "event": {
          "event_id": "550e8400-...",
          "source_file": "天文定向_星途再望.txt",
          "source_name": "复旦天协",
          "source_url": "http://mp.weixin.qq.com/...",
          "title": "第十一届天文主题定向「星途再望」",
          "summary": "...",
          "start_time": "2026-06-05T13:30:00+08:00",
          "end_time": null,
          "location": "邯郸校区",
          "campus": "邯郸",
          "organizer": "复旦大学天文协会",
          "tags": ["天文", "定向"],
          "evidence_text": "..."
        },
        "score": 0.85,
        "score_components": {
          "interest_match": 1.0,
          "time_fit": 0.7,
          "campus_fit": 0.9,
          "source_reliability": 0.8,
          "freshness": 0.71
        },
        "matched_terms": ["天文"]
      }
    ],
    "total": 3,
    "page": 1,
    "page_size": 20,
    "total_before_filter": 8,
    "rejections": [],
    "is_stale": false
  },
  "message": "ok"
}
```

### 响应字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `items[].event` | object | 匹配的活动（`AGGREGATED_EVENT_FIELDS` 格式） |
| `items[].score` | float | 综合得分 0~1 |
| `items[].score_components` | object | 各维度得分明细 |
| `items[].matched_terms` | string[] | 匹配到的兴趣词 |
| `total` | int | 过滤+打分后的总数（分页前） |
| `total_before_filter` | int | 硬约束过滤前的活动总数 |
| `rejections` | object[] | 调试信息：被拒绝的活动及原因（仅 `include_debug=true`） |
| `is_stale` | bool | 数据源是否可能过期（所有活动均为过去 / 超出 TTL） |

### `is_stale` 判断逻辑

1. 数据从未抓取过 → `true`
2. 上次抓取距今超过 24 小时（`freshness_ttl`）→ `true`
3. 当前缓存中没有任何 `[now, now+7d]` 窗口内的未来活动 → `true`
4. 以上均不满足 → `false`（数据新鲜且有未来活动可用）

---

## 6. 错误码

| 错误码 | 说明 |
|---|---|
| 0 | 成功 |
| 400 | 请求参数不合法 |
| 401 | 未认证 |
| 404 | 资源不存在 |
| 500 | 服务端内部错误 |
| 1001 | 用户画像未创建 |
| 1002 | 用户画像已存在 |
| 2001 | 生成任务不存在 |
| 2002 | 生成任务超时 |
| 2003 | 时间范围内无匹配活动 |
| 3001 | 来源不存在 |
| 3002 | URL 导入失败 |

---

## 7. 前端轮询建议

`POST /api/agent/plan-day` 返回 202 后，前端按以下策略轮询 `GET /api/agent/runs/{run_id}`：

| 阶段 | 间隔 | 说明 |
|---|---|---|
| 前 10 秒 | 1 秒/次 | 大部分生成在 2-5 秒内完成 |
| 10-30 秒 | 2 秒/次 | 降频 |
| 超过 30 秒 | 5 秒/次，最多 60 秒 | 长尾兜底，超时后展示失败提示 |

前端在拿到 `status: "completed"` 或 `"failed"` 后停止轮询。

---

## 8. 附录 A：校区枚举

| 值 | 说明 |
|---|---|
| `江湾` | 江湾校区 |
| `邯郸` | 邯郸校区 |
| `枫林` | 枫林校区 |
| `张江` | 张江校区 |
| `其他` | 其他/校外 |

---

## 9. 附录 B：活动标签建议

MVP 阶段建议统一使用以下标签体系（算法侧做匹配、前端做展示、数据侧做标注）：

**主题标签**：`AI`、`创业`、`学术`、`职业`、`技术`、`人文`、`艺术`、`体育`、`公益`、`社交`

**形式标签**：`讲座`、`沙龙`、`工作坊`、`比赛`、`展览`、`演出`、`聚会`、`课程`

**风格标签**：`轻松`、`互动`、`实践`、`理论`、`正式`、`自由`

数据入库时，`tags` 字段从以上三个维度各取 0-N 个标签。

---

## 10. 团队开工 Checklist

各角色拿到本文档后可以立即开工的内容：

| 角色 | 可以开始做的事 | 依赖 |
|---|---|---|
| 后端 | 建表、搭 FastAPI 骨架、按本文档定义 Pydantic schema | 无 |
| 前端 | 按本文档 Mock 接口数据，开发 4 个页面 UI 和路由 | 无 |
| 数据 | 调研目标来源、写抓取脚本、按 events 字段结构入库 | sources 表 |
| 算法 | 实现 filter/score 规则函数、LLM prompt 模板、plan-day 流程编排 | events 表 + 画像 |
| 联调/测试 | 准备演示数据、写接口测试用例、搭建 Docker Compose 环境 | 无 |

---

本文档所有字段名、类型、枚举值与错误码即为前后端契约。后端实现时字段名请严格保持一致（snake_case JSON），如有调整需同步更新本文档并通知全员。
