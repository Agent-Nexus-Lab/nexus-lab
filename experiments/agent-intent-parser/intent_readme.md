# Intent Parser — 意图解析器

> 李颖哲 | agent 的 query 理解和 LLM 输出层  
> 最后更新：2026-05-26

---

## 1. 概述

Intent Parser 是 Agent Runtime 的第一个环节。它把用户的一句话 query 解析为结构化意图，供下游 `search_events()` 消费。

**核心原则**：

- Intent 只负责用户**这一次明确表达**的需求（"今天下午"、"不要讲座"、"特别喜欢天文"）
- 长期偏好来自 Profile，历史反馈来自 Memory，最终 hard/soft 约束由 `search_events._build_query()` 统一整合

---

## 2. 文件结构

```
experiments/agent-intent-parser/
├── schemas.py              # Pydantic 模型定义
├── intent_parser.py        # 核心解析器（规则引擎 + LLM 可选）
├── eval.json               # 评测集（7 条典型 query）
├── test_intent_parser.py   # 回归测试（17 个用例）
└── intent_readme.md        # 本文档
```

---

## 3. API

### 3.1 主入口

```python
from intent_parser import parse_intent

result = parse_intent(
    "今天下午在江湾有没有天文相关的轻松活动",
    use_llm=False,  # 默认用规则引擎
)
```

返回值：`IntentParseOutput`（Pydantic 模型）

### 3.2 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `request_text` | `str` | `""` | 用户原始 query |
| `date_scope` | `Literal["today","tomorrow","this_week"]` | `"this_week"` | 时间范围 |
| `explicit_campuses` | `list[str]` | `[]` | 用户明确提到的校区（邯郸/江湾/枫林/张江），解析不到为 `[]` |
| `max_items` | `int` | `4` | 用户想要的活动数，如说"3个"→3，没说默认 4 |
| `time_preference` | `TimePreference` | 全 `false` | 时段偏好（morning/afternoon/evening/weekend），解析不到全 `false` |
| `interest_tags` | `list[str]` | `[]` | 从 query 解析到的兴趣词（天文/AI/戏剧等），解析不到为 `[]` |
| `style_tags` | `list[str]` | `[]` | 从 query 解析到的风格标签（轻松/互动/正式等），解析不到为 `[]` |
| `hard_constraints` | `list[HardConstraint]` | `[]` | 由规则引擎提取的硬约束（如"不要XX"），LLM 不生成 |
| `soft_constraints` | `list[SoftConstraint]` | `[]` | 由规则引擎提取的软偏好（如"特别喜欢XX"），LLM 不生成 |
| `parsed_successfully` | `bool` | `true` | 解析是否成功 |
| `parse_warnings` | `list[str]` | `[]` | 解析过程中的警告信息 |

### 3.3 HardConstraint 结构

```python
class HardConstraint(BaseModel):
    field: str      # excluded_keywords / excluded_tags / campus / date_scope
    operator: str   # eq / ne / contains
    value: str      # 约束值

# 示例：
# "不要讲座" → HardConstraint(field="excluded_keywords", operator="contains", value="讲座")
```

### 3.4 SoftConstraint 结构

```python
class SoftConstraint(BaseModel):
    field: str      # interest_tags / style_tags
    weight: float   # 0.0=排除, 0.5=不太喜欢, 1.0=喜欢, 1.5=特别喜欢, 2.0=强烈偏好
    value: str      # 偏好值

# 示例：
# "特别喜欢天文" → SoftConstraint(field="interest_tags", weight=1.5, value="天文")
# "最好轻松一点" → SoftConstraint(field="interest_tags", weight=1.2, value="轻松一点")
```

### 3.5 桥接到 agent_core

```python
from intent_parser import parse_intent, to_agent_intent

parsed = parse_intent("今天下午在江湾有没有天文活动")
agent_intent = to_agent_intent(parsed)
# => {"request_text": "...", "date_scope": "today", "explicit_campuses": ("江湾",), "max_items": 4}

# 然后传给 search_events:
from agent_core.search_events import search_events
result = search_events(events, intent=agent_intent, profile=profile)
```

---

## 4. 解析架构

