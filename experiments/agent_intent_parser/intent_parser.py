from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from .schemas import HardConstraint, IntentParseOutput, SoftConstraint, TimePreference

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_BASE_URL = "https://api.modelarts-maas.com/openai/v1"
DEFAULT_MODEL = "deepseek-v4-flash"
MAX_RETRIES = 1

DATE_SCOPE_KEYWORDS: dict[str, list[str]] = {
    "today": ["今天", "今日", "今晚", "今儿", "今"],
    "tomorrow": ["明天", "明日", "明", "明晚"],
    "this_week": ["本周", "这周", "这个星期", "这周内", "本周内", "周末", "周六", "周日"],
}

TIME_KEYWORDS: dict[str, list[str]] = {
    "morning": ["早上", "上午", "早起", "早晨", "晨"],
    "afternoon": ["下午", "午后"],
    "evening": ["晚上", "今晚", "晚间", "夜间", "傍晚", "晚饭后"],
    "weekend": ["周末", "周六", "周日", "星期六", "星期日"],
}

STYLE_TERMS: dict[str, list[str]] = {
    "轻松": ["轻松", "休闲", "随意", "不累", "别太累", "不想太累", "放松", "轻松一点"],
    "互动": ["互动", "交流", "讨论", "参与", "动手"],
    "正式": ["正式", "学术", "专业", "严肃"],
    "实践": ["实践", "实操", "动手", "实验", "训练"],
    "安静": ["安静", "安静一点", "不吵", "清静"],
    "热闹": ["热闹", "嗨", "气氛好"],
}

CAMPUS_KEYWORDS: dict[str, list[str]] = {
    "邯郸": ["邯郸", "本部"],
    "江湾": ["江湾"],
    "枫林": ["枫林"],
    "张江": ["张江"],
}

KNOWN_INTEREST_TERMS: list[str] = [
    "AI", "人工智能", "大模型", "创业", "天文", "观星", "戏剧", "工作坊",
    "分享会", "学术", "参观", "展览", "图书馆", "体育", "游泳", "音乐",
    "吉他", "职业", "就业", "公益", "社交", "讲座", "沙龙", "比赛",
    "演出", "聚会", "课程", "返校日", "开放日",
]

EXCLUSION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?:不要|别|不想|排除|除了|去掉|避免)\s*去?\s*([^\s，。！？,!?;；的了吧呢吗啊]{1,8})"), "contains"),
    (re.compile(r"(?:不想要|不需要|不想去)([^\s，。！？,!?;；的了吧呢吗啊]{1,8})"), "contains"),
    (re.compile(r"(?:只要|必须在|只去)([^\s，。！？,!?;；的了吧呢吗啊]{1,8})"), "eq"),
    (re.compile(r"(?:换一个|换点|换个|换点别的|换一个别的)([^\s，。！？,!?;；的了吧呢吗啊]{0,8})"), "contains"),
]

PREFERENCE_PATTERNS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"(?:特别喜欢|非常喜欢|超爱|最爱|尤其喜欢|更喜欢|特别想|非常想|更偏|更想要|更想|更偏向|更倾向于)\s*([^\s，。！？,!?;；的了吧呢吗啊]{1,8})"), 1.5),
    (re.compile(r"(?:喜欢|想|最好|尽量)\s*([^\s，。！？,!?;；的了吧呢吗啊]{1,8})"), 1.2),
    (re.compile(r"(?:不太喜欢|不太想|一般)\s*([^\s，。！？,!?;；的了吧呢吗啊]{1,8})"), 0.5),
]


def parse_intent(
    query: str,
    *,
    profile: Optional[dict[str, Any]] = None,
    use_llm: bool = False,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
) -> IntentParseOutput:
    if not query.strip():
        return IntentParseOutput(
            request_text=query,
            parsed_successfully=False,
            parse_warnings=["query 为空"],
        )

    if use_llm:
        try:
            result = _parse_intent_with_llm(query, profile=profile, base_url=base_url, model=model, timeout=timeout)
            # LLM 模式下，约束由 LLM 直接生成，不再追加规则引擎结果
            return result
        except Exception as exc:
            logger.warning("LLM intent parsing failed, falling back to rules: %s", exc)
            result = _parse_intent_with_rules(query)
            result.parse_warnings.append(f"LLM 解析失败，已回退到规则引擎: {exc}")
    else:
        result = _parse_intent_with_rules(query)

    hard = _extract_hard_constraints(query)
    soft = _extract_soft_constraints(query, result.interest_tags, result.style_tags)
    # 过滤掉与硬约束冲突的软约束（如"不想太累"中的"太累"不应被当作偏好）
    hard_values = {c.value for c in hard}
    soft = [c for c in soft if c.value not in hard_values]
    result.hard_constraints = hard
    result.soft_constraints = soft

    return result


