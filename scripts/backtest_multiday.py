"""多日回测: 针对每个有分析缓存的交易日,拉取下一个交易日实盘数据做回测"""
import json, urllib.request, sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))
RESULTS_DIR = PROJECT_DIR / "data" / "results"

# M-scripts-2 (round-9): 用 _BJ_TIME 判定"当天"，避免非北京时间服务器与缓存 trade_date 错位
from dataflows.akshare_adapter import _BJ_TIME
# M-scripts-4 (round-9): STEP 基准统一为 d1o（买入价），与 collector.py / batch_backtest.py 对齐
from config.default_config import get_config as _get_cfg
_swing_cfg = _get_cfg().get("one_day_swing", {})
TARGET_GAIN_PCT = _swing_cfg.get("target_gain_pct", 1.0)   # 止盈线 +1%

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
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    klines = data["data"][sid].get("qfqday") or data["data"][sid].get("day", [])
    return klines


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

    # M-scripts-2 (round-9): 用 _BJ_TIME 判定"当天"，跳过当天无次日数据的逻辑才不会错位
    today_str = datetime.now(_BJ_TIME).strftime("%Y-%m-%d")

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
            # M-scripts-4 (round-9): 补 d1_open/d1_high 的 None 校验，避免 d1o 基准计算抛 TypeError
            if d1_open is None or d1_high is None:
                print(f"  {pure_code} {name}: {trade_date} 次日开/高缺失")
                continue

            rating = pred.get("rating", "?")
            confidence = pred.get("confidence", 0)

            close_pct = (d1_close / d0_close - 1) * 100  # 仅打印参考，不参与 HIT 判定
            # (round-11, C-scripts-2): HIT 基准从 d0_close 改为 d1_open（实际买入价），
            # 与 collector.py 的 d1_open 基准对齐，避免隔夜跳空与盘内涨跌混淆
            open_pct = (d1_close / d1_open - 1) * 100
            net_pct = open_pct - 0.11  # 扣除成本

            should_buy = rating in ("Buy", "Overweight")
            # (round-12, H-scripts-5): HIT 也用 high 基准（日内触达止盈线即 HIT），与 STEP 对称
            # HIT=已建仓的止盈，STEP=未建仓的踏空，两者基准相同但语义不同
            hit_trig = (d1_high / d1_open - 1) * 100 >= TARGET_GAIN_PCT
            step_trig = (d1_high / d1_open - 1) * 100 >= TARGET_GAIN_PCT

            if should_buy and hit_trig:
                verdict = "HIT"
            elif should_buy:
                verdict = "MISS"
            elif step_trig:
                verdict = "STEP"
            else:
                verdict = "AVOID"

            day_results[trade_date][verdict.lower().replace(" ","_")] += 1

            print(f"  {pure_code} {name}: {rating:12s} conf={confidence:.0%}  →  {d1_date}: c2c={close_pct:+.2f}% o2c={open_pct:+.2f}%  [{verdict}]")

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
