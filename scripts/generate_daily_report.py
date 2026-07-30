# Generate daily report: forecast (pre-market) or backtest (post-close) -> daily_reports/
# Usage:
#   python generate_daily_report.py --mode forecast              # 预报: 最新cache预测展示
#   python generate_daily_report.py --mode backtest --d1 DATE    # 回测: D1买入日cache -> D2实盘
#   python generate_daily_report.py --mode combined              # 旧版合并 (向后兼容)
import json
import urllib.request
import sys
import argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))
RESULTS_DIR = PROJECT_DIR / "data" / "results"
REPORTS_DIR = PROJECT_DIR / "daily_reports"

from scripts.stock_universe import stocks_for_collector
# M-scripts-1 (round-9): 报告时间戳用北京时间，避免非北京时间服务器上文件名/Generated 偏移
from dataflows.akshare_adapter import _BJ_TIME
# (round-9, L-scripts-4): 引入 get_config 以读取模型名，避免硬编码
from config.default_config import get_config
STOCKS = stocks_for_collector()

# ---- parse args ----
parser = argparse.ArgumentParser()
parser.add_argument("--mode", choices=["forecast", "backtest", "combined"], default="combined")
parser.add_argument("--d1", default=None, help="backtest mode: D1 buy date (YYYY-MM-DD)")
args = parser.parse_args()

RATING_EMOJI = {"Overweight": "OW", "Buy": "BUY", "Hold": "HOLD", "Underweight": "UW", "Sell": "SELL"}


def get_kline(sid):
    code = sid[2:]
    if code.startswith(("6", "9")):
        sid = "sh" + code
    else:
        sid = "sz" + code
    url = (
        "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        "?param={sid},day,,,10,qfq".format(sid=sid)
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read().decode("utf-8"))["data"][sid]
    for key in ("qfqday", "day"):
        if data.get(key):
            return data[key]
    return []


def load_predictions(date_str):
    preds = {}
    for pattern in [f"*_{date_str}_v10_analysis.cache.json", f"*_{date_str}_analysis.cache.json"]:
        for f in RESULTS_DIR.glob(pattern):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                code = d.get("symbol", "")
                if not code:
                    code = f.stem.split("_")[0]
                    d["symbol"] = code
                if code not in preds:
                    preds[code] = d
            except Exception as e:
                print(f"  [warn] 跳过损坏的缓存 {f.name}: {e}", file=sys.stderr)
    return preds


def pct_str(v):
    return "{:+.2f}%".format(v)


# (P1-fix#9) 提取纯函数用于单元测试 — 模拟单笔交易收益计算
def simulate_trade_return(high_pct, low_pct, close_pct,
                          target_gain_pct, stop_loss_pct):
    """根据 D2 日内价格波动计算单笔交易收益(%)。

    保守最坏情形假设: 日内时序不可还原，若最低价触及止损则按止损计。
    实际可能存在先 +1% 止盈再回落 -3% 的场景，此处简化为保守判断。

    Args:
        high_pct:  (d2_high / d1_open - 1) * 100
        low_pct:   (d2_low  / d1_open - 1) * 100, 可为 None
        close_pct: (d2_close/ d1_open - 1) * 100
        target_gain_pct: 止盈阈值(正数, 如 1.0 表示 +1%)
        stop_loss_pct:   止损阈值(正数, 如 3.0 表示 -3%)

    Returns:
        (trade_ret_pct, action) — action ∈ {"TP","SL","Close"}
    """
    if low_pct is not None and low_pct <= -stop_loss_pct:
        return -stop_loss_pct, "SL"
    if high_pct >= target_gain_pct:
        return target_gain_pct, "TP"
    return close_pct, "Close"