def to_agent_intent(parsed: IntentParseOutput) -> dict[str, Any]:
    return {
        "request_text": parsed.request_text,
        "date_scope": parsed.date_scope,
        "explicit_campuses": tuple(parsed.explicit_campuses),
        "max_items": parsed.max_items,
    }


def to_agent_intent_extended(parsed: IntentParseOutput) -> dict[str, Any]:
    return {
        **to_agent_intent(parsed),
        "time_preference": parsed.time_preference.model_dump(),
        "interest_tags": parsed.interest_tags,
        "style_tags": parsed.style_tags,
        "hard_constraints": [h.model_dump() for h in parsed.hard_constraints],
        "soft_constraints": [s.model_dump() for s in parsed.soft_constraints],
    }


def _parse_intent_with_rules(query: str) -> IntentParseOutput:
    warnings: list[str] = []

    date_scope = _extract_date_scope(query)
    time_pref = _extract_time_preference(query)
    interest_tags = _extract_interest_tags(query)
    style_tags = _extract_style_tags(query)
    explicit_campuses = _extract_campuses(query)
    max_items = _extract_max_items(query)

    return IntentParseOutput(
        request_text=query,
        date_scope=date_scope,
        explicit_campuses=explicit_campuses,
        max_items=max_items,
        time_preference=time_pref,
        interest_tags=interest_tags,
        style_tags=style_tags,
        parsed_successfully=True,
        parse_warnings=warnings,
    )


def _parse_intent_with_llm(
    query: str,
    *,
    profile: Optional[dict[str, Any]] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
) -> IntentParseOutput:
    import requests

    api_key = os.getenv("MAAS_API_KEY")
    if not api_key:
        raise RuntimeError("MAAS_API_KEY is required for LLM intent parsing")

    resolved_model = model or os.getenv("MAAS_MODEL") or DEFAULT_MODEL
    resolved_base_url = (base_url or os.getenv("MAAS_BASE_URL") or DEFAULT_OPENAI_BASE_URL).rstrip("/")
    url = f"{resolved_base_url}/chat/completions"
    timeout_value = timeout or float(os.getenv("MAAS_TIMEOUT", "30"))

    system_prompt = _build_intent_system_prompt()
    user_content = json.dumps({"query": query}, ensure_ascii=False)

    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout_value,
            )
            if not response.ok:
                detail = response.text[:500].replace(api_key, "[REDACTED]")
                if attempt < MAX_RETRIES:
                    time.sleep(1.0)
                    continue
                raise RuntimeError(f"MaaS HTTP {response.status_code}: {detail}")

            raw = response.json()
            parsed = _extract_intent_from_response(raw)
            return _validate_and_build(parsed, query)

        except (ValueError, json.JSONDecodeError, KeyError) as exc:
            if attempt < MAX_RETRIES:
                time.sleep(1.0)
                continue
            raise exc

    raise RuntimeError("LLM intent parsing failed after all retries")


def _extract_date_scope(query: str) -> str:
    for scope, keywords in DATE_SCOPE_KEYWORDS.items():
        if any(kw in query for kw in keywords):
            return scope
    return "today"


def _extract_time_preference(query: str) -> TimePreference:
    return TimePreference(
        morning=any(kw in query for kw in TIME_KEYWORDS["morning"]),
        afternoon=any(kw in query for kw in TIME_KEYWORDS["afternoon"]),
        evening=any(kw in query for kw in TIME_KEYWORDS["evening"]),
        weekend=any(kw in query for kw in TIME_KEYWORDS["weekend"]),
    )


