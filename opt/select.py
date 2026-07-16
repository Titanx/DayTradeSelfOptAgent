"""select.py — 从候选编辑池中挑选 Top-K 最佳编辑

SkillOpt Step 2b: 对 aggregate 后的编辑进行多维评分，只保留得分最高的 k 条，
防止 skill 文档膨胀、避免低质量编辑污染。

评分维度:
  1. error_backing (0-40分): 编辑背后的错误量级（MISS/STEP 数量）
  2. specificity (0-25分): 规则的具体程度（是否指名板块/股票/条件）
  3. action_priority (0-20分): replace > add > delete
  4. file_priority (0-15分): research_manager > portfolio_manager > trader > others

默认 top_k = 3

输入: opt/output/edits_aggregated.json (或 edits.json)
输出: opt/output/edits_selected.json
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List

PROJECT_DIR = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_DIR / "opt" / "output"
INPUT_DIR = PROJECT_DIR / "opt" / "input"

FILE_PRIORITY = {
    "research_manager": 15,
    "portfolio_manager": 15,
    "trader": 10,
    "bull_researcher": 8,
    "bear_researcher": 8,
    "aggressive_risk": 6,
    "conservative_risk": 6,
    "neutral_risk": 6,
}

SECTOR_KEYWORDS = {
    "Solar": ["光伏", "Solar", "通威", "隆基", "阳光电源", "天合", "迈为",
              "Tongwei", "LONGi", "Sungrow", "Trina", "Maxwell"],
    "Wind": ["风电", "Wind", "金风", "明阳", "东方电缆", "新强联", "龙源",
             "Goldwind", "MingYang", "OrientCable", "Xinqianglian"],
    "AI": ["AI", "科大讯飞", "寒武纪", "浪潮", "中际旭创", "同花顺",
           "iFlytek", "Cambricon", "Inspur", "Zhongji", "Hithink", "Hithink"],
    "Energy": ["储能", "Energy", "宁德", "亿纬锂能", "国轩", "赣锋", "上海电气",
               "CATL", "EVE", "Guoxuan", "Ganfeng", "SEC"],
    "Vision": ["视觉", "Vision", "海康", "大华", "德赛", "中科创达", "韦尔",
               "Hikvision", "Dahua", "DesaySV", "ThunderSoft", "WillSemi"],
}


def _load_rollout():
    """加载回测数据用于错误量级评分。"""
    rollout_path = INPUT_DIR / "rollout.json"
    if rollout_path.exists():
        return json.loads(rollout_path.read_text(encoding="utf-8"))
    return None


def _score_error_backing(edit: dict, rollout: dict) -> float:
    """评估编辑背后的错误严重程度 (0-40)。"""
    score = 0
    text = (edit.get("new", "") + edit.get("old", "")).lower()

    summary = rollout.get("group_summary", {})
    by_sector = summary.get("by_sector", {})

    for sector, kw_list in SECTOR_KEYWORDS.items():
        if any(kw in text for kw in kw_list):
            sector_data = by_sector.get(sector, {})
            miss = sector_data.get("miss", 0)
            step = sector_data.get("step", 0)
            score = max(score, min(40, (miss * 15) + (step * 8)))
            break

    if score == 0:
        overall = summary.get("overall", {})
        score = min(20, overall.get("miss", 0) * 5 + overall.get("step", 0) * 3)

    return score


def _score_specificity(edit: dict) -> float:
    """评估规则的具体程度 (0-25)。"""
    score = 0
    text = edit.get("new", "") or edit.get("old", "")

    # 检测 A股代码（6位连续数字）— 比单纯"含数字"更精确
    if re.search(r'(?<!\d)\d{6}(?!\d)', text):
        score += 8
    # 检测具体数值条件（百分比/价格，如 "10%"、"50元"、"0.5"）
    elif re.search(r'\d+(\.\d+)?\s*[%％]', text) or re.search(r'\d+(\.\d+)?\s*[元万]', text):
        score += 5

    conditions = ["如果", "若", "当", "连续", "调整后", "突破", "反弹", "资金"]
    condition_count = sum(1 for c in conditions if c in text)
    score += min(9, condition_count * 3)

    if "%" in text or "％" in text:
        score += 5

    return min(25, score)


def _score_action_priority(edit: dict) -> float:
    """按操作类型评分 (0-20)。"""
    action = edit.get("action", "add")
    return {"replace": 20, "add": 12, "delete": 5}.get(action, 8)


def _score_file_priority(edit: dict) -> float:
    """按目标 skill 文件评分 (0-15)。"""
    file_name = edit.get("file", "")
    return FILE_PRIORITY.get(file_name, 5)


def score_edit(edit: dict, rollout: dict) -> float:
    """对单条编辑进行综合评分。"""
    scores = {
        "error_backing": _score_error_backing(edit, rollout),
        "specificity": _score_specificity(edit),
        "action_priority": _score_action_priority(edit),
        "file_priority": _score_file_priority(edit),
    }
    total = sum(scores.values())
    scores["total"] = total
    return scores


def select(edits_data: dict, top_k: int = 3, rollout_data: dict = None) -> dict:
    """从编辑提案中选出 Top-K。

    Args:
        edits_data: aggregate 后的编辑数据 {"edits": [...], ...}
        top_k: 保留数量 (默认 3)
        rollout_data: 回测数据（用于评分），默认自动加载

    Returns:
        筛选后的 edits_data
    """
    edits = edits_data.get("edits", [])
    if len(edits) <= top_k:
        result = dict(edits_data)
        result["select"] = {
            "total": len(edits),
            "selected": len(edits),
            "threshold": None,
            "scores": [],
            "timestamp": datetime.now().isoformat(),
        }
        output_path = OUTPUT_DIR / "edits_selected.json"
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Select: {} edits ≤ top-k({}), all passed through".format(len(edits), top_k))
        return result

    if rollout_data is None:
        rollout_data = _load_rollout() or {}

    scored = []
    for e in edits:
        scores = score_edit(e, rollout_data)
        scored.append({"edit": e, "scores": scores})

    scored.sort(key=lambda x: x["scores"]["total"], reverse=True)
    selected = scored[:top_k]
    rejected = scored[top_k:]

    threshold_score = selected[-1]["scores"]["total"] if selected else 0

    selected_edits = [s["edit"] for s in selected]

    result = {
        "analysis": edits_data.get("analysis", ""),
        "edits": selected_edits,
        "aggregate": edits_data.get("aggregate", {}),
        "select": {
            "total": len(edits),
            "selected": len(selected_edits),
            "rejected": len(rejected),
            "threshold": threshold_score,
            "scores": [
                {
                    "file": s["edit"].get("file", ""),
                    "section": s["edit"].get("section", ""),
                    "action": s["edit"].get("action", ""),
                    "scores": s["scores"],
                }
                for s in scored
            ],
            "timestamp": datetime.now().isoformat(),
        },
        "meta": edits_data.get("meta", {}),
    }

    output_path = OUTPUT_DIR / "edits_selected.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Select: {} edits → {} selected (top-k={})".format(len(edits), len(selected_edits), top_k))
    print("Score ranking:")
    for i, s in enumerate(scored):
        marker = "✔" if i < top_k else "✘"
        sc = s["scores"]
        print("  {} [{:2.0f}] {} @ {} ({}) err={:.0f} spec={:.0f} act={:.0f} file={:.0f}".format(
            marker, sc["total"],
            s["edit"].get("file", ""), s["edit"].get("section", ""),
            s["edit"].get("action", ""),
            sc["error_backing"], sc["specificity"],
            sc["action_priority"], sc["file_priority"]
        ))
    print("Saved to: {}".format(output_path))

    return result


if __name__ == "__main__":
    for path in [OUTPUT_DIR / "edits_aggregated.json", OUTPUT_DIR / "edits.json"]:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            result = select(data, top_k=3)
            break
    else:
        print("No edits found.")
