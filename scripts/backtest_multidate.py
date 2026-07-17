import json
import re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_DIR / "data" / "results"
CACHE_DIR = PROJECT_DIR / "data" / "stock_cache"

STOCK_UNIVERSE = [
    ("600438", "通威股份", "光伏"), ("601012", "隆基绿能", "光伏"), ("300274", "阳光电源", "光伏"),
    ("688599", "天合光能", "光伏"), ("300751", "迈为股份", "光伏"), ("002459", "晶澳科技", "光伏"),
    ("603806", "福斯特", "光伏"), ("300763", "锦浪科技", "光伏"), ("600732", "爱旭股份", "光伏"),
    ("688390", "固德威", "光伏"),
    ("002202", "金风科技", "风电"), ("601615", "明阳智能", "风电"), ("603606", "东方电缆", "风电"),
    ("300850", "新强联", "风电"), ("001289", "龙源电力", "风电"), ("002531", "天顺风能", "风电"),
    ("300772", "运达股份", "风电"), ("002080", "中材科技", "风电"), ("002487", "大金重工", "风电"),
    ("300129", "泰胜风能", "风电"),
    ("002230", "科大讯飞", "AI"), ("688256", "寒武纪", "AI"), ("000977", "浪潮信息", "AI"),
    ("300308", "中际旭创", "AI"), ("300033", "同花顺", "AI"), ("601360", "三六零", "AI"),
    ("300418", "昆仑万维", "AI"), ("300229", "拓尔思", "AI"), ("688041", "海光信息", "AI"),
    ("688327", "云从科技", "AI"),
    ("300750", "宁德时代", "储能"), ("300014", "亿纬锂能", "储能"), ("002074", "国轩高科", "储能"),
    ("002460", "赣锋锂业", "储能"), ("601727", "上海电气", "储能"), ("300073", "当升科技", "储能"),
    ("688063", "派能科技", "储能"), ("300207", "欣旺达", "储能"), ("300438", "鹏辉能源", "储能"),
    ("300068", "南都电源", "储能"),
    ("002415", "海康威视", "视觉"), ("002236", "大华股份", "视觉"), ("002920", "德赛西威", "视觉"),
    ("300496", "中科创达", "视觉"), ("603501", "韦尔股份", "视觉"), ("002456", "欧菲光", "视觉"),
    ("688088", "虹软科技", "视觉"), ("688207", "格灵深瞳", "视觉"), ("688400", "凌云光", "视觉"),
    ("688686", "奥普特", "视觉"),
]

ALL_DATES = ["2026-06-26", "2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02", "2026-07-04"]


def date_plus_one(d):
    parts = d.split("-")
    from datetime import date, timedelta
    dt = date(int(parts[0]), int(parts[1]), int(parts[2])) + timedelta(days=1)
    return dt.strftime("%Y-%m-%d")


