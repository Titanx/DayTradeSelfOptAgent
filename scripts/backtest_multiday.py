"""多日回测: 针对每个有分析缓存的交易日,拉取下一个交易日实盘数据做回测"""
import json, urllib.request
from datetime import datetime
from pathlib import Path
from collections import defaultdict

RESULTS_DIR = Path(__file__).parent.parent / "data" / "results"

STOCKS = [
    ("sz300750", "宁德时代"),
    ("sh600438", "通威股份"),
    ("sz300033", "同花顺"),
    ("sz002202", "金风科技"),
    ("sz002415", "海康威视"),
]


# ---- 2. 拉取所有K线 ----------
def get_kline(sid):
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sid},day,,,30,qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read().decode("utf-8"))
    return data["data"][sid]["qfqday"]


def main():
    # ---- 1. 收集所有分析日期 ----------
    all_dates = set()
    for _, _, pure_code in [(sid[2:], name, sid[2:]) for sid, name in STOCKS]:
        for f in RESULTS_DIR.glob(f"{pure_code}_*_analysis.cache.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                td = d.get("trade_date", "")
                if td:
                    all_dates.add(td)
            except Exception as e:
                print(f"  读取 {f.name} 失败: {e}")
    dates = sorted(all_dates)
    print("分析缓存日期:", dates)

    # ---- 2. 拉取所有K线 ----------
    all_klines = {}
    for sid, _ in STOCKS:
        try:
            all_klines[sid] = get_kline(sid)
        except Exception as e:
            print(f"  拉取 {sid} 失败: {e}")

    # ---- 3. 每个日期做回测 ----------
    print("\n" + "=" * 72)
    print("  多日回测: 5 股 x 若干交易日")
    print("=" * 72)

    day_results = defaultdict(lambda: {"hit": 0, "avoid": 0, "miss": 0, "step": 0})

    today_str = datetime.now().strftime("%Y-%m-%d")

    for trade_date in dates:
        # 跳过当天(没下一天数据)
        if trade_date == today_str:
            print(f"\n{'─' * 72}")
            print(f"  {trade_date}: 当天无次日数据,跳过")
            continue

        print(f"\n{'─' * 72}")
        print(f"  Day0: {trade_date}")
        print(f"{'─' * 72}")

        for sid, name in STOCKS:
            pure_code = sid[2:]
            pred_file = RESULTS_DIR / f"{pure_code}_{trade_date}_analysis.cache.json"
            if not pred_file.exists():
                print(f"  {pure_code} {name}: 无预测数据 → 跳过")
                continue

            try:
                pred = json.loads(pred_file.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  {pure_code} {name}: 读取失败 → 跳过 ({e})")
                continue

            klines = all_klines.get(sid)
            if not klines:
                continue

            d0_close = None
            d1_open = d1_close = d1_high = d1_low = None
            d1_date = None
            for k in klines:
                if k[0] == trade_date:
                    d0_close = float(k[2])
                if d1_close is None and d0_close is not None and k[0] > trade_date:
                    d1_date = k[0]
                    d1_open = float(k[1])
                    d1_close = float(k[2])
                    d1_high = float(k[3])
                    d1_low = float(k[4])
                    break

            if d0_close is None:
                print(f"  {pure_code} {name}: {trade_date} 无K线")
                continue
            if d1_close is None:
                print(f"  {pure_code} {name}: {trade_date} 无次日数据(可能周末)")
                continue

            rating = pred.get("rating", "?")
            confidence = pred.get("confidence", 0)

            close_pct = (d1_close / d0_close - 1) * 100
            open_pct = (d1_close / d1_open - 1) * 100
            net_pct = open_pct - 0.11

            should_buy = rating in ("Buy", "Overweight")
            actually_up = close_pct >= 1.0

            if should_buy and actually_up:
                verdict = "HIT"
            elif should_buy:
                verdict = "MISS"
            elif actually_up:
                verdict = "STEP"
            else:
                verdict = "AVOID"

            day_results[trade_date][verdict.lower().replace(" ","_")] += 1

            print(f"  {pure_code} {name}: {rating:12s} conf={confidence:.0%}  →  {d1_date}: {close_pct:+.2f}%  [{verdict}]")

    # ---- 4. 汇总 ----------
    print("\n" + "=" * 72)
    print("  汇总表")
    print("=" * 72)

    total_hit = total_avoid = total_miss = total_step = 0
    for td in dates:
        if td == today_str:
            continue
        r = day_results[td]
        h, a, m, s = r.get("hit", 0), r.get("avoid", 0), r.get("miss", 0), r.get("step", 0)
        total = h + a + m + s
        if total == 0:
            continue
        total_hit += h
        total_avoid += a
        total_miss += m
        total_step += s
        acc = (h + a) / total * 100
        print(f"\n  {td}: 命中{h} 回避{a} 误判{m} 踏空{s}  准确率: {acc:.0f}% ({h+a}/{total})")

    grand_total = total_hit + total_avoid + total_miss + total_step
    if grand_total:
        print(f"\n{'─' * 50}")
        print(f"  总计: {grand_total} 笔")
        print(f"  命中: {total_hit}  |  回避: {total_avoid}  |  误判: {total_miss}  |  踏空: {total_step}")
        print(f"  总准确率: {(total_hit+total_avoid)/grand_total*100:.0f}%")
        print(f"  Buy信号准确率: {total_hit}/{total_hit+total_miss} = {total_hit/(total_hit+total_miss)*100 if (total_hit+total_miss) else 0:.0f}%")


if __name__ == "__main__":
    main()
