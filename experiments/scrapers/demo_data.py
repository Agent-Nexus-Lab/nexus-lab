"""Demo data generation — 20 synthetic future events for dev/test/presentation.

Usage:
    python scrapers/demo_data.py --output demo_events.json
    python scrapers/demo_data.py --output ../agent-maas-cli/outputs/events.json

Events span all 5 campuses across 8 interest categories, with dates
automatically offset from `now` to fall within the next 14 days.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_core._runtime_compat import DEFAULT_TIMEZONE

_EXPERIMENTS_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = _EXPERIMENTS_ROOT / "agent-maas-cli" / "outputs" / "demo_events.json"

# 20 demo events covering all campuses and 8 interest categories
# Dates are expressed as (day_offset, hour, minute) relative to `now`
_DEMO_TEMPLATES: list[dict[str, Any]] = [
    # ── 邯郸 campus (8 events) ──
    {
        "title": "AI 大模型前沿讲座",
        "summary": "计算机学院主办，邀请业界专家分享大模型技术最新进展",
        "location": "邯郸校区 H3108",
        "campus": "邯郸",
        "organizer": "计算机科学技术学院",
        "tags": ["AI", "讲座", "大模型"],
        "evidence_text": "复旦大学计算机学院学术活动通知：AI大模型前沿讲座，2026年6月3日14:00",
        "offset_days": 1, "hour": 14, "minute": 0,
    },
    {
        "title": "天文摄影分享会",
        "summary": "复旦天协主办，知名天文摄影师分享深空摄影技巧",
        "location": "邯郸校区 H3206",
        "campus": "邯郸",
        "organizer": "复旦大学天文协会",
        "tags": ["天文", "摄影", "分享会"],
        "evidence_text": "复旦天协活动通知：天文摄影分享会，5月16日13:30，H3101",
        "offset_days": 2, "hour": 13, "minute": 30,
    },
    {
        "title": "创新创业工作坊：从0到1的产品设计",
        "summary": "实战导向的产品设计工作坊，适合对创业感兴趣的同学",
        "location": "邯郸校区 光华楼东辅楼103",
        "campus": "邯郸",
        "organizer": "创新创业学院",
        "tags": ["创业", "工作坊", "产品", "互动"],
        "evidence_text": "创新创业学院工作坊通知",
        "offset_days": 3, "hour": 15, "minute": 0,
    },
    {
        "title": "文图读书会：《人类简史》精读",
        "summary": "每两周一次的读书分享活动，本期聚焦《人类简史》",
        "location": "文科图书馆二楼研讨室",
        "campus": "邯郸",
        "organizer": "图书馆读者协会",
        "tags": ["图书馆", "社交", "轻松"],
        "evidence_text": "文图读书会第42期通知",
        "offset_days": 4, "hour": 19, "minute": 0,
    },
    {
        "title": "职业规划讲座：科技行业求职攻略",
        "summary": "邀请BAT资深HR分享科技行业求职技巧和职业规划",
        "location": "邯郸校区 叶耀珍楼202",
        "campus": "邯郸",
        "organizer": "学生职业发展中心",
        "tags": ["职业", "就业", "讲座"],
        "evidence_text": "学生职业发展中心讲座通知",
        "offset_days": 5, "hour": 18, "minute": 30,
    },
    {
        "title": "戏剧社年度大戏《雷雨》公演",
        "summary": "复旦剧社年度制作，经典话剧《雷雨》校园公演",
        "location": "邯郸校区 相辉堂",
        "campus": "邯郸",
        "organizer": "复旦剧社",
        "tags": ["戏剧", "演出", "社交"],
        "evidence_text": "复旦剧社2026年度公演通知",
        "offset_days": 6, "hour": 19, "minute": 0,
    },
    {
        "title": "人工智能与医疗健康交叉论坛",
        "summary": "探讨AI在医疗诊断、药物研发中的应用与挑战",
        "location": "邯郸校区 逸夫科技楼报告厅",
        "campus": "邯郸",
        "organizer": "类脑智能科学与技术研究院",
        "tags": ["AI", "学术", "讲座"],
        "evidence_text": "类脑智能研究院学术论坛通知",
        "offset_days": 7, "hour": 9, "minute": 0,
    },
    {
        "title": "星空观测夜：夏季大三角",
        "summary": "天文协会组织夏季星空观测活动，提供望远镜",
        "location": "邯郸校区 光华楼顶层",
        "campus": "邯郸",
        "organizer": "复旦大学天文协会",
        "tags": ["天文", "观星", "实践"],
        "evidence_text": "复旦天协观星活动通知，夏季大三角观测",
        "offset_days": 8, "hour": 20, "minute": 0,
    },
    # ── 江湾 campus (4 events) ──
    {
        "title": "江湾校区生涯规划工作坊",
        "summary": "面向法学院和先进材料实验室学生的职业规划",
        "location": "江湾校区 法学楼301",
        "campus": "江湾",
        "organizer": "法学院学生工作办公室",
        "tags": ["职业", "工作坊", "互动"],
        "evidence_text": "江湾校区生涯规划工作坊活动通知",
        "offset_days": 2, "hour": 14, "minute": 0,
    },
    {
        "title": "材料科学前沿讲座：二维材料的未来",
        "summary": "先进材料实验室学术讲座系列",
        "location": "江湾校区 先进材料楼报告厅",
        "campus": "江湾",
        "organizer": "先进材料实验室",
        "tags": ["学术", "讲座", "理论"],
        "evidence_text": "先进材料实验室学术讲座通知",
        "offset_days": 4, "hour": 10, "minute": 0,
    },
    {
        "title": "江湾图书馆学术写作指导",
        "summary": "图书馆主办的学术论文写作与文献管理培训",
        "location": "江湾校区 李兆基图书馆培训室",
        "campus": "江湾",
        "organizer": "复旦大学图书馆",
        "tags": ["图书馆", "课程", "学术"],
        "evidence_text": "复旦大学图书馆培训通知",
        "offset_days": 6, "hour": 15, "minute": 0,
    },
    {
        "title": "江湾游泳馆开放日活动",
        "summary": "游泳馆免费体验日，含教练指导和水上趣味活动",
        "location": "江湾校区 游泳馆",
        "campus": "江湾",
        "organizer": "体育教学部",
        "tags": ["体育", "游泳", "轻松"],
        "evidence_text": "江湾游泳馆开放日活动通知",
        "offset_days": 9, "hour": 13, "minute": 0,
    },
    # ── 枫林 campus (4 events) ──
    {
        "title": "公共卫生与预防医学前沿论坛",
        "summary": "聚焦传染病防控和公共卫生政策",
        "location": "枫林校区 明道楼二楼报告厅",
        "campus": "枫林",
        "organizer": "公共卫生学院",
        "tags": ["学术", "讲座", "论坛"],
        "evidence_text": "公共卫生学院学术论坛通知",
        "offset_days": 3, "hour": 14, "minute": 0,
    },
    {
        "title": "枫林校区健康跑活动",
        "summary": "校园健康跑，全程5公里，适合各水平跑者",
        "location": "枫林校区 田径场集合",
        "campus": "枫林",
        "organizer": "体育教学部",
        "tags": ["体育", "社交", "轻松"],
        "evidence_text": "枫林校区健康跑活动通知",
        "offset_days": 5, "hour": 7, "minute": 30,
    },
    {
        "title": "医学生科研经验分享会",
        "summary": "高年级医学生分享科研选题、实验设计和论文发表经验",
        "location": "枫林校区 第二教学楼210",
        "campus": "枫林",
        "organizer": "基础医学院学生会",
        "tags": ["分享会", "学术", "实践"],
        "evidence_text": "基础医学院科研分享会通知",
        "offset_days": 7, "hour": 18, "minute": 30,
    },
    {
        "title": "枫林医学人文读书会",
        "summary": "共读《当呼吸化为空气》，探讨医学人文关怀",
        "location": "枫林校区 图书馆研讨室A",
        "campus": "枫林",
        "organizer": "医学人文研究中心",
        "tags": ["图书馆", "社交", "轻松"],
        "evidence_text": "医学人文读书会第8期通知",
        "offset_days": 10, "hour": 19, "minute": 0,
    },
    # ── 张江 campus (2 events) ──
    {
        "title": "张江校区技术沙龙：分布式系统设计",
        "summary": "讨论分布式系统的一致性、容错和性能优化",
        "location": "张江校区 软件楼102",
        "campus": "张江",
        "organizer": "软件学院",
        "tags": ["AI", "技术", "沙龙", "互动"],
        "evidence_text": "软件学院技术沙龙通知",
        "offset_days": 3, "hour": 19, "minute": 0,
    },
    {
        "title": "张江校区企业参访：走进商汤科技",
        "summary": "组织学生参观商汤科技，了解AI产业应用",
        "location": "张江校区集合，统一乘车",
        "campus": "张江",
        "organizer": "计算机科学技术学院",
        "tags": ["参观", "AI", "职业"],
        "evidence_text": "企业参访活动通知：走进商汤科技",
        "offset_days": 8, "hour": 13, "minute": 0,
    },
    # ── 线上 (2 events) ──
    {
        "title": "线上腾讯会议：开源项目贡献指南",
        "summary": "介绍如何参与开源项目，从PR到成为maintainer",
        "location": "腾讯会议 123-456-789",
        "campus": "其他",
        "organizer": "开源社区",
        "tags": ["AI", "课程", "互动"],
        "evidence_text": "线上技术分享通知：开源项目贡献指南",
        "offset_days": 1, "hour": 20, "minute": 0,
    },
    {
        "title": "线上直播：科研论文写作与投稿技巧",
        "summary": "学术写作专家在线分享SCI论文写作技巧",
        "location": "Zoom 987-654-321",
        "campus": "其他",
        "organizer": "研究生会学术部",
        "tags": ["学术", "讲座", "课程"],
        "evidence_text": "研究生会学术部线上讲座通知",
        "offset_days": 5, "hour": 19, "minute": 0,
    },
]


def generate_demo_events(
    now: datetime | None = None,
    count: int = 20,
) -> list[dict[str, Any]]:
    """Generate demo events with dates relative to `now`.

    Args:
        now: Reference time. Defaults to real clock.
        count: Number of events to generate (max 20).

    Returns:
        List of event dicts in AGGREGATED_EVENT_FIELDS format.
    """
    if now is None:
        now = datetime.now(DEFAULT_TIMEZONE)

    templates = _DEMO_TEMPLATES[:count]
    events: list[dict[str, Any]] = []

    for i, tmpl in enumerate(templates):
        offset_days = tmpl["offset_days"]
        hour = tmpl["hour"]
        minute = tmpl["minute"]
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            days=offset_days, hours=hour, minutes=minute
        )
        # Ensure start has timezone
        if start.tzinfo is None:
            start = start.replace(tzinfo=DEFAULT_TIMEZONE)

        # Derive end_time (default 2 hours)
        end = start + timedelta(hours=2)

        event: dict[str, Any] = {
            "event_id": f"demo_{i + 1:03d}",
            "source_file": "demo_data.py",
            "source_name": "演示数据",
            "source_url": f"https://example.com/demo/{i + 1}",
            "title": tmpl["title"],
            "summary": tmpl["summary"],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "location": tmpl["location"],
            "campus": tmpl["campus"],
            "organizer": tmpl["organizer"],
            "tags": tmpl["tags"],
            "evidence_text": tmpl["evidence_text"],
        }
        events.append(event)

    return events


def write_demo_events(
    output_path: Path | None = None,
    events: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> Path:
    """Generate and write demo events to a JSON file."""
    output_path = output_path or DEFAULT_OUTPUT
    if events is None:
        events = generate_demo_events(now=now)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = {"events": events}
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output_path


# ── CLI ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate 20 demo events for dev/test."
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=f"Output path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Number of events to generate (max 20)",
    )
    args = parser.parse_args(argv)

    now = datetime.now(DEFAULT_TIMEZONE)
    events = generate_demo_events(now=now, count=args.count)
    output_path = write_demo_events(Path(args.output), events=events)

    print(f"Generated {len(events)} demo events -> {output_path}", file=sys.stderr)
    # Print summary
    campuses: dict[str, int] = {}
    for ev in events:
        c = ev.get("campus", "?")
        campuses[c] = campuses.get(c, 0) + 1
    for c, n in sorted(campuses.items()):
        print(f"  {c}: {n}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