def load_prediction(code, pred_date):
    cache_file = RESULTS_DIR / f"{code}_{pred_date}_v10_analysis.cache.json"
    if not cache_file.exists():
        return None
    with open(cache_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    decision_str = data.get("decision", "")
    json_match = re.search(r'\{[^{}]*"decision"[^{}]*\}', decision_str, re.DOTALL)
    conf = 0
    position = 0
    decision_label = data.get("rating", "N/A")
    if json_match:
        try:
            d = json.loads(json_match.group())
            decision_label = d.get("decision", decision_label)
            position = d.get("position", 0)
            conf = d.get("confidence", 0)
        except json.JSONDecodeError:
            pass

    return {"symbol": code, "stock_name": data.get("stock_name", ""),
            "rating": data.get("rating", "N/A"), "position": position, "confidence": conf,
            "decision_label": decision_label}


def parse_price_cache(code, date1, date2, cache_date):
    cache_file = CACHE_DIR / code / f"{cache_date}_get_stock_price_data.md"
    if not cache_file.exists():
        return None, None

    with open(cache_file, "r", encoding="utf-8") as f:
        content = f.read()

    result = {date1: None, date2: None}
    in_table = False
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("| date"):
            in_table = True
            continue
        if not in_table or not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 2:
            continue
        d = parts[0].strip()
        if d in (date1, date2):
            try:
                result[d] = float(parts[1].replace(",", ""))
            except (ValueError, IndexError):
                continue

    if result[date1] is None or result[date2] is None:
        return None, None
    return result[date1], result[date2]


def classify_rating(rating_str):
    rl = rating_str.lower()
    if any(k in rl for k in ["buy", "overweight", "买入", "增持"]):
        return "看多"
    if any(k in rl for k in ["sell", "underweight", "卖出", "减持"]):
        return "看空"
    return "观望"


def run_backtest(pred_date, actual_date, cache_date, label):
    records = []
    missing = 0

    for code, name, sector in STOCK_UNIVERSE:
        pred = load_prediction(code, pred_date)
        if pred is None:
            missing += 1
            continue

        c1, c2 = parse_price_cache(code, pred_date, actual_date, cache_date)
        if c1 is None:
            missing += 1
            continue

        change = round((c2 - c1) / c1 * 100, 2)
        lab = classify_rating(pred["rating"])

        missed = False
        if lab != "看多" and change >= 1.0:
            missed = True

        records.append({"code": code, "name": name, "sector": sector, "change": change,
                        "label": lab, "missed": missed, "rating": pred["rating"],
                        "confidence": pred["confidence"], "position": pred["position"]})

    if len(records) < 10:
        return None

    bullish = sum(1 for r in records if r["label"] == "看多")
    bearish = sum(1 for r in records if r["label"] == "看空")
    hold = sum(1 for r in records if r["label"] == "观望")
    missed_up = [r for r in records if r["missed"]]
    up_count = sum(1 for r in records if r["change"] > 0)
    down_count = sum(1 for r in records if r["change"] < 0)
    avg_change = sum(r["change"] for r in records) / len(records) if records else 0

    total_up_ge1 = sum(1 for r in records if r["change"] >= 1.0)
    missed_rate = len(missed_up) / total_up_ge1 * 100 if total_up_ge1 > 0 else 0

    sector_stats = {}
    for r in records:
        sec = r["sector"]
        if sec not in sector_stats:
            sector_stats[sec] = {"total": 0, "missed": 0, "up": 0, "up_ge1": 0, "changes": []}
        sector_stats[sec]["total"] += 1
        sector_stats[sec]["changes"].append(r["change"])
        if r["missed"]:
            sector_stats[sec]["missed"] += 1
        if r["change"] > 0:
            sector_stats[sec]["up"] += 1
        if r["change"] >= 1.0:
            sector_stats[sec]["up_ge1"] += 1

    return {
        "pred_date": pred_date, "actual_date": actual_date, "label": label,
        "n": len(records), "missing": missing,
        "bullish": bullish, "hold": hold, "bearish": bearish,
        "up": up_count, "down": down_count,
        "avg_change": avg_change, "up_ge1": total_up_ge1,
        "missed_up": len(missed_up), "missed_rate": missed_rate,
        "missed_list": [(r["code"], r["name"], r["sector"], r["change"], r["confidence"]) for r in missed_up],
        "sector_stats": sector_stats,
        "total_bullish_correct": sum(1 for r in records if r["label"] == "看多" and r["change"] >= 1.0),
        "bullish_wrong": sum(1 for r in records if r["label"] == "看多" and r["change"] < 0),
    }


def main():
    pred_to_cache = {
        "2026-06-26": ("2026-06-26", "2026-06-27", "2026-06-29"),
        "2026-06-29": ("2026-06-29", "2026-06-30", "2026-06-30"),
        "2026-06-30": ("2026-06-30", "2026-07-01", "2026-07-01"),
        "2026-07-01": ("2026-07-01", "2026-07-02", "2026-07-02"),
        "2026-07-02": ("2026-07-02", "2026-07-03", "2026-07-04"),
        # (round-11, C-scripts-1): 修复 7/4 自回测错误，actual_date 应为下一交易日 7/7
        "2026-07-04": ("2026-07-04", "2026-07-07", "2026-07-07"),
    }

    print("=" * 90)
    print("  多日期对比回测: 逐日踏空率趋势")
    print("=" * 90)

    results = []
    for pred_date in ALL_DATES:
        d1, d2, cache_d = pred_to_cache[pred_date]
        label = f"{d1}→{d2}"
        bt = run_backtest(pred_date, d2, cache_d, label)
        if bt:
            results.append(bt)

    if not results:
        print("  无可用回测数据")
        return

    print(f"\n{'预测日期':<12} {'回测区间':<18} {'样本':>4} {'看多':>4} {'观望':>4} {'看空':>4} "
          f"{'实际上涨':>6} {'均涨跌':>8} {'涨≥1%':>5} {'踏空':>4} {'踏空率(分母=涨≥1%)':>18} {'命中':>4} {'误判':>4}")
    print("-" * 90)

    for bt in results:
        correct = bt["total_bullish_correct"]
        wrong = bt["bullish_wrong"]
        print(f"{bt['pred_date']:<12} {bt['label']:<18} {bt['n']:>4} {bt['bullish']:>4} {bt['hold']:>4} {bt['bearish']:>4} "
              f"{bt['up']:>4}/{bt['n']:>2} {bt['avg_change']:>+7.2f}% {bt['up_ge1']:>5} {bt['missed_up']:>4} "
              f"{bt['missed_rate']:>6.1f}% {correct:>4} {wrong:>4}")
    print("-" * 90)

    print("\n" + "=" * 90)
    print("  踏空率趋势分析")
    print("=" * 90)

    if len(results) >= 2:
        print(f"\n  {'日期':<18} {'踏空率':>8} {'趋势'}")
        print(f"  {'-'*35}")
        for bt in results:
            arrow = "←"
            if len(results) > 1:
                idx = results.index(bt)
                if idx > 0:
                    prev = results[idx - 1]["missed_rate"]
                    curr = bt["missed_rate"]
                    if curr < prev - 5:
                        arrow = "↓↓ 显著改善"
                    elif curr < prev - 1:
                        arrow = "↓ 小幅改善"
                    elif curr > prev + 5:
                        arrow = "↑↑ 显著恶化"
                    elif curr > prev + 1:
                        arrow = "↑ 小幅恶化"
                    else:
                        arrow = "→ 持平"
            print(f"  {bt['label']:<18} {bt['missed_rate']:>7.1f}%  {arrow}")

    print("\n  分板块踏空趋势:")
    sectors = ["光伏", "风电", "AI", "储能", "视觉"]
    header = f"  {'板块':<6}"
    for bt in results:
        header += f" {bt['label']:>16}"
    print(header)
    for sec in sectors:
        line = f"  {sec:<6}"
        for bt in results:
            ss = bt["sector_stats"].get(sec, {})
            missed = ss["missed"] if ss else 0
            up_ge1 = ss["up_ge1"] if ss else 0
            rate = missed / up_ge1 * 100 if up_ge1 > 0 else 0
            avg = sum(ss["changes"]) / len(ss["changes"]) if ss.get("changes") else 0
            line += f"  {avg:>+6.2f}% {missed}/{up_ge1:>2}"
        print(line)

    print("\n" + "=" * 90)
    print("  结论 (踏空率 = 踏空数 / 涨≥1%数)")
    print("=" * 90)

    if len(results) >= 3:
        first_bt = results[0]
        last_bt = results[-1]
        delta = last_bt["missed_rate"] - first_bt["missed_rate"]

        print(f"\n  首日 ({first_bt['label']}) 涨≥1%: {first_bt['up_ge1']}只  踏空: {first_bt['missed_up']}只  踏空率: {first_bt['missed_rate']:.1f}%")
        print(f"  最近 ({last_bt['label']}) 涨≥1%: {last_bt['up_ge1']}只  踏空: {last_bt['missed_up']}只  踏空率: {last_bt['missed_rate']:.1f}%")

        if delta < -20:
            print(f"  ✅ 踏空率显著改善 ({delta:+.1f}pp)")
        elif delta < -5:
            print(f"  👍 踏空率小幅改善 ({delta:+.1f}pp)")
        elif delta > 20:
            print(f"  ❌ 踏空率显著恶化 ({delta:+.1f}pp)")
        elif delta > 5:
            print(f"  ⚠ 踏空率小幅恶化 ({delta:+.1f}pp)")
        else:
            print(f"  ➡ 踏空率基本持平 ({delta:+.1f}pp)")

    if results:
        last = results[-1]
        print(f"\n  关键矛盾: 策略{last['bullish']}只看多，")
        print(f"  但市场{last['up_ge1']}/{last['n']}只涨≥1%。")
        if last["bullish"] == 0:
            print(f"  根本问题: 策略从未发出买入信号 → 涨≥1%的股票100%踏空。")
        elif last["bullish"] <= 3:
            print(f"  问题: 看多信号太少，覆盖率不足。")
    print()


if __name__ == "__main__":
    main()
