# -*- coding: utf-8 -*-
"""一次性脚本：给 account_list.json 每个账号加 category 字段。
按 name+notes 关键词推断，值域：讲座/文艺/体育/比赛/就业/志愿服务/其他。
已存在 category 的不覆盖。"""
import json
from pathlib import Path

P = Path(__file__).resolve().parent / "account_list.json"

# 关键词→category，按优先级顺序匹配（先命中先归类）
RULES = [
    ("就业", ["就业", "职业", "招聘", "实习", "校友", "发展中心", "职发"]),
    ("志愿服务", ["志愿", "公益", "青志", "服务队", "服务队"]),
    ("比赛", ["竞赛", "比赛", "挑战杯", "创新创业", "创赛", "数模", "建模"]),
    ("体育", ["体育", "运动", "球", "跑", "健身", "武术", "棋", "登山", "定向",
              "羽", "乒乓", "网球", "篮球", "足球", "排球", "游泳", "瑜伽",
              "跆拳道", "骑行", "车协"]),
    ("讲座", ["讲座", "论坛", "报告会", "讲坛", "学术", "讲习", "读书", "沙龙"]),
    ("文艺", ["剧", "合唱", "艺术", "民乐", "乐团", "音乐", "舞蹈", "话剧", "戏剧",
              "书画", "摄影", "文学", "诗", "曲艺", "合奏", "漫画", "动漫", "影视",
              "书法", "美术", "设计", "展览", "乐队", "吉他", "钢琴", "戏曲", "魔术",
              "相声", "广播", "主持", "辩", "演讲"]),
]


def classify(name: str, notes: str) -> str:
    text = (name + " " + notes).lower()
    for cat, kws in RULES:
        for kw in kws:
            if kw in text:
                return cat
    return "其他"


def main() -> None:
    data = json.loads(P.read_text(encoding="utf-8"))
    accounts = data.get("accounts", [])
    breakdown: dict[str, int] = {}
    changed = 0
    for a in accounts:
        if a.get("category"):
            cat = a["category"]
        else:
            cat = classify(a.get("name", ""), a.get("notes", ""))
            a["category"] = cat
            changed += 1
        breakdown[cat] = breakdown.get(cat, 0) + 1
    P.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"updated {changed}/{len(accounts)} accounts")
    print("breakdown:", json.dumps(breakdown, ensure_ascii=False))


if __name__ == "__main__":
    main()
