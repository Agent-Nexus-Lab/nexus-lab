<p align="center">
  <img src="docs/NexusLab_logo_trimmed.png" alt="NexusLab" width="420">
</p>

复旦校园日程 AI 助手 MVP 仓库。项目目标是从校园活动信息源中抽取结构化活动，结合用户画像、时间范围和偏好，生成可展示在微信小程序里的个性化活动日程。

## Project Map

![NexusLab 项目结构与 Agent 主链路](docs/poster/nexuslab_final_poster.png)

## Repository Structure

```text
nexus-lab/
  backend/        Agent plan-day 服务层与 schema，封装检索、评分、排程和可选 LLM 改写
  database/       FastAPI 数据库服务、SQLAlchemy models、Alembic migrations、画像/日程/API 路由
  miniprogram/    微信小程序前端原型
  experiments/    Agent core、MaaS 抽取、微信抓取、intent parser 和 runtime 原型
  docs/           PRD、API 字段定义、架构文档、前端契约和静态预览
```

当前主线中，`database/` 是带数据库的 FastAPI 服务；`backend/` 是 Agent 运行时服务层代码，不再承载旧数据库路由。

## Environment

复制环境变量模板并填写真实配置：

```powershell
Copy-Item .env.example .env
```

`.env` 至少需要：

```dotenv
DATABASE_URL=postgresql://postgres:password@localhost:5432/campus_ai
MAAS_API_KEY=
MAAS_BASE_URL=https://api.modelarts-maas.com/openai/v1
MAAS_MODEL=deepseek-v4-pro
```

`.env` 已被 `.gitignore` 忽略，不要提交真实数据库密码或 MaaS API key。

## Install

安装全部本地开发依赖：

```powershell
python -m pip install -r requirements-dev.txt
```

也可以按模块单独安装：

```powershell
python -m pip install -r database/requirements.txt
python -m pip install -r experiments/agent_maas_cli/requirements.txt
python -m pip install -r experiments/scrapers/requirements.txt
python -m pip install -r experiments/weixin-scraper/requirements.txt
```

## Run

### Database API

```powershell
cd database
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

常用接口：

```text
POST /api/profile
POST /api/agent/plan-day
GET  /api/agent/runs/{run_id}
GET  /api/plans
GET  /api/admin/events
```

数据库迁移：

```powershell
python -m alembic -c database/alembic.ini current
python -m alembic -c database/alembic.ini upgrade head
```

导入演示活动数据：

```powershell
cd database
python import_events.py
```

### Miniprogram

用微信开发者工具打开：

```text
miniprogram/
```

前端当前默认联调地址和字段契约见：

```text
docs/frontend-api-contract.md
miniprogram/README.md
```

浏览器静态预览：

```text
docs/previews/miniprogram-t0-preview.html
```

### Agent Experiments

Agent 实验和数据流详见：

```text
experiments/README.md
```

常用命令：

```powershell
python experiments/agent_plan_runtime/cli.py `
  --request-text "这周想看天文或图书馆活动，最好轻松一点" `
  --date-scope this_week `
  --now 2026-06-15T12:00:00+08:00 `
  --include-debug

python -m unittest discover -s experiments/agent_core
python -m unittest discover -s experiments/agent_plan_runtime
python -m unittest discover -s experiments/agent-intent-parser
```

## Verification

合并或提交前建议至少运行：

```powershell
git diff --check
python -m compileall -q backend database experiments
python -m unittest discover -s experiments/agent_core
python -m unittest discover -s experiments/agent_plan_runtime
python -m unittest discover -s experiments/agent-intent-parser
```

如需验证 Alembic 配置但不连接真实 PostgreSQL，可临时使用 SQLite：

```powershell
$env:DATABASE_URL='sqlite:///:memory:'
python -m alembic -c database/alembic.ini current
```

## Notes

- `experiments/agent_maas_cli/outputs/events.json` 是当前 Agent demo/runtime 使用的结构化事件样本。
- `experiments/scrapers/` 是较新的微信抓取管道；`experiments/weixin-scraper/` 是旧抓取方案 fallback。
- 微信小程序联调依赖后端 `plan_run` 状态机：`queued` / `running` / `completed` / `failed`。
- 真实密钥、数据库密码、请求日志和未授权敏感数据不得提交。