def calc_pnl(trades, initial_capital, target_gain_pct, stop_loss_pct):
    """汇总模拟交易损益。

    Args:
        trades: list of {"code","name","pos"(小数),"ret"(%)}
        initial_capital: 初始本金
        target_gain_pct: 止盈阈值(正数, 如 1.0)
        stop_loss_pct:   止损阈值(正数, 如 3.0)

    Returns:
        dict with keys: total_pos, weighted_ret_pct, profit,
                        tp_count, sl_count, close_count
    """
    total_pos = sum(t["pos"] for t in trades)
    weighted_ret_pct = sum(t["ret"] * t["pos"] for t in trades)
    profit = weighted_ret_pct / 100.0 * initial_capital
    tp_count = sum(1 for t in trades if t["ret"] >= target_gain_pct)
    sl_count = sum(1 for t in trades if t["ret"] <= -stop_loss_pct)
    close_count = len(trades) - tp_count - sl_count
    return {
        "total_pos": total_pos,
        "weighted_ret_pct": weighted_ret_pct,
        "profit": profit,
        "tp_count": tp_count,
        "sl_count": sl_count,
        "close_count": close_count,
    }


# ---- discover dates ----
# M-scripts-1 (round-9): 用 _BJ_TIME 保证报告文件名与 Generated 时间戳在非北京时间服务器上也正确
today = datetime.now(_BJ_TIME)
today_str = today.strftime("%Y-%m-%d")

all_dates = set()
for pattern in ["*_v10_analysis.cache.json", "*_analysis.cache.json"]:
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
    print("No analysis data")
    sys.exit(0)

# mode-based date selection
# forecast: analysis_date = latest cache (D1 buy date)
# backtest: backtest_date = --d1 (D1 buy date), D2 = next trading day (auto-discover from kline)
# combined: analysis_date = latest, backtest_date = second latest (legacy D0 model)
if args.mode == "backtest":
    if not args.d1:
        print("backtest mode requires --d1 YYYY-MM-DD")
        sys.exit(1)
    backtest_date = args.d1
    analysis_date = None
elif args.mode == "forecast":
    analysis_date = sorted_dates[-1]
    backtest_date = None
else:  # combined
    analysis_date = sorted_dates[-1]
    backtest_date = sorted_dates[-2] if len(sorted_dates) >= 2 else None

print("Today: " + today_str)
print("Mode: " + args.mode)
if analysis_date:
    print("Analysis date: " + analysis_date)
if backtest_date:
    print("Backtest D1 (buy): " + backtest_date)

# ---- build report ----
_report_title_suffix = {"forecast": "Forecast", "backtest": "Backtest", "combined": "Daily"}.get(args.mode, "Daily")
lines = []
lines.append("# DayTradeSelfOptAgent {} Report - {}".format(_report_title_suffix, today_str))
lines.append("")
lines.append(
    "> **Disclaimer**: This report is auto-generated by an AI multi-agent system. "
    "All analysis results are for educational/research purposes ONLY and do NOT constitute "
    "any investment advice. Past performance does not guarantee future results. "
    "The system may produce errors - do NOT use for real trading."
)
lines.append("")
lines.append("**Generated**: " + today.strftime("%Y-%m-%d %H:%M"))
lines.append("**Strategy**: One-Day Swing (Day0 analyze -> Day1 buy -> Day2 force close)")
# (round-9, L-scripts-4): 模型名从 config 读取，避免硬编码 DeepSeek-V4
_d_cfg = get_config()
# (round-12, C-scripts-3): 从 config 读取 target_gain_pct，避免硬编码 1.0
TARGET_GAIN_PCT = _d_cfg.get("one_day_swing", {}).get("target_gain_pct", 1.0)
STOP_LOSS_PCT = _d_cfg.get("one_day_swing", {}).get("stop_loss_pct", 3.0)
INITIAL_CAPITAL = _d_cfg.get("initial_capital", 1000000)
# (P0-fix#3) 策略铁律: 单票仓位上限强制约束，避免预测结果异常突破 max_position_pct
MAX_POSITION_PCT = _d_cfg.get("max_position_pct", 0.2)
lines.append("**Model**: " + str(_d_cfg.get("deep_think_llm", "?")) + "  temperature=" + str(_d_cfg.get("temperature", "?")))
# (P3-fix#5) Target 字符串使用配置值，避免改 config 后报告头不同步
lines.append("**Target**: >={tp}% gain (net ~{net:.2f}% after 0.11% cost)".format(
    tp=int(TARGET_GAIN_PCT), net=TARGET_GAIN_PCT - 0.11))
