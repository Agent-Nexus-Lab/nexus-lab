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
