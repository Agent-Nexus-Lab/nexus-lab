# Agent Experiments — 复旦校园日程 AI 助手

Agent 侧的实验原型、检索核心、抓取管道和数据结构化抽取。

## 目录结构

```
experiments/
  agent_core/              # 检索核心（Python package）
    query.py               #   Intent/Profile/Memory/SearchQuery/SearchResult 类型定义
    time_provider.py        #   时间解析（支持 AGENT_FIXED_NOW 固定时间用于测试）
    search_events.py        #   V2 检索入口：search_events(events, intent, profile, memory, now)
    filters.py              #   硬约束链：时间/校区/地点/来源/排除标签
    scoring.py              #   软偏好评分：兴趣(0.30)+时间适配(0.25)+校区(0.20)+可信度(0.15)+新鲜度(0.10)
    freshness.py            #   过期/陈旧检测：has_future_events(), needs_refresh()
    datasource.py           #   DataSource ABC + DataSourceRegistry + FileTextSource
    pipeline.py             #   PlanDayPipeline 编排器
    seed_filter.py          #   导入前过滤：只保留未来事件
    test_search_events.py   #   30+ 测试用例，覆盖过滤/评分/搜索/新鲜度

  scrapers/                # 微信抓取管道（Python package）
    exporter_client.py     #   wechat-article-exporter HTTP 客户端
    wechat_datasource.py   #   WeChatDataSource — 可注册到 DataSourceRegistry 的 DataSource 实现
    account_list.json       #   目标公众号列表
    account_list.py         #   账户列表 CRUD
    cleanup.py              #   过期事件（>3天）及源文本文件清理
    demo_data.py            #   20 条未来活动演示数据生成

  agent-maas-cli/          # MaaS LLM 结构化抽取
    cli.py                  #   CLI + 批量抽取（调用华为云 DeepSeek-v4-Pro）
    schema.py               #   事件 Schema 验证、校区展开
    prompt.md               #   抽取 System Prompt
    run_eval.py             #   批量测评脚本
    texts/                  #   抓取产出的原始文本文件
    outputs/events.json     #   聚合的结构化事件

  agent-plan-runtime/      # 旧 plan-day runtime（fallback）
    runtime.py              #   plan_day() 完整流水线
    cli.py                  #   CLI 入口
    llm.py                  #   可选 MaaS LLM 改写 summary/reason_text

  weixin-scraper/          # 旧 Playwright 抓取方案（fallback）
    fetch_weixin.py         #   单篇文章抓取（Playwright + MSEdge）
    list_articles.py        #   合集 API 文章发现
    README.md               #   旧方案文档

  wechat-article-exporter/ # 外部工具（git clone，已 gitignore）
```

## 数据流

```
┌─────────────────────────────────────────────────────────────┐
│  wechat-article-exporter (localhost:3000)                   │
│  扫码登录 → 搜索公众号 → 获取文章列表 → 下载文章内容          │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
                scrapers/exporter_client.py
                scrapers/wechat_datasource.py
                       │
                       ▼
              .txt 文件 (texts/ 目录)
                       │
                       ▼
              agent-maas-cli/cli.py
              (MaaS DeepSeek-v4-Pro 结构化抽取)
                       │
                       ▼
              outputs/events.json
                       │
                       ▼
              agent_core/pipeline.py
              (PlanDayPipeline)
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
   agent_core/search_events.py   agent-plan-runtime/runtime.py
   (V2 检索：硬约束过滤          (旧 plan_day：过滤+评分+排程)
    + 软偏好评分 + 分页)
                       │
                       ▼
              SearchResult
              { items, total, rejections, is_stale }
```

## 实现方法

### 确定性两阶段检索

Agent Core 的检索不依赖 LLM，完全基于规则：

1. **硬约束（HardConstraints）**：拒绝不合格事件
   - `filter_start_time` — 过期/缺少时间/超出日期范围
   - `filter_campus` — 校区不匹配
   - `filter_location` — 缺少地点（允许线上活动）
   - `filter_source_evidence` — 缺少来源 URL 或证据文本
   - `filter_excluded_tags` — 匹配排除标签

2. **软偏好（SoftPreferences）**：评分但不拒绝
   - `interest_match` (0.30) — 兴趣关键词匹配
   - `time_fit` (0.25) — 用户可用时间适配
   - `campus_fit` (0.20) — 校区偏好匹配
   - `source_reliability` (0.15) — 来源完整度
   - `freshness` (0.10) — 活动新鲜度（线性衰减，7天归零）