```
用户 query
    │
    ▼
┌─────────────────────────────────────────┐
│ parse_intent(query, use_llm=False)      │
│                                         │
│  ┌─ 阶段一：基础字段提取（规则/LLM）──┐  │
│  │ date_scope     ← 今天/明天/周末    │  │
│  │ time_preference ← 上午/下午/晚上   │  │
│  │ interest_tags  ← 白名单匹配（30+） │  │
│  │ style_tags     ← 风格词匹配       │  │
│  │ explicit_campuses ← 校区关键词    │  │
│  │ max_items      ← "3个" → 3       │  │
│  └───────────────────────────────────┘  │
│                                         │
│  ┌─ 阶段二：hard/soft 补全（仅规则）──┐  │
│  │ hard_constraints  ← 不要XX/别XX   │  │
│  │ soft_constraints  ← 特别喜欢XX    │  │
│  │ LLM 不参与此阶段                   │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

**规则引擎**（默认）：零延迟，基于正则 + 关键词白名单。

**LLM 模式**（`use_llm=True`）：调用 MaaS API + `response_format: json_object` 做更灵活的字段提取。LLM 只负责阶段一的基础字段，不生成 hard/soft 约束。失败自动回退规则引擎。

---

## 5. 规则清单

### 5.1 时间范围 (date_scope)

| 关键词 | 解析结果 |
|---|---|
| 今天/今日/今晚/今儿 | `today` |
| 明天/明日/明晚 | `tomorrow` |
| 本周/这周/周末/周六/周日 | `this_week` |
| 无明确时间词 | `today`（默认） |

### 5.2 时段偏好 (time_preference)

| 关键词 | 字段 |
|---|---|
| 早上/上午/早起/早晨 | `morning: true` |
| 下午/午后 | `afternoon: true` |
| 晚上/今晚/晚间/夜间/傍晚 | `evening: true` |
| 周末/周六/周日 | `weekend: true` |

### 5.3 兴趣词 (interest_tags) — 白名单（30+）

```
AI / 人工智能 / 大模型 / 创业 / 天文 / 观星 / 戏剧 / 工作坊
分享会 / 学术 / 参观 / 展览 / 图书馆 / 体育 / 游泳 / 音乐
吉他 / 职业 / 就业 / 公益 / 社交 / 讲座 / 沙龙 / 比赛
演出 / 聚会 / 课程 / 返校日 / 开放日
```

### 5.4 风格标签 (style_tags)

| 风格 | 匹配词 |
|---|---|
| 轻松 | 轻松 / 休闲 / 随意 / 不累 / 别太累 / 放松 / 轻松一点 |
| 互动 | 互动 / 交流 / 讨论 / 参与 |
| 正式 | 正式 / 学术 / 专业 / 严肃 |
| 实践 | 实践 / 实操 / 实验 / 训练 |
| 安静 | 安静 / 不吵 / 清静 |
| 热闹 | 热闹 / 嗨 / 气氛好 |

### 5.5 校区 (explicit_campuses)

| 校区 | 匹配词 |
|---|---|
| 邯郸 | 邯郸 / 本部 |
| 江湾 | 江湾 |
| 枫林 | 枫林 |
| 张江 | 张江 |

### 5.6 硬约束 (hard_constraints) — 排除模式

| 模式 | 正则 | 示例 |
|---|---|---|
| 不要/别/不想/排除 | `(?:不要\|别\|不想\|...)\s*去?\s*([^\s]*){1,8}` | "不要讲座" → `{field: "excluded_keywords", value: "讲座"}` |
| 不想要/不需要/不想去 | `(?:不想要\|不需要\|不想去)([^\s]*){1,8}` | "不想要运动" → `{field: "excluded_keywords", value: "运动"}` |

### 5.7 软约束 (soft_constraints) — 偏好权重

| 模式 | 权重 | 示例 |
|---|---|---|
| 特别喜欢/非常喜欢/超爱/特别想 | `1.5` | "特别喜欢天文" → 权重 1.5 |
| 喜欢/想/最好/尽量 | `1.2` | "最好AI相关" → 权重 1.2 |
| 不太喜欢/不太想/一般 | `0.5` | "不太喜欢体育" → 权重 0.5 |

---

## 6. 评测集

| ID | Query | 关键测试点 |
|---|---|---|
| eval_001 | 今天下午在江湾有没有天文相关的轻松活动 | date_scope + explicit_campuses + interest_tags + style_tags |
| eval_002 | 今晚想看AI相关但不要讲座的活动 | hard_constraint 排除"讲座" + evening |
| eval_003 | 周末想去看展览或者参加工作坊，最好在邯郸或者枫林 | this_week + 多兴趣 + 多校区 + soft_constraint |
| eval_004 | 这周邯郸的戏剧或者演出，不要讲座 | 校区约束 + hard_constraint 排除 |
| eval_005 | 明天晚上特别喜欢天文，最好是互动类型的活动 | 喜爱偏好 weight≥1.5 + 多约束 |
| eval_006 | 最近有什么好玩的 | 极限模糊查询，所有字段为空 |
| eval_007 | 下午想看2个AI或者创业相关的分享会，轻松一点 | max_items=2 + 多兴趣 + 风格 |

---

## 7. 运行测试

```powershell
python -m unittest discover -s experiments/agent-intent-parser -v
```

预期输出：**17 tests OK**

---

## 8. 与下游的协作

```
Intent Parser (李颖哲)
    │
    │  IntentParseOutput
    ▼
to_agent_intent() / to_agent_intent_extended()
    │
    │  {"request_text", "date_scope", "explicit_campuses", "max_items"}
    ▼
search_events(events, intent=..., profile=..., memory=...)  (曹昕宇)
    │
    │  Intent + Profile + Memory → HardConstraints + SoftPreferences
    ▼
过滤 → 打分 → 分页 → 日程
```

Intent Parser 的 `hard_constraints` / `soft_constraints` 是**可选的补充信息**。`search_events._build_query()` 会从 Intent + Profile + Memory 自行派生最终约束。Parser 提取到的硬/软约束可以通过 `to_agent_intent_extended()` 获取，供下游按需使用。
