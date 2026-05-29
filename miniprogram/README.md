# 微信小程序前端 T0

本目录是校园日程 AI 助手的小程序前端原型。

## 页面

- `pages/profile`：偏好设置页，收集校区、身份、兴趣、时间和活动风格。
- `pages/plan`：日程输入页，收集 `request_text` 和 `date_scope`。
- `pages/loading`：生成中页面，轮询后端 `plan_run` 状态机。
- `pages/result`：结果页，渲染后端返回的活动卡片，并处理空字段兜底。

## 本地预览

用微信开发者工具打开本目录：

```text
miniprogram/
```

浏览器静态交互预览在：

```text
docs/previews/miniprogram-t0-preview.html
```

## 当前边界

当前版本请求真实后端联调地址：

```text
http://1.117.75.184:8000/api
```

生成流程：

- `POST /api/agent/plan-day`
- `GET /api/agent/runs/{run_id}`

前端会一直轮询到 `completed` 后进入结果页；如果返回 `failed` 或轮询超时，会停在错误提示。

字段契约见：

```text
docs/frontend-api-contract.md
```