lines.append("")

# ====== Part 1: Today's Prediction ======
if args.mode in ("forecast", "combined") and analysis_date:
    lines.append("---")
    lines.append("")
    lines.append("## 1. Today's Prediction (" + analysis_date + " -> next trading day)")
    lines.append("")

    preds = load_predictions(analysis_date)
    if preds:
        by_sector = defaultdict(list)
        for sid, name, sector in STOCKS:
            code = sid[2:]
            if code in preds:
                by_sector[sector].append((code, name, preds[code]))

        buy_count = sum(1 for p in preds.values() if p["rating"] in ("Buy", "Overweight"))
        hold_count = sum(1 for p in preds.values() if p["rating"] == "Hold")
        uw_count = sum(1 for p in preds.values() if p["rating"] == "Underweight")
        sell_count = sum(1 for p in preds.values() if p["rating"] == "Sell")

        lines.append("| BUY/OW | HOLD | UW | SELL |")
        lines.append("|:--:|:--:|:--:|:--:|")
        lines.append(
            "| **{b}** | {h} | {u} | {s} |".format(
                b=buy_count, h=hold_count, u=uw_count, s=sell_count
            )
        )
        lines.append("")

        sector_names = [("Solar", "Solar"), ("Wind", "Wind"), ("AI", "AI"),
                        ("Energy", "Energy Storage"), ("Vision", "Vision")]
        for sector_key, sector_label in sector_names:
            if sector_key not in by_sector:
                continue
            lines.append("### " + sector_label)
            lines.append("")
            lines.append("| Code | Name | Rating | Confidence |")
            lines.append("|------|------|:--:|:--:|")
            for code, name, p in by_sector[sector_key]:
                r = p["rating"]
                lines.append(
                    "| {c} | {n} | {rt} | {cf:.0%} |".format(
                        c=code, n=name, rt=r, cf=p["confidence"]
                    )
                )
            lines.append("")

        if buy_count > 0:
            lines.append("### Buy Signals")
            lines.append("")
            for p in preds.values():
                if p["rating"] in ("Buy", "Overweight"):
                    summary = (p.get("summary") or p.get("investment_logic") or "-")[:200]
                    lines.append(
                        "- **{s}** ({r}, conf {cf:.0%}): {sm}".format(
                            s=p["symbol"], r=p["rating"], cf=p["confidence"], sm=summary
                        )
                    )
            lines.append("")
    else:
        lines.append("*No analysis data for today*")
        lines.append("")

