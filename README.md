<p align="center">
  <img src="docs/NexusLab_logo_trimmed.png" alt="NexusLab" width="420">
</p>

<p align="center">
  一个能听懂自然语言、推荐真实校园活动、安排日程并记住反馈的校园 Agent。
</p>

<p align="center">
  <a href="http://43.161.218.158/nexuslab/"><strong>观看 NexusLab 动态项目介绍</strong></a>
</p>

## 关于 NexusLab

校园里从来不缺活动。公众号、官网和社团通知每天都在更新，但信息散、筛选慢、时间地点容易冲突，真正做出一份适合自己的安排并不轻松。

NexusLab 希望把这件事变成一次自然的对话。你可以直接说：

> 周末想找轻松一点、能和朋友一起参加、不要太商业化的活动。

系统会理解时间、同伴、兴趣和排除项，从活动库中寻找真实活动，检查时间与校区冲突，给出推荐理由和原始来源，再排成一份可执行的日程。

大模型在其中负责理解口语、抽取活动信息和组织文案；确定性规则负责信息校验、去重、过滤、评分和排程。即使模型暂时不可用，核心规划仍会降级运行，不会凭空新增活动，也不会改乱已经确定的排序。

## 你可以用它做什么

- 用一句自然语言描述今天、明天或本周想参加的活动。
- 查看真实的生成阶段，而不是等待一个虚假的进度动画。
- 获得带时间、地点、来源链接、推荐理由和评分依据的日程。
- 对活动点赞、不喜欢或点击来源，让反馈立即影响下一轮排序。
- 查看历史日程和系统总结出的偏好记忆，也可以随时删除记忆。
- 在数据管理侧查看活动质量、采集记录，并手动触发新一轮采集。

当前仓库实现的是可继续迭代的单用户 MVP。数据来自已配置的信息源，尚不代表覆盖全部校园官网、院系和社团；多用户登录、权限隔离和正式生产运营不在当前版本范围内。

## 项目地图

![NexusLab 项目结构与 Agent 主链路](docs/poster/nexuslab_final_poster.png)

## 工作方式

```text
配置的数据源
  -> 文章抓取与跨轮去重
  -> LLM 提取活动事实
  -> 质量校验与正式数据库入库
  -> 理解用户本轮需求与历史偏好
  -> 检索、评分、冲突检查与排程
  -> 小程序展示来源和推荐理由
  -> like / dislike / 点击来源
  -> 下一轮即时调序与多轮偏好总结
```

采集任务会记录每次运行的真实数量和失败原因，并通过 Redis 锁避免重复执行。文章内容没有变化时不会重复消耗 LLM；内容更新后允许重新提取。计划与查询改写使用不同有效期的 Redis 缓存，Redis 不可用时自动回退到正常规划路径。

## 技术栈

| 层级 | 主要技术 | 用途 |
| --- | --- | --- |
| 用户端 | 微信小程序、WXML、WXSS、JavaScript | 画像设置、规划请求、进度轮询、结果、历史、反馈和记忆 |
| API 服务 | Python 3.10、FastAPI、Uvicorn、Pydantic | 单用户 API、后台任务、数据管理和接口契约 |
| 数据层 | PostgreSQL 15、SQLAlchemy 2、Alembic | 活动、原始文章、规划、反馈、记忆和运行记录持久化 |
| 缓存与调度 | Redis 7、APScheduler | 规划与改写缓存、采集锁、账号轮换游标和定时采集 |
| Agent | 规则检索与评分、可选语义向量、MaaS 兼容 LLM | 意图理解、活动抽取、排序排程、文案和记忆总结 |
| 工程化 | Docker Compose、unittest | 本地服务编排、迁移和回归验证 |

## 仓库结构

```text
nexus-lab/
  backend/                     Agent 服务层、缓存适配和采集互斥锁
  database/                    FastAPI 应用、数据模型、业务服务和数据库测试
    alembic/                   PostgreSQL 版本迁移
    routers/                   画像、规划、历史、反馈、记忆和管理接口
  experiments/                Agent、抽取、采集与诊断实验
    agent_core/                硬约束过滤、软偏好评分和检索核心
    agent_intent_parser/       自然语言意图解析
    agent_plan_runtime/        查询改写、排程、文案生成和 Memory Reflection
    agent_maas_cli/            MaaS 活动结构化抽取工具
    scrapers/                  数据源抓取、文章状态、重试和自动采集
    diagnostics/               正式数据库推荐链路诊断
    pickup/                    文本抽取实验与评估样例
    runtime/                   独立运行时原型
    weixin-scraper/            保留的旧微信抓取 fallback
  miniprogram/                 微信小程序页面、样式和 API 客户端
  docs/                        PRD、架构、接口契约、验收记录和静态预览
  Dockerfile                   FastAPI 服务镜像
  docker-compose.yml           PostgreSQL、Redis 与后端的本地编排
  requirements-dev.txt         仓库级 Python 开发依赖
```