### WeChat DataSource

`scrapers/wechat_datasource.py` 实现了 `DataSource` ABC，可直接注册到 `DataSourceRegistry`：

```python
from agent_core.datasource import DataSourceRegistry
from agent_core.pipeline import PlanDayPipeline
from scrapers import WeChatDataSource, load_account_list

registry = DataSourceRegistry()
for acct in load_account_list():
    registry.register(WeChatDataSource(acct))

pipeline = PlanDayPipeline(registry)
result = pipeline.run_plan_day(profile=..., request_text=..., date_scope=...)
```

## 快速开始

1. 启动 wechat-article-exporter：
   ```bash
   cd experiments/wechat-article-exporter
   yarn dev
   ```

2. 登录：浏览器打开 `http://localhost:3000`，微信扫码

3. 抓取 + 抽取：
   ```bash
   cd experiments
   PYTHONPATH=. python scrapers/wechat_datasource.py  # TODO: 独立 CLI
   ```

4. 生成演示数据：
   ```bash
   PYTHONPATH=. python scrapers/demo_data.py --output agent-maas-cli/outputs/events.json
   ```

5. 运行检索：
   ```bash
   PYTHONPATH=. python -c "
   from agent_core.pipeline import PlanDayPipeline
   from agent_core.datasource import DataSourceRegistry
   ...
   "
   ```

6. 清理过期事件：
   ```bash
   PYTHONPATH=. python scrapers/cleanup.py --dry-run
   PYTHONPATH=. python scrapers/cleanup.py --ttl-days 3
   ```

## Linux 部署

### wechat-article-exporter

**Docker（推荐）**：
```bash
docker pull ghcr.io/wechat-article/wechat-article-exporter:latest
docker run -d -p 3000:3000 \
  -e NITRO_KV_DRIVER=fs \
  -v ./data:/app/.data \
  ghcr.io/wechat-article/wechat-article-exporter:latest
```

**源码构建**（需要 Node.js ≥ 22）：
```bash
git clone https://github.com/wechat-article/wechat-article-exporter.git
cd wechat-article-exporter
corepack enable && corepack prepare yarn@1.22.22 --activate
yarn install
PUPPETEER_SKIP_DOWNLOAD=true yarn dev
```

### Python 依赖

```bash
pip install -r experiments/scrapers/requirements.txt
pip install -r experiments/agent-maas-cli/requirements.txt
```

### 环境变量

| 变量 | 必须 | 说明 |
|------|------|------|
| `MAAS_API_KEY` | ✅ | 华为云 MaaS API 密钥 |
| `MAAS_BASE_URL` | ❌ | MaaS API 地址（默认自动） |
| `MAAS_MODEL` | ❌ | 模型名（默认 deepseek-v4-pro） |
| `AGENT_FIXED_NOW` | ❌ | 固定时间用于 dev/test（ISO 8601） |
| `ENVIRONMENT` | ❌ | 设为 `production` 时强制真实时钟 |

## 开发 vs 生产模式

| 模式 | 时间源 | 数据 | 用途 |
|------|--------|------|------|
| dev/test | `AGENT_FIXED_NOW=2026-06-01T12:00:00+08:00` | 演示数据（20条未来活动） | 回归测试、本地开发 |
| prod | 真实时钟（忽略 AGENT_FIXED_NOW） | 公众号实时抓取 | 实际运行 |

```bash
# Dev mode（时间固定）
AGENT_FIXED_NOW=2026-06-01T12:00:00+08:00 python scrapers/demo_data.py

# Prod mode（强制真实时间）
ENVIRONMENT=production python scrapers/cleanup.py
```

## 旧方案对照

| 方案 | 抓取 | 发现 | 风控 | 状态 |
|------|------|------|------|------|
| **新** (scrapers/) | wechat-article-exporter API | 后台搜索 API | 低（基于合法 session） | ✅ 主要 |
| **旧** (weixin-scraper/) | Playwright + MSEdge | 合集 API | 高（实测被风控） | ⚠️ fallback |

旧方案文件保留在 `weixin-scraper/` 目录中，作为备用。切换方式：
```bash
# 旧方案
python weixin-scraper/fetch_weixin.py <url>
python weixin-scraper/list_articles.py <url> --format json

# 新方案
python scrapers/demo_data.py  # 演示数据
# 或通过 WeChatDataSource 接口
```
