"""collector.py — 从回测数据收集优化信号

输入: backtest_multiday.py 的输出 + results/ 目录
输出: opt/input/rollout.json (结构化数据供 optimizer 消费)

核心流程:
1. 读取所有 results/{code}_{date}_analysis.cache.json → 提取预测 (rating, confidence)
2. 从腾讯行情API拉取 K 线 → 模拟一日游策略的止盈止损 → 计算 HIT/STOP/FLAT/MISS/STEP/AVOID
3. 按 sector + error_type 分组，生成 group_summary
4. 输出 JSON 供 Optimizer LLM 分析

策略对齐 (与 README + scripts/batch_backtest.py 一致, 两者均为两日策略):
  注: scripts/backtest_multiday.py 为已废弃的旧版单日策略，请勿参考
  Day0(决策日)收盘分析 → Day1 开盘买入 → Day2 止盈/止损/收盘平仓
  买价基准 = Day1 开盘价 (d1_open)，HIT/STEP 均以此为准，避免 Day1 跳空误报
    HIT   = 看多 + Day2 日内最高 ≥ d1_open+1%  → 止盈平仓
    STOP  = 看多 + Day2 日内最低 ≤ d1_open-3%  → 止损平仓
    FLAT  = 看多 + 未触发止盈/止损              → Day2 收盘强制平仓
    AVOID = 观望 + Day2 最高未达 d1_open+1%    → 正确回避
    STEP  = 观望 + Day2 最高 ≥ d1_open+1%      → 踏空 (基准与 HIT 一致)
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

# 策略参数 (与 README + batch_backtest.py 对齐)
TARGET_GAIN_PCT = 1.0   # 止盈线 +1%
STOP_LOSS_PCT = 3.0     # 止损线 -3%


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
    """拉取 K 线数据（30 天窗口，确保历史日期回测能取到正确 K 线，覆盖节假日）。

    返回 dict: {date_str: (open, close, high, low)}
    """
    url = (
        "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        "?param={sid},day,,,30,qfq".format(sid=sid)
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read().decode("utf-8"))["data"][sid]
    raw = data.get("qfqday") or data.get("day", [])
    # k 格式: [date, open, close, high, low, ...]
    return {k[0]: (float(k[1]), float(k[2]), float(k[3]), float(k[4])) for k in raw}


def _classify(verdict_rating: str, d1_open: float, d2_high: float,
              d2_low: float, d2_close: float) -> tuple:
    """按一日游策略分类，返回 (verdict, actual_return_pct)。

    actual_return_pct 是模拟止盈止损后的实际收益，非收盘价差。
    M1: 删除 d0_close 参数（H1 修复后 STEP 改用 d1_open，d0_close 不再使用）
    """
    is_bull = verdict_rating in ("Buy", "Overweight")
    hit_price = d1_open * (1 + TARGET_GAIN_PCT / 100.0)   # +1% 止盈
    stop_price = d1_open * (1 - STOP_LOSS_PCT / 100.0)    # -3% 止损

    if is_bull:
        if d2_high >= hit_price:
            # 止盈触发：实际收益 = +1%
            return "HIT", TARGET_GAIN_PCT
        elif d2_low <= stop_price:
            # 止损触发：实际收益 = -3%
            return "STOP", -STOP_LOSS_PCT
        else:
            # 未触发，收盘平仓
            flat_pct = (d2_close / d1_open - 1) * 100
            return "FLAT", round(flat_pct, 2)
    else:
        # 观望：用 Day1 开盘（如当时按策略买入的价格）→ Day2 最高 涨幅判断是否踏空
        # 基准与 HIT 一致，避免 Day1 跳空高/低开时 STEP 误报/漏报
        if d1_open <= 0:
            return "AVOID", 0.0
        step_trig = (d2_high / d1_open - 1) * 100 >= TARGET_GAIN_PCT
        if step_trig:
            return "STEP", round((d2_high / d1_open - 1) * 100, 2)
        else:
            return "AVOID", 0.0


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
    stats = {"hit": 0, "stop": 0, "flat": 0, "avoid": 0, "step": 0, "miss": 0}
    by_sector = defaultdict(lambda: {"hit": 0, "stop": 0, "flat": 0, "avoid": 0,
                                      "step": 0, "miss": 0, "items": []})

    for trade_date in date_list:
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

            # 校验关键日期存在（避免静默用错日期）
            if trade_date not in klines:
                continue

            # Day0(决策日) → Day1(买入日) → Day2(卖出日)
            sorted_dates = sorted(klines.keys())
            try:
                d0_idx = sorted_dates.index(trade_date)
            except ValueError:
                continue
            if d0_idx + 2 >= len(sorted_dates):
                # 数据不足，无法取 Day1/Day2
                continue
            d1_date = sorted_dates[d0_idx + 1]
            d2_date = sorted_dates[d0_idx + 2]

            d1_open = klines[d1_date][0]        # Day1 开盘 = 买入价
            d2_high = klines[d2_date][2]        # Day2 日内最高
            d2_low = klines[d2_date][3]         # Day2 日内最低
            d2_close = klines[d2_date][1]       # Day2 收盘

            verdict, actual_return_pct = _classify(
                pred["rating"], d1_open, d2_high, d2_low, d2_close
            )

            # MISS 兼容旧标签：看多但未 HIT 的（STOP/FLAT）在 optimizer 语境里都是"错误信号"
            # 保留 STOP/FLAT 细分类别，同时计入 miss 总数供 accuracy 计算
            if verdict in ("STOP", "FLAT"):
                stats["miss"] += 1
                by_sector[sector]["miss"] += 1
            stats[verdict.lower()] += 1
            by_sector[sector][verdict.lower()] += 1

            entry = {
                "date": trade_date,
                "stock": code,
                "name": name,
                "sector": sector,
                "rating": pred["rating"],
                "confidence": pred["confidence"],
                "actual_chg": actual_return_pct,
                "verdict": verdict,
                "d1_open": d1_open,
                "d2_high": d2_high,
                "d2_low": d2_low,
                "d2_close": d2_close,
                "summary": pred["summary"],
            }
            results.append(entry)
            by_sector[sector]["items"].append(entry)

    # 构建 group_summary
    # accuracy = (HIT + AVOID) / total —— 看多且止盈 + 观望且正确回避
    total_valid = len(results)
    correct = stats["hit"] + stats["avoid"]
    accuracy = round(correct / total_valid * 100, 1) if total_valid else 0

    group_summary = {
        "by_sector": {},
        "by_error_type": {
            "STOP": [r for r in results if r["verdict"] == "STOP"],
            "FLAT": [r for r in results if r["verdict"] == "FLAT"],
            "STEP": [r for r in results if r["verdict"] == "STEP"],
            "MISS": [r for r in results if r["verdict"] in ("STOP", "FLAT")],
        },
        "overall": {
            "total": total_valid,
            "accuracy": accuracy,
            "hit": stats["hit"],
            "stop": stats["stop"],
            "flat": stats["flat"],
            "avoid": stats["avoid"],
            "step": stats["step"],
            "miss": stats["miss"],  # stop + flat
        },
    }

    for sector, s in by_sector.items():
        # miss = stop + flat 已包含，total_s 不单独加 miss 避免重复计算
        total_s = s["hit"] + s["stop"] + s["flat"] + s["avoid"] + s["step"]
        correct_s = s["hit"] + s["avoid"]
        group_summary["by_sector"][sector] = {
            "total": total_s,
            "accuracy": round(correct_s / total_s * 100, 1) if total_s else 0,
            "hit": s["hit"],
            "stop": s["stop"],
            "flat": s["flat"],
            "avoid": s["avoid"],
            "step": s["step"],
            "miss": s["miss"],
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

    # 训练集: 取倒数第3-5天（保证至少3天可处理，避免最近2天因K线不足被跳过）
    # L6: 若取 sorted_dates[-3:]，最近2天的 Day1/Day2 K线可能尚未生成，
    #     collect() 内部会因 d0_idx+2>=len 而 continue 跳过，导致样本不足。
    #     改为取 [-5:-2]（倒数第3-5天），这3天都有完整的后续2天K线。
    if len(sorted_dates) >= 5:
        train_dates = sorted_dates[-5:-2]
    elif len(sorted_dates) >= 3:
        train_dates = sorted_dates[-3:]
    else:
        train_dates = sorted_dates
    print("Collecting for train dates: {}".format(train_dates))

    data = collect(train_dates)

    output_path = OUTPUT_DIR / "rollout.json"
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    o = data["group_summary"]["overall"]
    print("Collected {} results".format(len(data["rollout_results"])))
    print("  HIT: {}  STOP: {}  FLAT: {}  AVOID: {}  STEP: {}".format(
        o["hit"], o["stop"], o["flat"], o["avoid"], o["step"],
    ))
    print("  Accuracy: {}%".format(o["accuracy"]))
    print("Saved to: {}".format(output_path))


if __name__ == "__main__":
    main()
