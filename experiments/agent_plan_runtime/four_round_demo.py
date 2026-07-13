"""
连续四轮接线样例 — 可在服务器复现（无网络依赖，全部走规则回退）。

展示 LLM 模块契约的完整数据流：
  第 1 轮：完成推荐并 like/dislike。
  第 2 轮：细粒度 Memory 立即影响排序，再次反馈。
  第 3 轮：细粒度 Memory 继续影响；结束后静默 reflection。
  第 4 轮：query rewrite 读取 memory_summary，完成搜索、排序和 composer。

样例输出包含：
  - 前三轮 request_text / recommended_event_ids / liked_event_ids / disliked_event_ids
  - 第三轮后生成的 memory_summary / source_refs / status
  - 第四轮 original_query / enriched_query / memory_used
  - composer 前后的 event_id 顺序（必须一致）

运行：python experiments/agent_plan_runtime/four_round_demo.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from runtime import plan_day  # noqa: E402
from query_rewrite import rewrite_query  # noqa: E402
from answer_composer import compose_answer, validate_composer_preserves_ranking  # noqa: E402
from memory_reflection import reflect_on_memory  # noqa: E402


# ============================================================
# 固定 mock 数据（自包含，保证可复现）
# ============================================================

# 固定 now：2026-07-13 08:00，所有活动均在「今天」窗口内
NOW = datetime.fromisoformat("2026-07-13T08:00:00+08:00")

PROFILE = {
    "interest_tags": ["天文", "AI"],
    "preferred_campuses": ["邯郸"],
    "available_time": "evening",
}

# 6 个活动，时间错开避免冲突；标签多样以便观察 memory 影响
EVENTS = [
    {
        "event_id": "evt_astro_2",
        "title": "望远镜实操工作坊",
        "summary": "天文协会望远镜实操工作坊，动手学习望远镜调试与观测。",
        "start_time": "2026-07-13T10:00:00+08:00",
        "end_time": "2026-07-13T11:30:00+08:00",
        "location": "光草东北角",
        "campus": "邯郸",
        "organizer": "复旦天协",
        "tags": ["天文", "望远镜", "工作坊", "实践"],
        "evidence_text": "天文协会望远镜实操工作坊，时间：2026.7.13 10:00~11:30，地点：光草东北角",
    },
    {
        "event_id": "evt_photo_1",
        "title": "摄影作品分享会",
        "summary": "摄影社作品分享与交流，轻松互动。",
        "start_time": "2026-07-13T12:00:00+08:00",
        "end_time": "2026-07-13T13:00:00+08:00",
        "location": "青书馆",
        "campus": "邯郸",
        "organizer": "摄影社",
        "tags": ["摄影", "分享", "轻松"],
        "evidence_text": "摄影社作品分享会，时间：2026.7.13 12:00~13:00，地点：青书馆",
    },
    {
        "event_id": "evt_business_1",
        "title": "创新创业路演",
        "summary": "创业团队路演与商业对接。",
        "start_time": "2026-07-13T13:30:00+08:00",
        "end_time": "2026-07-13T15:00:00+08:00",
        "location": "光华楼",
        "campus": "邯郸",
        "organizer": "创业中心",
        "tags": ["创业", "路演", "商业"],
        "evidence_text": "创业团队路演，时间：2026.7.13 13:30~15:00，地点：光华楼",
    },
    {
        "event_id": "evt_ai_1",
        "title": "AI前沿学术讲座",
        "summary": "AI 前沿学术讲座，偏理论。",
        "start_time": "2026-07-13T15:30:00+08:00",
        "end_time": "2026-07-13T17:00:00+08:00",
        "location": "江湾校区教室",
        "campus": "江湾",
        "organizer": "计算机学院",
        "tags": ["AI", "讲座", "学术"],
        "evidence_text": "AI前沿学术讲座，时间：2026.7.13 15:30~17:00，地点：江湾校区教室",
    },
    {
        "event_id": "evt_comedy_1",
        "title": "即兴喜剧互动夜",
        "summary": "即兴喜剧与观众互动，轻松愉快。",
        "start_time": "2026-07-13T18:00:00+08:00",
        "end_time": "2026-07-13T19:30:00+08:00",
        "location": "学生活动中心",
        "campus": "邯郸",
        "organizer": "喜剧社",
        "tags": ["喜剧", "互动", "轻松"],
        "evidence_text": "即兴喜剧互动夜，时间：2026.7.13 18:00~19:30，地点：学生活动中心",
    },
    {
        "event_id": "evt_astro_1",
        "title": "路边天文观测夜",
        "summary": "路边天文，讲星班讲解星空，望远镜观测深空。",
        "start_time": "2026-07-13T20:00:00+08:00",
        "end_time": "2026-07-13T21:30:00+08:00",
        "location": "光草东北角",
        "campus": "邯郸",
        "organizer": "复旦天协",
        "tags": ["天文", "观星", "实践"],
        "evidence_text": "路边天文观测夜，时间：2026.7.13 20:00~21:30，地点：光草东北角",
    },
]


def _ids(data: dict) -> list[str]:
    """从 plan_day 返回中提取 recommended_event_ids（保持顺序）。"""
    items = (data or {}).get("items") or []
    return [str(it.get("event_id", "")) for it in items if it.get("event_id")]


def _titles(data: dict) -> list[str]:
    """从 plan_day 返回中提取 recommended_event_titles（与 _ids 同序）。"""
    items = (data or {}).get("items") or []
    return [str(it.get("title", "")) for it in items if it.get("event_id")]


def _apply_fine_grained_memory(events: list[dict], memory: dict) -> list[dict]:
    """细粒度 Memory 影响排序：排除 disliked 活动并记录降权标记。

    模拟后端在 plan_day 前的候选过滤：
    - disliked_event_ids 中的活动从候选池移除（即时影响排序）
    - 保留 liked_event_ids 用于 reason_text 说明
    """
    disliked = set(memory.get("disliked_event_ids") or memory.get("excluded_from_feedback") or [])
    if not disliked:
        return list(events)
    return [e for e in events if e.get("event_id") not in disliked]


def _print_section(title: str) -> None:
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def _print_json(label: str, obj: dict) -> None:
    print(f"{label}:")
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main() -> None:
    # 累积的细粒度 memory（跨轮）
    cumulative_memory: dict = {"liked_event_ids": [], "disliked_event_ids": []}
    rounds_log: list[dict] = []

    # ============================================================
    # 第 1 轮：完成推荐并 like/dislike
    # ============================================================
    _print_section("第 1 轮：初次推荐 + 用户反馈")
    r1_request = "今天有什么活动"
    r1 = plan_day(
        events=EVENTS,
        profile=PROFILE,
        request_text=r1_request,
        date_scope="today",
        now=NOW,
        memory=None,
    )
    r1_ids = _ids(r1.get("data", {}))
    r1_titles = _titles(r1.get("data", {}))
    # 用户喜欢天文观测夜，不喜欢偏学术的 AI 讲座（均在推荐中）
    r1_liked = ["evt_astro_1"] if "evt_astro_1" in r1_ids else []
    r1_disliked = ["evt_ai_1"] if "evt_ai_1" in r1_ids else []
    rounds_log.append({
        "round": 1,
        "run_id": r1.get("data", {}).get("run_id"),
        "request_text": r1_request,
        "recommended_event_ids": r1_ids,
        "recommended_event_titles": r1_titles,
        "liked_event_ids": r1_liked,
        "disliked_event_ids": r1_disliked,
    })
    cumulative_memory["liked_event_ids"].extend(r1_liked)
    cumulative_memory["disliked_event_ids"].extend(r1_disliked)
    _print_json("第1轮", rounds_log[-1])

    # ============================================================
    # 第 2 轮：细粒度 Memory 立即影响排序，再次反馈
    # ============================================================
    _print_section("第 2 轮：细粒度 Memory 影响排序 + 再次反馈")
    r2_request = "今天还有什么可以参加"
    r2_events = _apply_fine_grained_memory(EVENTS, cumulative_memory)
    r2 = plan_day(
        events=r2_events,
        profile=PROFILE,
        request_text=r2_request,
        date_scope="today",
        now=NOW,
        memory={**cumulative_memory, "excluded_from_feedback": cumulative_memory["disliked_event_ids"]},
    )
    r2_ids = _ids(r2.get("data", {}))
    r2_titles = _titles(r2.get("data", {}))
    # 验证第1轮 disliked（evt_ai_1）已被细粒度 memory 排除
    assert "evt_ai_1" not in r2_ids, "第1轮 disliked 活动应被细粒度 memory 排除"
    # 用户喜欢望远镜工作坊（天文），不喜欢摄影分享会
    r2_liked = ["evt_astro_2"] if "evt_astro_2" in r2_ids else []
    r2_disliked = ["evt_photo_1"] if "evt_photo_1" in r2_ids else []
    rounds_log.append({
        "round": 2,
        "run_id": r2.get("data", {}).get("run_id"),
        "request_text": r2_request,
        "recommended_event_ids": r2_ids,
        "recommended_event_titles": r2_titles,
        "liked_event_ids": r2_liked,
        "disliked_event_ids": r2_disliked,
    })
    cumulative_memory["liked_event_ids"].extend(r2_liked)
    cumulative_memory["disliked_event_ids"].extend(r2_disliked)
    _print_json("第2轮", rounds_log[-1])

    # ============================================================
    # 第 3 轮：细粒度 Memory 继续影响；结束后静默 reflection
    # ============================================================
    _print_section("第 3 轮：细粒度 Memory 继续影响 + 静默 reflection")
    r3_request = "再帮我看看今天的安排"
    r3_events = _apply_fine_grained_memory(EVENTS, cumulative_memory)
    r3 = plan_day(
        events=r3_events,
        profile=PROFILE,
        request_text=r3_request,
        date_scope="today",
        now=NOW,
        memory={**cumulative_memory, "excluded_from_feedback": cumulative_memory["disliked_event_ids"]},
    )
    r3_ids = _ids(r3.get("data", {}))
    r3_titles = _titles(r3.get("data", {}))
    # 验证累积 disliked（evt_ai_1, evt_photo_1）均被排除
    assert "evt_ai_1" not in r3_ids and "evt_photo_1" not in r3_ids, "累积 disliked 应被排除"
    # 用户再次喜欢天文观测夜（持续天文偏好）
    r3_liked = ["evt_astro_1"] if "evt_astro_1" in r3_ids else []
    r3_disliked: list[str] = []
    rounds_log.append({
        "round": 3,
        "run_id": r3.get("data", {}).get("run_id"),
        "request_text": r3_request,
        "recommended_event_ids": r3_ids,
        "recommended_event_titles": r3_titles,
        "liked_event_ids": r3_liked,
        "disliked_event_ids": r3_disliked,
    })
    cumulative_memory["liked_event_ids"].extend(r3_liked)
    _print_json("第3轮", rounds_log[-1])

    # 静默 reflection：基于最近 3 轮生成 memory_summary
    print("\n--- 静默 memory reflection ---")
    reflection = reflect_on_memory(
        {"rounds": rounds_log, "existing_memory": None},
        api_key="",  # 规则回退，可复现
    )
    _print_json("reflection 结果", {
        "memory_summary": reflection["memory_summary"],
        "source_refs": reflection["source_refs"],
        "status": reflection["status"],
        "memory_strength": reflection["memory_strength"],
        "used_fallback": reflection["used_fallback"],
        "duration_ms": reflection["duration_ms"],
        "retry_count": reflection["retry_count"],
    })

    # ============================================================
    # 第 4 轮：query rewrite 读取 memory_summary，完成搜索、排序和 composer
    # ============================================================
    _print_section("第 4 轮：query rewrite 读取 memory_summary + composer")
    r4_request = "今天下午有什么活动"
    memory_for_rewrite = {
        "memory_summary": reflection["memory_summary"],
        "status": reflection["status"],
    }
    rewrite = rewrite_query(
        query=r4_request,
        memory_summary=memory_for_rewrite,
        profile=PROFILE,
        api_key="",  # 规则回退，可复现
    )
    _print_json("query_rewrite 结果", {
        "original_query": rewrite["original_query"],
        "enriched_query": rewrite["enriched_query"],
        "memory_used": rewrite["memory_used"],
        "positive_terms": rewrite["positive_terms"],
        "negative_terms": rewrite["negative_terms"],
        "top_k": rewrite["top_k"],
        "used_fallback": rewrite["used_fallback"],
        "model": rewrite["model"],
        "duration_ms": rewrite["duration_ms"],
        "retry_count": rewrite["retry_count"],
    })

    # 用 enriched query 完成 plan_day（仍排除累积 disliked）
    r4_events = _apply_fine_grained_memory(EVENTS, cumulative_memory)
    r4 = plan_day(
        events=r4_events,
        profile=PROFILE,
        request_text=rewrite["enriched_query"] or r4_request,
        date_scope="today",
        now=NOW,
        memory={**cumulative_memory, "excluded_from_feedback": cumulative_memory["disliked_event_ids"]},
    )
    r4_data = r4.get("data", {})
    r4_items = r4_data.get("items") or []
    r4_ids_before = [str(it.get("event_id", "")) for it in r4_items]

    # composer 解释已排序结果
    composer = compose_answer(
        ranked_items=r4_items,
        memory_summary=reflection["memory_summary"],
        request_text=r4_request,
        api_key="",  # 规则回退，可复现
    )
    r4_ids_after = [str(it.get("event_id", "")) for it in composer["recommended_items"]]

    _print_json("composer 结果", {
        "summary": composer["summary"],
        "event_id_order_before_composer": r4_ids_before,
        "event_id_order_after_composer": r4_ids_after,
        "tradeoffs": composer["tradeoffs"],
        "follow_up_question": composer["follow_up_question"],
        "used_fallback": composer["used_fallback"],
        "model": composer["model"],
        "duration_ms": composer["duration_ms"],
        "retry_count": composer["retry_count"],
    })

    # 校验 composer 保持排序
    ranking_preserved = validate_composer_preserves_ranking(r4_items, composer)
    print(f"\ncomposer 保持排序校验: {'PASS' if ranking_preserved else 'FAIL'}")
    assert ranking_preserved, "composer 必须保持 event_id 顺序"

    # ============================================================
    # 汇总
    # ============================================================
    _print_section("四轮接线汇总")
    print("前三轮：")
    for r in rounds_log:
        print(f"  第{r['round']}轮 request_text={r['request_text']!r}")
        print(f"         recommended_event_ids={r['recommended_event_ids']}")
        print(f"         liked_event_ids={r['liked_event_ids']}")
        print(f"         disliked_event_ids={r['disliked_event_ids']}")
    print("\n第三轮后 reflection：")
    print(f"  memory_summary={reflection['memory_summary']!r}")
    print(f"  source_refs={reflection['source_refs']}")
    print(f"  status={reflection['status']}")
    print("\n第四轮 query_rewrite：")
    print(f"  original_query={rewrite['original_query']!r}")
    print(f"  enriched_query={rewrite['enriched_query']!r}")
    print(f"  memory_used={rewrite['memory_used']}")
    print("\n第四轮 composer 前后 event_id 顺序：")
    print(f"  before={r4_ids_before}")
    print(f"  after ={r4_ids_after}")
    print(f"  一致={r4_ids_before == r4_ids_after}")

    print("\n样例完成。")


if __name__ == "__main__":
    main()
