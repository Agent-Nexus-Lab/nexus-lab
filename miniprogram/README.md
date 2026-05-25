# 微信小程序前端 T0

本目录是校园日程 AI 助手的小程序前端原型。

## 页面

- `pages/profile`：偏好设置页，收集校区、身份、兴趣、时间和活动风格。
- `pages/plan`：日程输入页，收集 `request_text` 和 `date_scope`。
- `pages/loading`：生成中页面，用 `setInterval` 模拟轮询和 loading 进度。
- `pages/result`：结果页，渲染本地 mock JSON 活动卡片。

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

当前版本只跑本地假交互，不请求真实后端。后续联调时可将：

- `POST /api/agent/plan-day`
- `GET /api/agent/runs/{run_id}`

替换掉 `pages/loading/loading.js` 中的 mock 逻辑。
