"""collector.py — 从回测数据收集优化信号

输入: backtest_multiday.py 的输出 + results/ 目录
输出: opt/input/rollout.json (结构化数据供 optimizer 消费)

核心流程:
1. 读取所有 results/{code}_{date}_analysis.cache.json → 提取预测 (rating, confidence)
2. 从腾讯行情API拉取次日实盘涨跌 → 计算 HIT/MISS/STEP/AVOID
3. 按 sector + error_type 分组，生成 group_summary
4. 输出 JSON 供 Optimizer LLM 分析
"""

import json
import urllib.request
import time
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))
RESULTS_DIR = PROJECT_DIR / "data" / "results"
OUTPUT_DIR = PROJECT_DIR / "opt" / "input"

from scripts.stock_universe import stocks_for_collector

STOCKS = stocks_for_collector()


def load_prediction(code, trade_date):
    candidates = [
        RESULTS_DIR / "{}_{}_analysis.cache.json".format(code, trade_date),
    ]
    candidates += sorted(
        RESULTS_DIR.glob("{}_{}_v*_analysis.cache.json".format(code, trade_date)),
        reverse=True,
    )
    for f in candidates:
        if f.exists():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                return {
                    "symbol": d.get("symbol", code),
                    "rating": d.get("rating", "?"),
                    "confidence": d.get("confidence", 0),
                    "summary": (d.get("summary") or d.get("investment_logic") or "")[:300],
                }
            except Exception:
                pass
    return None


def get_kline(sid):
    url = (
        "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        "?param={sid},day,,,5,qfq".format(sid=sid)
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read().decode("utf-8"))["data"][sid]["qfqday"]


def collect(date_list: List[str]) -> dict:
    """收集指定日期的回测信号。

    Args:
        date_list: 交易日列表, 如 ["2026-06-12", "2026-06-15"]

    Returns:
        {
            "date_range": "2026-06-12 ~ 2026-06-15",
            "skill_files": {...},
            "rollout_results": [...],
            "group_summary": {
                "by_sector": {...},
                "by_error_type": {...}
            }
        }
    """
    date_range = "{} ~ {}".format(date_list[0], date_list[-1])

    # 读取当前 skill 文件 (供 optimizer 参考)
    skills_dir = PROJECT_DIR / "skills"
    skill_files = {}
    for sf in skills_dir.glob("*.skill.md"):
        skill_files[sf.stem.replace(".skill", "")] = sf.read_text(encoding="utf-8")

    results = []
    stats = {"hit": 0, "avoid": 0, "miss": 0, "step": 0}
    by_sector = defaultdict(lambda: {"hit": 0, "avoid": 0, "miss": 0, "step": 0, "items": []})

    for trade_date in date_list:
        # 找到下一个交易日的收盘价
        for sid, name, sector in STOCKS:
            code = sid[2:]
            pred = load_prediction(code, trade_date)
            if not pred:
                continue

            try:
                klines = get_kline(sid)
                time.sleep(0.1)
            except Exception:
                continue

            # 策略：Day0(决策日)收盘分析 → Day1 开盘买入 → Day2 收盘卖出
            # 需要找到 Day1 开盘价（买入价）和 Day2 收盘价（卖出价）
            d1_open = None  # Day1 开盘价 = 买入价
            d2_close = None  # Day2 收盘价 = 卖出价
            next_day_count = 0
            for k in klines:
                if k[0] == trade_date:
                    # Day0 (决策日)，跳过
                    continue
                if k[0] > trade_date:
                    next_day_count += 1
                    if next_day_count == 1:
                        # Day1: 取开盘价作为买入价
                        d1_open = float(k[1])
                    elif next_day_count == 2:
                        # Day2: 取收盘价作为卖出价
                        d2_close = float(k[2])
                        break

            if d1_open is None or d2_close is None:
                # 数据不足（可能是决策日就是最后一个交易日），跳过
                continue

            # 实际收益率 = (Day2收盘价 - Day1开盘价) / Day1开盘价
            actual_return_pct = (d2_close / d1_open - 1) * 100
            should_buy = pred["rating"] in ("Buy", "Overweight")
            actually_up = actual_return_pct >= 1.0

            if should_buy and actually_up:
                verdict = "HIT"
            elif should_buy:
                verdict = "MISS"
            elif actually_up:
                verdict = "STEP"
            else:
                verdict = "AVOID"

            stats[verdict.lower()] += 1
            by_sector[sector][verdict.lower()] += 1

            entry = {
                "date": trade_date,
                "stock": code,
                "name": name,
                "sector": sector,
                "rating": pred["rating"],
                "confidence": pred["confidence"],
                "actual_chg": round(actual_return_pct, 2),
                "verdict": verdict,
                "summary": pred["summary"],
            }
            results.append(entry)
            by_sector[sector]["items"].append(entry)

    # 构建 group_summary
    group_summary = {
        "by_sector": {},
        "by_error_type": {
            "MISS": [r for r in results if r["verdict"] == "MISS"],
            "STEP": [r for r in results if r["verdict"] == "STEP"],
        },
        "overall": {
            "total": len(results),
            "accuracy": round((stats["hit"] + stats["avoid"]) / len(results) * 100, 1) if results else 0,
            "hit": stats["hit"],
            "avoid": stats["avoid"],
            "miss": stats["miss"],
            "step": stats["step"],
        },
    }

    for sector, s in by_sector.items():
        total_s = s["hit"] + s["avoid"] + s["miss"] + s["step"]
        group_summary["by_sector"][sector] = {
            "total": total_s,
            "accuracy": round((s["hit"] + s["avoid"]) / total_s * 100, 1) if total_s else 0,
            "hit": s["hit"],
            "avoid": s["avoid"],
            "miss": s["miss"],
            "step": s["step"],
            "items": s["items"],
        }

    return {
        "date_range": date_range,
        "collected_at": datetime.now().isoformat(),
        "skill_files": skill_files,
        "rollout_results": results,
        "group_summary": group_summary,
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 自动发现 results/ 中的所有日期 (支持版本化文件名)
    all_dates = set()
    for pattern in ["*_analysis.cache.json", "*_v*_analysis.cache.json"]:
        for f in RESULTS_DIR.glob(pattern):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                td = d.get("trade_date", "")
                if td:
                    all_dates.add(td)
            except Exception:
                pass

    sorted_dates = sorted(all_dates)
    if len(sorted_dates) < 1:
        print("No analysis data found in results/")
        return

    # 训练集: 最近 3 个日期 (或全部)
    train_dates = sorted_dates[-3:] if len(sorted_dates) >= 3 else sorted_dates
    print("Collecting for train dates: {}".format(train_dates))

    data = collect(train_dates)

    output_path = OUTPUT_DIR / "rollout.json"
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Collected {} results".format(len(data["rollout_results"])))
    print("  HIT: {}  AVOID: {}  MISS: {}  STEP: {}".format(
        data["group_summary"]["overall"]["hit"],
        data["group_summary"]["overall"]["avoid"],
        data["group_summary"]["overall"]["miss"],
        data["group_summary"]["overall"]["step"],
    ))
    print("  Accuracy: {}%".format(data["group_summary"]["overall"]["accuracy"]))
    print("Saved to: {}".format(output_path))


if __name__ == "__main__":
    main()
