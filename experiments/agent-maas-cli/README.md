# 活动信息结构化抽取 CLI

本目录是 Agent 侧探索性脚本，用于验证“信息源原文 -> 活动抽取中间结构”的 prompt 和 MaaS 调用链路。代码不属于后端主源文件。

## 1. 用途

输入：校园官网、学院通知、公众号转写等信息源原文。

处理：调用华为云 MaaS `deepseek-v4-pro`，按 `prompt.md` 抽取活动事实。

输出：`docs/API字段定义_MVP版.md` 5.5 节定义的活动信息抽取中间结构。

不负责：

- 处理最终用户需求文本。
- 推荐、排序、冲突检查或日程组合。
- 生成 `event_id`、`quality_score`、`verification_status`、`is_user_visible` 等入库/审核字段。
- 生成 `reason_text`、`display_order` 等 `plan-day` 推荐结果字段。

## 2. 环境准备

```powershell
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
python -m pip install -r experiments\agent-maas-cli\requirements.txt
```

在仓库根目录 `.env` 配置开发环境变量：

```dotenv
MAAS_API_KEY=你的华为云MaaS_API_Key
MAAS_BASE_URL=https://api.modelarts-maas.com/openai/v1
MAAS_MODEL=deepseek-v4-pro
MAAS_API_STYLE=openai
MAAS_TEMPERATURE=0.1
MAAS_MAX_TOKENS=4096
MAAS_THINKING=disabled
TIMEZONE=Asia/Shanghai
```

注意：

- `.env` 已被 `.gitignore` 排除，不能提交。
- 不要在命令行、日志或文档里输出真实 `MAAS_API_KEY`。
- 本项目约束禁止直接读取或展示 `.env` 内容。

## 3. 使用方式

测评目录：

- 输入：`experiments/agent-maas-cli/texts/`
- 输出：`experiments/agent-maas-cli/outputs/`
- `texts/` 支持 `.txt`、`.md`、`.html`。
- `outputs/` 放同名 `.json` 测评输出，可随本目录提交。

批量跑全部测评：

```powershell
python experiments\agent-maas-cli\run_eval.py
```

只跑指定序号：

```powershell
python experiments\agent-maas-cli\run_eval.py --range 1-3
python experiments\agent-maas-cli\run_eval.py --range 1,3,5-7
```

只生成请求体，不调用 MaaS：

```powershell
python experiments\agent-maas-cli\run_eval.py --range 1-2 --dry-run --output-dir experiments\agent-maas-cli\outputs\dry-run
```

直接使用底层 CLI：

```powershell
python experiments\agent-maas-cli\cli.py --input-file experiments\agent-maas-cli\texts\1.txt --output-file experiments\agent-maas-cli\outputs\1.json --reference-date 2026-05-20
```

可显式传信息源元数据：

```powershell
python experiments\agent-maas-cli\cli.py --input-file sample.txt --source-name "计算机学院官网" --source-url "https://example.edu.cn/events/123" --reference-date 2026-05-20
```

## 4. 输出结构

```json
{
  "source_name": "复旦天协",
  "source_url": null,
  "events": [
    {
      "title": "路边天文 | 春末夏初，群星交替",
      "summary": "5月15日20:00在光草东北角举办路边天文观测活动。",
      "start_time": "2026-05-15T20:00:00+08:00",
      "end_time": null,
      "location": "光草东北角",
      "campus": null,
      "organizer": "复旦天协",
      "tags": ["天文", "观星"],
      "evidence_text": "时间：今晚（5.15）20:00开始\n地点：光草东北角"
    }
  ],
  "warnings": []
}
```

抽取失败或无活动时：

- `events=[]`
- `warnings` 写明失败或不确定原因

## 5. 开发说明

文件职责：

- `cli.py`：读取输入、加载环境变量、调用 MaaS、输出 JSON。
- `run_eval.py`：批量测评入口，默认处理 `texts/` 全部文件，支持序号范围。
- `prompt.md`：结构化抽取 prompt。
- `schema.py`：MaaS tool schema、输出归一化和本地校验。
- `requirements.txt`：脚本依赖。

CLI 常用参数：

| 参数 | 说明 |
|---|---|
| `--text` | 直接传入信息源原文 |
| `--input-file` | 从 UTF-8 文件读取信息源原文 |
| `--input-dir` | 批量读取输入目录 |
| `--output-file` / `--output-dir` | 写入输出文件或目录 |
| `--source-name` / `--source-url` | 信息源元数据，优先写入输出 |
| `--reference-date` | 解析相对日期的参考日期 |
| `--timeout` / `--max-tokens` | MaaS 请求参数，可按需要覆盖 |
| `--thinking` | 深度思考开关，抽取任务默认 `disabled` |
| `--dry-run` | 只生成请求体，不发起网络请求 |
| `--strict` | 调用或校验失败时直接抛错 |

`run_eval.py` 常用参数：

| 参数 | 说明 |
|---|---|
| `--range 1-3` | 只跑指定编号范围 |
| `--range 1,3,5-7` | 支持逗号组合 |
| `--input-dir` / `--output-dir` | 覆盖测评输入/输出目录 |
| `--reference-date` | 传给底层 CLI |
| `--timeout` / `--max-tokens` | 可选，传给底层 CLI |
| `--thinking` | 默认 `disabled` |
| `--dry-run` | 只生成请求体 |
| `--stop-on-error` | 遇到失败立即停止 |

开发自检：

```powershell
python -m py_compile experiments\agent-maas-cli\cli.py experiments\agent-maas-cli\schema.py experiments\agent-maas-cli\run_eval.py
python experiments\agent-maas-cli\run_eval.py --range 1-2 --dry-run --output-dir experiments\agent-maas-cli\outputs\dry-run
```
