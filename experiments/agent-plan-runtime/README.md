# Plan Runtime Pipeline Prototype

This directory is the Agent-side prototype for the MVP `plan-day` runtime. It reads the existing extraction output at `experiments/agent-maas-cli/outputs/events.json` and keeps filtering, scoring, commute checks, and schedule building in deterministic Python code.

The MaaS/LLM path is optional and only rewrites `summary` and `reason_text` after the code pipeline has selected activities. It must not add, remove, or replace events.

## Run

```powershell
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

python experiments\agent-plan-runtime\cli.py `
  --request-text "这周想看天文或图书馆活动，最好轻松一点" `
  --date-scope this_week `
  --now 2026-05-09T12:00:00+08:00 `
  --include-debug
```

The sample `events.json` is dated before `2026-05-25`, so real "now" will correctly return no future activities. Use `--now` for deterministic demos against the sample data.

## Campus and Commute Rules

- Missing `campus` values in the sample `events.json` are filled as `邯郸` by extraction post-processing.
- Runtime output uses API enum values such as `邯郸` and `江湾`; legacy labels like `邯郸校区` are normalized when encountered.
- Same-campus schedule buffer: 15 minutes.
- `邯郸 <-> 江湾`: 30 minutes.
- `邯郸 <-> 枫林`: 60 minutes.
- Unknown cross-campus commute: 60 minutes until the matrix is completed.

## Optional LLM Rewrite

```powershell
$env:MAAS_API_KEY = "<set outside logs>"
python experiments\agent-plan-runtime\cli.py `
  --request-text "这周想看天文或图书馆活动，最好轻松一点" `
  --date-scope this_week `
  --now 2026-05-09T12:00:00+08:00 `
  --llm-mode maas `
  --include-debug
```

Do not print or commit API keys. If MaaS returns an unknown `event_id`, the runtime ignores that rewrite and keeps the template reason.

## Checks

```powershell
python -m py_compile `
  experiments\agent-plan-runtime\cli.py `
  experiments\agent-plan-runtime\llm.py `
  experiments\agent-plan-runtime\runtime.py `
  experiments\agent-plan-runtime\test_runtime.py
python -m unittest discover -s experiments\agent-plan-runtime
```