# ====== Part 2: Backtest ======
# --d1 = D0 analysis date (= cache trade_date)
# D0 (close) -> D1 (next-day open buy) -> D2 (next-day high/close sell)
if args.mode in ("backtest", "combined") and backtest_date:
    _is_d1_model = False  # backtest mode also uses D0 model (was: args.mode == "backtest")
    lines.append("---")
    lines.append("")
    if args.mode == "backtest":
        lines.append("## Backtest (D0={} analyze -> D1 buy -> D2 sell)".format(backtest_date))
    else:
        lines.append("## 2. Yesterday's Backtest ({} prediction -> next-day actual)".format(backtest_date))
    lines.append("")

    backtest_preds = load_predictions(backtest_date)
    if backtest_preds:
        hit = 0; avoid = 0; miss = 0; step = 0
        sim_trades = []  # v2.5: 模拟交易 (本金 100万, +1% 止盈 / -3% 止损 / 收盘平仓)
        table_lines = []
        table_lines.append("| Code | Name | Sector | Prediction | Conf | CloseChg | HighChg | Result |")
        table_lines.append("|------|------|--------|:--:|:--:|:--:|:--:|:--:|")

        for sid, name, sector in STOCKS:
            code = sid[2:]
            bp = backtest_preds.get(code)
            if not bp:
                continue
            try:
                klines = get_kline(sid)
                if _is_d1_model:
                    # D1 model (backtest mode): backtest_date=D1(买入日, open), D2=下一交易日(high/low/close)
                    d1_open = None; d2_high = d2_low = d2_close = None
                    for k in klines:
                        if k[0] == backtest_date:
                            d1_open = float(k[1])
                        if d1_open is not None and k[0] > backtest_date and d2_high is None:
                            d2_high = float(k[3])
                            d2_low = float(k[4])
                            d2_close = float(k[2])
                            break
                    if d1_open is None or d2_high is None or d2_low is None:
                        continue
                    close_pct = (d2_close / d1_open - 1) * 100
                else:
                    # D0 model (combined legacy): backtest_date=D0(分析日,close), D1=下一交易日(open), D2=再下一交易日(high/low/close)
                    d0_close = None; d1_open = None; d1_date = None; d2_high = d2_low = d2_close = None
                    for k in klines:
                        if k[0] == backtest_date:
                            d0_close = float(k[2])
                        if d1_open is None and d0_close is not None and k[0] > backtest_date:
                            d1_date = k[0]
                            d1_open = float(k[1])
                        if d1_open is not None and k[0] > d1_date and d2_high is None:
                            d2_high = float(k[3])
                            d2_low = float(k[4])
                            d2_close = float(k[2])
                            break
                    if d0_close is None or d1_open is None or d2_high is None or d2_low is None:
                        continue
            except Exception as e:
                # (P2-fix#8) 不再静默吞异常，输出 warning 便于排查数据问题
                print(f"  [warn] {code} K线获取/解析失败: {e}", file=sys.stderr)
                continue

            high_pct = (d2_high / d1_open - 1) * 100
            # (P3-fix#6) d2_low 真值判断改 is not None，避免 d2_low==0 的边界误判
            low_pct = (d2_low / d1_open - 1) * 100 if d2_low is not None else None
            close_pct = (d2_close / d1_open - 1) * 100
            should_buy = bp["rating"] in ("Buy", "Overweight")
            actually_up = high_pct >= TARGET_GAIN_PCT
            # (P3-fix#7) 删除冗余 step_trig (与 actually_up 完全相同)

            if should_buy and actually_up:
                v = "HIT"; hit += 1
            elif should_buy:
                v = "MISS"; miss += 1
            elif actually_up:
                v = "STEP"; step += 1
            else:
                v = "AVOID"; avoid += 1

            table_lines.append(
                "| {c} | {n} | {sec} | {r} | {cf:.0%} | {cp} | {op} | {v} |".format(
                    c=code, n=name, sec=sector, r=bp["rating"], cf=bp["confidence"],
                    cp=pct_str(close_pct), op=pct_str(high_pct), v=v,
                )
            )

            # v2.5: 模拟收益 (仅 Buy/Overweight) — +1% 止盈 / -3% 止损 / 收盘平仓
            if should_buy:
                # (P0-fix#3) 策略铁律: 单票仓位 <= MAX_POSITION_PCT (默认 20%)
                raw_pos = bp.get("position_pct", 0.1)
                pos_pct = min(raw_pos if raw_pos else 0.1, MAX_POSITION_PCT)
                # (P1-fix#9) 调用纯函数计算单笔收益
                trade_ret, _action = simulate_trade_return(
                    high_pct, low_pct, close_pct, TARGET_GAIN_PCT, STOP_LOSS_PCT)
                sim_trades.append({"code": code, "name": name, "pos": pos_pct, "ret": trade_ret})

        total = hit + avoid + miss + step
        if total == 0:
            lines.append("*无有效回测数据（下一个交易日尚未发生）*")
            lines.append("")
        else:
            lines.append("| Metric | Value |")
            lines.append("|--------|:--:|")
            lines.append("| Total | {t} |".format(t=total))
            lines.append("| HIT (Buy->up>=1%) | {h} |".format(h=hit))
            lines.append("| AVOID (Hold->not up) | {a} |".format(a=avoid))
            lines.append("| MISS (Buy->down/fail) | {m} |".format(m=miss))
            lines.append("| STEP (Hold->up>=1%) | {s} |".format(s=step))
            lines.append(
                "| Accuracy | **{acc:.0f}%** |".format(acc=(hit + avoid) / total * 100)
            )
            if hit + miss > 0:
                lines.append(
                    "| Buy Precision | {h}/{t2} = {pct:.0f}% |".format(
                        h=hit, t2=hit + miss, pct=hit / (hit + miss) * 100
                    )
                )
            lines.append("")

            # v2.5: 模拟收益 (本金按 config, 单票按仓位比例, +1% 止盈 / -3% 止损 / 收盘平仓)
            if sim_trades:
                # (P1-fix#9) 调用纯函数汇总损益
                pnl = calc_pnl(sim_trades, INITIAL_CAPITAL, TARGET_GAIN_PCT, STOP_LOSS_PCT)
                total_pos = pnl["total_pos"]
                weighted_ret_pct = pnl["weighted_ret_pct"]
                profit = pnl["profit"]
                tp_count = pnl["tp_count"]
                sl_count = pnl["sl_count"]
                close_count = pnl["close_count"]

                lines.append("### 💰 Simulated P&L (Capital ¥{cap:,})".format(cap=INITIAL_CAPITAL))
                lines.append("")
                lines.append("| Metric | Value |")
                lines.append("|--------|:--:|")
                lines.append("| Trades | {n} |".format(n=len(sim_trades)))
                lines.append("| Total Position | {p:.0%} |".format(p=total_pos))
                lines.append("| Take-Profit (+{tp}%) | {c} |".format(tp=int(TARGET_GAIN_PCT), c=tp_count))
                lines.append("| Stop-Loss (-{sl}%) | {c} |".format(sl=int(STOP_LOSS_PCT), c=sl_count))
                lines.append("| Close (forced) | {c} |".format(c=close_count))
                lines.append("| Return | **{r:+.2f}%** |".format(r=weighted_ret_pct))
                lines.append("| Profit | **¥{p:,.0f}** |".format(p=profit))
                lines.append("")
                # (P2-fix#4) 总仓位超额风险提示
                if total_pos > 1.0:
                    lines.append("> ⚠️ Total position {p:.0%} > 100%: requires margin/leverage or per-trade capital reallocation".format(p=total_pos))
                    lines.append("")

                # 明细表 — 按 ret 阈值分类 (trade_ret 已是结算后值，无需重算)
                lines.append("| Code | Name | Position | Return | Action |")
                lines.append("|------|------|:--:|:--:|:--:|")
                for t in sim_trades:
                    if t["ret"] >= TARGET_GAIN_PCT:
                        act = "TP"
                    elif t["ret"] <= -STOP_LOSS_PCT:
                        act = "SL"
                    else:
                        act = "Close"
                    lines.append("| {c} | {n} | {p:.0%} | {r:+.2f}% | {a} |".format(
                        c=t["code"], n=t["name"], p=t["pos"], r=t["ret"], a=act))
                lines.append("")

        lines.extend(table_lines)
        lines.append("")
    else:
        lines.append("*No prediction data for " + str(backtest_date) + "*")
        lines.append("")

# ---- write ----
REPORTS_DIR.mkdir(exist_ok=True)
if args.mode == "backtest":
    report_path = REPORTS_DIR / (today_str + "_backtest.md")
elif args.mode == "forecast":
    report_path = REPORTS_DIR / (today_str + "_forecast.md")
else:
    report_path = REPORTS_DIR / (today_str + "_daily_report.md")
report_path.write_text("\n".join(lines), encoding="utf-8")
print("\nReport saved: " + str(report_path))