def _extract_interest_tags(query: str) -> list[str]:
    matched: list[str] = []
    folded = query.casefold()
    for term in KNOWN_INTEREST_TERMS:
        if term.casefold() in folded and term not in matched:
            matched.append(term)
    return matched


def _extract_style_tags(query: str) -> list[str]:
    matched: list[str] = []
    for style, synonyms in STYLE_TERMS.items():
        if any(syn in query for syn in synonyms) and style not in matched:
            matched.append(style)
    return matched


def _extract_campuses(query: str) -> list[str]:
    matched: list[str] = []
    for campus, aliases in CAMPUS_KEYWORDS.items():
        if any(alias in query for alias in aliases) and campus not in matched:
            matched.append(campus)
    return matched


def _extract_max_items(query: str) -> int:
    match = re.search(r"(\d+)\s*个", query)
    if match:
        n = int(match.group(1))
        return min(max(n, 1), 10)
    return 4


def _extract_hard_constraints(query: str) -> list[HardConstraint]:
    constraints: list[HardConstraint] = []
    for pattern, operator in EXCLUSION_PATTERNS:
        for match in pattern.finditer(query):
            value = match.group(1).strip()
            # 处理"换一个/换点"等切换语义：捕获值为空时用默认标记
            if not value:
                matched_text = match.group(0).strip()
                if matched_text and any(kw in matched_text for kw in ["换一个", "换点", "换个", "换点别的"]):
                    value = "_switch_request"
            if not value or len(value) > 15:
                continue
            if operator == "eq":
                if value in ["邯郸", "江湾", "枫林", "张江"]:
                    continue
            constraints.append(HardConstraint(
                field="excluded_keywords",
                operator=operator,
                value=value,
            ))
    return constraints


def _extract_soft_constraints(
    query: str,
    interest_tags: list[str],
    style_tags: list[str],
) -> list[SoftConstraint]:
    constraints: list[SoftConstraint] = []

    for pattern, weight in PREFERENCE_PATTERNS:
        for match in pattern.finditer(query):
            value = match.group(1).strip()
            if not value or len(value) > 15:
                continue
            constraints.append(SoftConstraint(
                field="interest_tags",
                weight=weight,
                value=value,
            ))

    seen = set()
    deduped: list[SoftConstraint] = []
    for c in constraints:
        key = f"{c.field}:{c.value}"
        if key not in seen:
            seen.add(key)
            deduped.append(c)

    return deduped


def _build_intent_system_prompt() -> str:
    return """你是复旦大学校园日程助手的意图解析器。从用户 query 中提取结构化意图，**包括显式表达和隐式偏好**。

## 输出 JSON 格式
{
  "date_scope": "today",
  "explicit_campuses": ["江湾"],
  "max_items": 4,
  "time_preference": {"morning": false, "afternoon": true, "evening": false, "weekend": false},
  "interest_tags": ["天文"],
  "style_tags": ["轻松"],
  "hard_constraints": [
    {"field": "excluded_keywords", "operator": "contains", "value": "讲座"}
  ],
  "soft_constraints": [
    {"field": "interest_tags", "weight": 1.5, "value": "天文"},
    {"field": "style_tags", "weight": 0.5, "value": "体育"}
  ]
}

## 基础字段规则
1. date_scope: today / tomorrow / this_week，根据"今天/明天/这周/周末"判断，默认 today
2. explicit_campuses: 仅提取用户明确说出的校区（邯郸/江湾/枫林/张江），没提到就是 []
3. max_items: 用户说"2个/3个"就设对应值，没说就默认 4
4. time_preference: 用户提到具体时段（上午/下午/晚上/周末）就设 true，没提到全 false
5. interest_tags: 从 query 提取用户感兴趣的关键词（天文/AI/戏剧/讲座/工作坊/展览/体育/音乐/社交/职业/创业等），提取不到就是 []
6. style_tags: 从 query 提取风格偏好（轻松/互动/正式/实践/安静/热闹），提取不到就是 []

## hard_constraints 规则（硬过滤）
硬约束是用户**明确不想看到的**内容，匹配的活动应被直接排除。
- 用户说"不要XX"、"别XX"、"不想XX"、"避免XX" → field="excluded_keywords", operator="contains"
- 用户说"只去XX校区"、"必须在XX" → field="campus", operator="eq"
- 用户说"换一个"、"换点别的" → field="excluded_keywords", value="_switch_request"（表示要换方向）
- 示例: "不要创业路演" → {"field": "excluded_keywords", "operator": "contains", "value": "创业路演"}
- 示例: "不想看太商业的" → {"field": "excluded_keywords", "operator": "contains", "value": "太商业"}

## soft_constraints 规则（软偏好/排序影响）
软偏好影响排序但不直接过滤。按用户表达的强烈程度设置 weight：
- weight 1.5: 用户说"特别喜欢"、"更喜欢"、"更偏"、"超爱"、"尤其喜欢"
- weight 1.2: 用户说"喜欢"、"想"、"最好"、"尽量"
- weight 0.5: 用户说"不太喜欢"、"不太想"、"一般"、"无所谓"
- 示例: "更喜欢 AI 展览" → {"field": "interest_tags", "weight": 1.5, "value": "AI展览"}

## 隐式意图推断
当用户表达模糊时，合理推断其意图并写入对应字段：
- "最近有点无聊" → interest_tags: ["社交", "演出"]，style_tags: ["轻松"]
- "不想太累但又想学点东西" → style_tags: ["轻松"]，interest_tags: ["学术", "讲座"]，hard_constraints: [排除需要大量体力的活动]
- "想做点不一样的" → hard_constraints: [{"field": "excluded_keywords", "value": "_switch_request"}]
- "随便看看" → 所有提取字段可留空

注意：只推断合理的、上下文支持的意图。不确定时宁可留空。
只返回 JSON，不要输出任何额外文字。"""


