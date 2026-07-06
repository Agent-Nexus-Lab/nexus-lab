# LLM Rewrite Fallback 验收记录

> 李颖哲 | Phase 2
> 验收日期：2026-07-04

---

## 1. 配置信息

| 字段 | 值 |
|---|---|
| PROMPT_VERSION | `2026-07-04-v1` |
| 定义位置 | `experiments/agent_plan_runtime/llm.py` |
| MAAS_MODEL | deepseek-v4-pro |
| MAX_RETRIES | 2 |

## 2. used_fallback 追踪

- **实现位置**: `experiments/agent_plan_runtime/runtime.py` `apply_rewrite()`
- **追踪字段**: `debug["used_fallback"]`（布尔值）、`debug["prompt_version"]`（字符串）、`debug["llm_error"]`（异常时记录）
- **rewrite 成功时**: `used_fallback = False`，`prompt_version = "2026-07-04-v1"`
- **rewrite 异常时**: `used_fallback = True`，`llm_error = <异常信息>`，plan_day 仍返回 `status: completed`

## 3. 验收测试结果

### 3.1 test_rewrite_fallback_on_timeout
- **场景**: 模拟 rewriter 抛出 `RuntimeError("simulated timeout")`
- **结果**: PASSED
- **验证**:
  - `result["data"]["status"]` = `"completed"` ✅
  - `result["data"]["debug"]["used_fallback"]` = `true` ✅
  - `"simulated timeout"` in `result["data"]["debug"]["llm_error"]` ✅
  - 模板 summary 仍然存在且非空 ✅

### 3.2 test_rewrite_disabled_has_readable_summary
- **场景**: rewriter=None（LLM改写关闭）
- **结果**: PASSED
- **验证**:
  - `result["data"]["status"]` = `"completed"` ✅
  - summary 包含"活动"和"天文" ✅
  - reason_text 包含"邯郸"和"评分"（来自模板） ✅

### 3.3 test_llm_unknown_event_id_is_ignored（已有测试, 未修改）
- **场景**: LLM 返回未识别的 event_id
- **结果**: PASSED ✅

### 3.4 ENABLE_LLM_REWRITE=false 时主链路正常
- **验证方式**: `test_rewrite_disabled_has_readable_summary` 和所有没有 rewriter 的现有测试
- **结果**: 所有 9 个 runtime 测试 PASSED ✅

## 4. 结论

LLM rewrite fallback 机制工作正常：
- ✅ plan_day completed 不依赖 LLM rewrite
- ✅ 异常时自动回退到模板 summary/reason
- ✅ used_fallback 和 llm_error 可追踪
- ✅ PROMPT_VERSION 用于审计
- ✅ 关闭 rewrite 时仍有可读输出