`database/` 是当前正式数据库 API 入口，`backend/` 为它提供 Agent 与基础设施能力；`experiments/` 保留可复现的算法、采集和诊断代码，不是另一套线上 API。

## 如何体验

### 先了解项目

访问 [NexusLab 动态项目介绍](http://43.161.218.158/nexuslab/)，可以更直观地查看项目背景、交互流程、Agent 决策方式和完整链路。

### 使用微信小程序

1. 安装微信开发者工具，并将 [miniprogram](miniprogram/) 作为项目目录导入。
2. 确认 [miniprogram/utils/api.js](miniprogram/utils/api.js) 中的 `API_BASE_URL` 指向可访问的后端。
3. 开发联调时按微信开发者工具提示关闭合法域名校验，生产环境应配置 HTTPS 合法域名。
4. 首次进入先填写校区和兴趣画像，再输入一句活动需求。
5. 等待真实规划任务完成后查看结果；随后可以打开来源、提交反馈、查看历史和管理记忆。

小程序当前使用固定演示用户，不需要登录或切换账号。页面字段和联调边界见 [小程序说明](miniprogram/README.md) 与 [前端 API 契约](docs/frontend-api-contract.md)。

## 本地运行

### 1. 准备配置

```powershell
Copy-Item .env.example .env
```

至少配置 `DATABASE_URL`。`REDIS_URL` 用于缓存和采集协调；`MAAS_API_KEY` 与 `CN8N_API_KEY` 只在启用对应模型或数据源时需要。真实密钥只应保存在本地 `.env`、服务器环境变量或密钥管理服务中，不要提交到 Git。

### 2. 使用 Docker Compose

```powershell
docker compose up -d db redis
docker compose run --rm backend python -m alembic -c database/alembic.ini upgrade head
docker compose up --build -d backend
```

服务启动后访问：

- API 健康检查：`http://localhost:8000/`
- Swagger 接口文档：`http://localhost:8000/docs`
- 数据健康状态：`http://localhost:8000/api/admin/data-health`

### 3. 不使用 Docker

准备好 PostgreSQL 与 Redis 后，在仓库根目录执行：

```powershell
python -m pip install -r requirements-dev.txt
python -m alembic -c database/alembic.ini upgrade head
Set-Location database
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 开始一次规划

首次使用先通过小程序或 `POST /api/profile` 创建演示画像。之后的正式流程是：

```text
POST /api/agent/plan-day
  -> 返回 run_id
GET  /api/agent/runs/{run_id}
  -> 轮询 queued / running / completed / failed
```

规划完成后可以查询历史日程、提交活动反馈和管理记忆。采集、活动导入和数据质量相关能力集中在 `/api/admin`；建议直接通过 Swagger 文档查看当前请求字段，避免 README 与接口契约重复维护。

演示活动可以通过 `POST /api/admin/import-events` 写入正式数据库，也可以由自动采集任务入库。`database/events.json` 只保留兼容或实验用途，不作为正式推荐验收的数据来源。

## 验证开发改动

```powershell
git diff --check
python -m compileall -q backend database experiments
$env:DATABASE_URL='sqlite:///:memory:'
python -m unittest discover
python -m unittest discover -s experiments -p "test*.py"
```

需要检查“正式数据库活动是否真的进入推荐”时，可运行：

```powershell
python experiments/diagnostics/verify_db_recommendation.py
```

该诊断会从 PostgreSQL 读取活动并输出候选、排名、评分构成、是否进入计划和拒绝原因，不使用 JSON stopgap 伪造成功结果。

## 更多资料

- [产品需求文档](docs/PRD.md)
- [前端 API 契约](docs/frontend-api-contract.md)
- [Agent 实验说明](experiments/README.md)
- [Plan Runtime 说明](experiments/agent_plan_runtime/README.md)
- [小程序说明](miniprogram/README.md)

NexusLab 目前已经跑通“理解需求、检索真实活动、生成日程、解释推荐、接收反馈、形成记忆”的单用户闭环。下一步是持续扩充可靠数据源、完善部署与观测，让找校园活动逐渐变成一次简单、可信的对话。