def _extract_intent_from_response(raw_response: dict[str, Any]) -> dict[str, Any]:
    choices = raw_response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("MaaS response missing choices")
    content = choices[0].get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("MaaS response missing content")
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    return json.loads(stripped)


def _validate_and_build(parsed: dict[str, Any], query: str) -> IntentParseOutput:
    time_pref = parsed.get("time_preference", {})
    hard_raw = parsed.get("hard_constraints", [])
    soft_raw = parsed.get("soft_constraints", [])

    hard_constraints = _parse_hard_constraints_from_llm(hard_raw)
    soft_constraints = _parse_soft_constraints_from_llm(soft_raw)

    return IntentParseOutput(
        request_text=query,
        date_scope=parsed.get("date_scope", "today"),
        explicit_campuses=parsed.get("explicit_campuses", []),
        max_items=parsed.get("max_items", 4),
        time_preference=TimePreference(
            morning=time_pref.get("morning", False),
            afternoon=time_pref.get("afternoon", False),
            evening=time_pref.get("evening", False),
            weekend=time_pref.get("weekend", False),
        ),
        interest_tags=parsed.get("interest_tags", []),
        style_tags=parsed.get("style_tags", []),
        hard_constraints=hard_constraints,
        soft_constraints=soft_constraints,
        parsed_successfully=True,
        parse_warnings=[],
    )


def _parse_hard_constraints_from_llm(raw: Any) -> list[HardConstraint]:
    """Parse hard_constraints from LLM output, with validation."""
    if not isinstance(raw, list):
        return []
    constraints: list[HardConstraint] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field", "")).strip()
        operator = str(item.get("operator", "contains")).strip()
        value = str(item.get("value", "")).strip()
        if not field or not value or len(value) > 50:
            continue
        constraints.append(HardConstraint(
            field=field,
            operator=operator if operator in ("eq", "ne", "contains") else "contains",
            value=value,
        ))
    return constraints


def _parse_soft_constraints_from_llm(raw: Any) -> list[SoftConstraint]:
    """Parse soft_constraints from LLM output, with validation."""
    if not isinstance(raw, list):
        return []
    constraints: list[SoftConstraint] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field", "")).strip()
        try:
            weight = float(item.get("weight", 1.0))
        except (TypeError, ValueError):
            weight = 1.0
        weight = max(0.0, min(2.0, weight))
        value = str(item.get("value", "")).strip()
        if not field or not value or len(value) > 50:
            continue
        constraints.append(SoftConstraint(
            field=field,
            weight=weight,
            value=value,
        ))
    return constraints
