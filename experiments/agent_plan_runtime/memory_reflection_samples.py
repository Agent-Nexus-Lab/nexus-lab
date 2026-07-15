"""
3 轮对话样例 — memory_reflection 测试数据

模拟用户连续 3 次使用日程规划，每次有不同反馈。
"""
from __future__ import annotations

# ============================================================
# 样例 1: 3 轮对话，有明确偏好模式
# ============================================================

SAMPLE_3_ROUNDS = {
    "session_id": "sess_demo_001",
    "rounds": [
        {
            "round": 1,
            "run_id": "run_a1b2c3d4",
            "request_text": "今天下午有什么天文活动",
            "recommended_event_titles": [
                "天文摄影讲座——深空摄影入门",
                "校园观星——夏季星空指南",
                "AI时代的天文摄影",
            ],
            "feedback": {
                "liked": ["校园观星——夏季星空指南"],
                "disliked": ["AI时代的天文摄影"],
            },
        },
        {
            "round": 2,
            "run_id": "run_e5f6g7h8",
            "request_text": "还想看天文相关的，但不要太学术的",
            "recommended_event_titles": [
                "天文协会观测夜——木星观测",
                "天文定向——星途再望",
                "量子计算与宇宙学前沿",
            ],
            "feedback": {
                "liked": ["天文协会观测夜——木星观测", "天文定向——星途再望"],
                "disliked": [],
            },
        },
        {
            "round": 3,
            "run_id": "run_i9j0k1l2",
            "request_text": "换点别的，想看展览或工作坊，最好在邯郸",
            "recommended_event_titles": [
                "毕业生艺术作品展",
                "Python数据分析入门工作坊",
                "创新创业项目路演",
            ],
            "feedback": {
                "liked": ["Python数据分析入门工作坊"],
                "disliked": ["创新创业项目路演"],
            },
        },
    ],
    "existing_memory": None,
}

# 预期输出（LLM模式）
EXPECTED_REFLECTION_LLM = {
    "memory_summary": "用户对天文观测类活动有持续偏好，连续两轮选择了观星和观测活动。不喜欢过于学术或商业化的活动（如AI天文摄影、创业路演）。第三轮开始探索实践类活动（工作坊），对邯郸校区有地理位置偏好。偏好轻松、互动、实操型的活动形式。",
    "source_refs": ["run_a1b2c3d4", "run_e5f6g7h8", "run_i9j0k1l2"],
    "expires_after_turns": 6,
    "cleanup_reason": None,
    "error": None,
    "used_fallback": False,
    "prompt_version": "2026-07-08-v1",
}

# 预期输出（规则模式，无LLM时的fallback）
EXPECTED_REFLECTION_RULE = {
    "memory_summary": "用户对「校园观星——夏季星空指南、天文协会观测夜——木星观测、Python数据分析入门工作坊」等活动感兴趣；不喜欢「AI时代的天文摄影、创新创业项目路演」类活动。",
    "source_refs": ["run_a1b2c3d4", "run_e5f6g7h8", "run_i9j0k1l2"],
    "expires_after_turns": 6,
    "cleanup_reason": None,
    "error": None,
    "used_fallback": True,
    "prompt_version": "2026-07-08-v1",
}

# ============================================================
# 样例 2: 3 轮对话，无反馈（用户只是浏览）
# ============================================================

SAMPLE_3_ROUNDS_NO_FEEDBACK = {
    "session_id": "sess_demo_002",
    "rounds": [
        {
            "round": 1,
            "run_id": "run_x1",
            "request_text": "最近有什么好玩的",
            "recommended_event_titles": ["校园音乐会", "毕业季草坪音乐节"],
            "feedback": {"liked": [], "disliked": []},
        },
        {
            "round": 2,
            "run_id": "run_x2",
            "request_text": "上午有什么活动",
            "recommended_event_titles": ["学术讲座", "游泳比赛"],
            "feedback": {"liked": [], "disliked": []},
        },
        {
            "round": 3,
            "run_id": "run_x3",
            "request_text": "算了随便看看",
            "recommended_event_titles": ["图书馆展览", "社团招新"],
            "feedback": {"liked": [], "disliked": []},
        },
    ],
    "existing_memory": None,
}

# 预期输出（无反馈）
EXPECTED_NO_FEEDBACK = {
    "memory_summary": "用户尚未表达明确偏好。",
    "source_refs": ["run_x1", "run_x2", "run_x3"],
    "expires_after_turns": 6,
    "cleanup_reason": None,
    "error": None,
    "used_fallback": True,
    "prompt_version": "2026-07-08-v1",
}

# ============================================================
# 生命周期测试
# ============================================================

SAMPLE_MEMORY_FOR_DECAY = {
    "memory_summary": "测试记忆",
    "source_refs": ["run_1"],
    "expires_after_turns": 6,
    "cleanup_reason": None,
    "prompt_version": "2026-07-08-v1",
}
