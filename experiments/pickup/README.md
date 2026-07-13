# 活动信息结构化抽取原型

本目录是 Agent 侧探索性脚本，用于验证“信息源原文 -> 活动候选事件集”的 MaaS 调用、prompt 和输出结构。代码不并入后端主源文件。

## 1. 任务边界

输入是上游信息源原文，例如校园官网通知、学院公告、公众号转写文本；不是用户对话输入。

脚本负责：

- 调用华为云 MaaS `deepseek-v4-pro` 抽取活动事实。
- 批量处理 `texts/` 下的测试文本。
- 聚合输出一个 `outputs/events.json`。
- 为每条活动候选生成 UUIDv4 `event_id`。

脚本不负责：

- 用户推荐、排序、冲突检查或日程组合。
- 生成 `quality_score`、`verification_status`、`is_user_visible`、`reason_text`、`display_order` 等后续阶段字段。
- 数据入库、审核流、前端展示或后端通用 API。

## 2. 环境变量

在仓库根目录 `.env` 配置开发环境变量：

```dotenv
MAAS_API_KEY=你的华为云MaaS_API_Key
MAAS_BASE_URL=https://api.modelarts-maas.com/openai/v1
MAAS_MODEL=deepseek-v4-pro
MAAS_API_STYLE=openai
MAAS_TEMPERATURE=0.1
MAAS_THINKING=disabled
TIMEZONE=Asia/Shanghai
```

注意：

- `.env` 已被 `.gitignore` 排除，不能提交。
- 不要在命令行、日志或文档里输出真实 `MAAS_API_KEY`。
- 本项目约束禁止直接读取或展示 `.env` 内容；需要验证时只运行脚本或检查变量是否存在。
- `MAAS_MAX_TOKENS`、`MAAS_TIMEOUT` 可按需要临时设置；脚本默认不额外传这两个限制。

安装依赖：

```powershell
python -m pip install -r experiments\agent-maas-cli\requirements.txt
```

PowerShell 中文输出如有乱码，先设置 UTF-8：

```powershell
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
```

## 3. 输入输出目录

- 输入目录：`experiments/agent-maas-cli/texts/`
- 输出文件：`experiments/agent-maas-cli/outputs/events.json`
- `texts/` 支持 `.txt`、`.md`、`.html`。
- `outputs/events.json` 和测试文本作为测评材料可以提交，但不得包含密钥、账号信息、完整请求日志或未授权敏感数据。

默认批量处理全部文本：

```powershell
python experiments\agent-maas-cli\run_eval.py
```

只跑指定序号：

```powershell
python experiments\agent-maas-cli\run_eval.py --range 1-3
python experiments\agent-maas-cli\run_eval.py --range 1,3,5-7
```

如果账号侧出现 MaaS 限流，可以临时增加调用间隔：

```powershell
python experiments\agent-maas-cli\run_eval.py --delay-seconds 22
```

如果模型偶发空结果或截断输出，可以临时增加重试或输出上限：

```powershell
python experiments\agent-maas-cli\run_eval.py --retries 1 --max-tokens 16000
```

指定聚合输出文件：

```powershell
python experiments\agent-maas-cli\run_eval.py --output-file experiments\agent-maas-cli\outputs\events.json
```

只生成请求体，不调用 MaaS：

```powershell
python experiments\agent-maas-cli\run_eval.py --range 1-2 --dry-run
```

底层 CLI 可用于单条调试：

```powershell
python experiments\agent-maas-cli\cli.py --input-file experiments\agent-maas-cli\texts\1.txt --reference-date 2026-05-20
```

底层 CLI 也支持目录模式，并写入同一个 `events.json`：

```powershell
python experiments\agent-maas-cli\cli.py --input-dir experiments\agent-maas-cli\texts --output-dir experiments\agent-maas-cli\outputs --reference-date 2026-05-20
```

## 4. 输出结构

正式测评输出为一个 JSON 对象，顶层只包含 `events`：

```json
{
  "events": [
    {
      "event_id": "550e8400-e29b-41d4-a716-446655440000",
      "source_file": "1.txt",
      "source_name": "复旦天协",
      "source_url": null,
      "title": "路边天文 | 春末夏初，群星交替",
      "summary": "5月15日20:00在光草东北角举办路边天文观测活动。",
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

字段定义以 `docs/API字段定义_MVP版.md` 5.5 节为准。`event_id` 由脚本在每次聚合时生成 UUIDv4，因此重复运行会变化。

校区规则：

- `campus` 使用 `邯郸`、`江湾`、`枫林`、`张江`、`其他`。
- 原文未明确校区时默认 `邯郸`。
- 同一活动明确涉及多个校区时拆成多条 event，每条 event 只保留一个 `campus`。

## 5. 文件职责

- `cli.py`：底层调用入口，读取输入、加载环境变量、调用 MaaS、输出单条抽取结果或批量聚合结果。
- `run_eval.py`：测评入口，默认读取 `texts/` 全部文件并生成 `outputs/events.json`，支持序号范围。
- `prompt.md`：单条信息源活动事实抽取 prompt。
- `schema.py`：MaaS tool schema、单条抽取归一化、聚合输出校验。
- `REPORT.md`：基于测试文本和 `events.json` 的测评结论。

常用自检：

```powershell
python -m py_compile experiments\agent-maas-cli\cli.py experiments\agent-maas-cli\schema.py experiments\agent-maas-cli\run_eval.py
python experiments\agent-maas-cli\run_eval.py --range 1-2 --dry-run
```
