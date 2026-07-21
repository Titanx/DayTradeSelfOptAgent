"""batch_predict.py — 批量预测统一入口 (并发 + 增量 + 数据预加载 + 完整性校验 + 日期参数)

用法:
  python scripts/batch_predict.py                           # 今天 → 下一交易日
  python scripts/batch_predict.py 2026-06-26                # 指定日期 → 下一交易日
  python scripts/batch_predict.py 2026-06-26 --fresh         # 强制重跑全部

特性:
  - 并发: 5 workers 并行分析 (I/O 密集, ~5x 提速)
  - 增量: 跳过已有结果的股票 (rating != ERR)
  - 数据预加载: 大盘指数 + 市场情绪 + 北向资金 只拉一次
  - 个股数据集中获取: 价格/行情/财务/舆论 预先拉取并缓存
  - 完整性校验: 关键数据缺失时跳过个股，避免浪费 token
  - 解耦: 数据获取与 agent 辩论完全分离
"""

import sys, time, os, logging, json, argparse, random, copy
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from collections import defaultdict

project_dir = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_dir))
sys.path.insert(0, str(project_dir / "libs"))

from dotenv import load_dotenv
load_dotenv(project_dir / ".env", override=True)

logging.basicConfig(level=logging.WARNING, format="%(levelname)-5s %(message)s")

from config.default_config import get_config
from graph.trading_graph import AStockTradingGraph
from scripts.stock_universe import stocks_for_batch_predict
from scripts.market_overview import load_overview, overview_to_prompt
from dataflows.market_cache import MarketDataCache

ALL_STOCKS = stocks_for_batch_predict()

SECTOR_DESCRIPTIONS = {
    "光伏": "新能源光伏产业链，受政策补贴、海外需求、硅料价格影响。近期板块波动较大，关注超跌反弹信号。",
    "风电": "风力发电设备产业链，受益于碳中和政策，关注海上风电招标和原材料价格。",
    "AI": "人工智能/算力芯片板块，受AI应用落地、国产替代、海外芯片禁令影响。高波动高弹性。",
    "储能": "储能电池产业链，新能源配套刚需，关注宁德时代产业链延伸和锂价走势。",
    "视觉": "计算机视觉/安防/车载视觉板块，受智慧城市、自动驾驶、AI+应用落地驱动。",
}

SECTOR_BOARD_KEYWORDS = {
    "光伏": ["光伏", "太阳能"],
    "风电": ["风电", "风能", "电力"],
    "AI": ["人工智能", "AI", "半导体", "芯片", "算力", "计算机"],
    "储能": ["电池", "储能", "锂电", "新能源"],
    "视觉": ["光学", "电子", "安防", "机器视觉"],
}

CRITICAL_DATA = ["price"]

PUBLIC_DATA_KEYS = ["market_sentiment", "north_flow", "sector_data", "sector_fund_flow"]

_THROTTLE_INTERVAL = 1.0


def is_done(code, trade_date, version=""):
    ver_suffix = f"_{version}" if version else ""
    cache_file = project_dir / "data" / "results" / f"{code}_{trade_date}{ver_suffix}_analysis.cache.json"
    if cache_file.exists():
        try:
            d = json.loads(cache_file.read_text("utf-8"))
            if d.get("rating", "ERR") != "ERR":
                # (round-12, C-scripts-4): 同时返回 position_pct，供归一化使用
                return True, d["rating"], d.get("position_pct")
        except Exception:
            pass
    return False, None, None


def get_next_trade_date(date_str: str) -> str:
    from datetime import datetime, timedelta
    d = datetime.strptime(date_str, "%Y-%m-%d")
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _is_empty(data) -> bool:
    if data is None:
        return True
    s = str(data).strip()
    if not s:
        return True
    for fail_marker in ["获取失败", "ERROR", "数据不可用", "板块资金流数据获取失败"]:
        if fail_marker in s:
            return True
    if len(s) < 30:
        return True
    return False


def _degraded_realtime_from_price(price_md: str) -> str:
    return (
        "⚠️ 实时行情获取失败，以下为日线价格数据降级替代：\n\n"
        + price_md
        + "\n\n> 注: 实时行情接口不可用，请以日线收盘价为参考。日内波动数据缺失。"
    )


def _prefetch_public_data():
    from agents.utils.agent_utils import (
        get_market_sentiment_data,
        get_north_flow_data,
        get_sector_data,
        get_sector_fund_flow_data,
    )

    def _safe(name, fn):
        try:
            v = fn()
            return v if v else ""
        except Exception as e:
            logging.warning(f"prefetch {name} failed: {e}")
            return ""

    return {
        "market_sentiment": _safe("sentiment", get_market_sentiment_data),
        "north_flow": _safe("north", get_north_flow_data),
        "sector_data": _safe("sector", get_sector_data),
        "sector_fund_flow": _safe("fund_flow", get_sector_fund_flow_data),
    }


def _gather_stock_data(symbol, stock_name):
    from agents.utils.agent_utils import (
        get_stock_price_data,
        get_stock_realtime_quote,
        get_stock_financials,
        get_opinion_report,
    )
    price = get_stock_price_data(symbol)
    realtime = get_stock_realtime_quote(symbol)
    financials = get_stock_financials(symbol)
    opinion = get_opinion_report(symbol, stock_name)

    if _is_empty(realtime) and not _is_empty(price):
        realtime = _degraded_realtime_from_price(price)

    return {
        "price": price,
        "realtime": realtime,
        "financials": financials,
        "opinion": opinion,
    }


def _build_data_context(stock_data, public_data, market_overview):
    """Build a single comprehensive data context string for all analysts."""
    parts = []

    if market_overview:
        parts.append(f"## 大盘环境\n{market_overview}")

    for key, label in [
        ("price", "## 价格数据"),
        ("realtime", "## 实时行情"),
        ("financials", "## 财务数据"),
        ("opinion", "## 舆论情绪"),
    ]:
        if stock_data.get(key) and not _is_empty(stock_data[key]):
            parts.append(f"{label}\n{stock_data[key]}")

    for key, label in [
        ("market_sentiment", "## 市场情绪"),
        ("north_flow", "## 北向资金"),
        ("sector_data", "## 行业板块"),
        ("sector_fund_flow", "## 板块资金流"),
    ]:
        if public_data.get(key) and not _is_empty(public_data[key]):
            parts.append(f"{label}\n{public_data[key]}")

    return "\n\n".join(parts)


def compute_sector_momentum() -> dict:
    """板块动量加权: 解析板块资金流，返回我们的5个板块是否在top-3。

    调用已缓存的 route_to_vendor('get_sector_fund_flow') 获取结构化数据，
    然后通过关键词匹配将东财行业板块映射到我们的5大板块。
    晚间AKShare不稳定时，返回空dict跳过。

    Returns: {"光伏": "HOT(资金流入排名2/60)", "风电": None, ...}
    """
    try:
        from dataflows.interface import route_to_vendor
        data = route_to_vendor("get_sector_fund_flow", config={}, days=3)
        if not data or not isinstance(data, dict):
            return {}
    except Exception:
        return {}

    today_entries = data.get("today", [])
    # (round-12, H-scripts-2): 类型校验，避免非 list（None/string/dict）导致主流程崩溃
    if not isinstance(today_entries, list):
        return {}
    if not today_entries:
        return {}

    total_boards = len(today_entries)
    sector_scores = {sector: {"rank": 99, "name": "", "pct": 0, "net_inflow": 0}
                     for sector in SECTOR_BOARD_KEYWORDS}

    for entry in today_entries[:20]:
        board_name = entry.get("name", "")
        rank = entry.get("rank", 99)
        for our_sector, keywords in SECTOR_BOARD_KEYWORDS.items():
            for kw in keywords:
                if kw in board_name and rank < sector_scores[our_sector]["rank"]:
                    sector_scores[our_sector] = {
                        "rank": rank, "name": board_name,
                        "pct": entry.get("pct_chg", 0),
                        "net_inflow": entry.get("net_inflow", 0),
                    }
                    break

    result = {}
    for sector, info in sector_scores.items():
        if info["rank"] <= 3:
            result[sector] = (f"🔥HOT(资金流入排名{info['rank']}/{total_boards}, "
                              f"净流入{info['net_inflow']/1e8:.1f}亿)")
        elif info["rank"] <= 8:
            result[sector] = (f"⚡WARM(资金流入排名{info['rank']}/{total_boards})")
        elif info["rank"] <= 15:
            result[sector] = f"NEUTRAL(排名{info['rank']}/{total_boards})"
        else:
            result[sector] = ""

    return result



def compute_market_signal(overview: dict) -> str:
    """大方向闸门: 从大盘数据计算市场方向信号，注入PM上下文。
    解决"全Hold"极端保守问题 — 反弹日强制输出至少1-2个Buy。
    """
    indices = overview.get("indices", {})
    changes = []

    # 主路径: 三大指数pct_chg
    for name in ["上证指数", "深证成指", "创业板指"]:
        info = indices.get(name, {})
        pct = info.get("pct_chg", 0)
        close = info.get("close")
        if isinstance(pct, (int, float)) and abs(pct) < 20 and close is not None:
            changes.append((name, pct))

    if not changes:
        # 回落: 从市场情绪推断 (up/down ratio)
        sentiment_raw = overview.get("market_sentiment", "")
        try:
            if "up_count" in str(sentiment_raw):
                import re
                up = int(re.search(r"'up_count':\s*(\d+)", str(sentiment_raw)).group(1))
                down = int(re.search(r"'down_count':\s*(\d+)", str(sentiment_raw)).group(1))
                if up + down > 0:
                    ratio = up / (up + down)
                    if ratio > 0.65:
                        changes.append(("全市场(涨跌比)", 1.5))
                    elif ratio > 0.55:
                        changes.append(("全市场(涨跌比)", 0.5))
                    elif ratio < 0.35:
                        changes.append(("全市场(涨跌比)", -1.5))
                    elif ratio < 0.45:
                        changes.append(("全市场(涨跌比)", -0.5))
                    else:
                        changes.append(("全市场(涨跌比)", 0.0))
        except Exception:
            pass

    if not changes:
        return "市场方向: NEUTRAL (数据不可用)"

    avg_change = sum(c[1] for c in changes) / len(changes)
    idx_detail = ", ".join(f"{n}{pct:+.2f}%" for n, pct in changes)
    source_label = "涨跌比" if "涨跌比" in changes[0][0] else "三大指数平均涨"

    if avg_change > 1.5:
        signal = (f"市场方向: STRONG_BULL {idx_detail} "
                  f"({source_label}{avg_change:+.1f}%)\n"
                  f"【闸门指令】今日大盘强势反弹，明日大概率延续。"
                  f"本批次分析中，你**必须**输出至少 1-2 个 Buy 或 Overweight。"
                  f"选择 Bull 论据最充分、超跌反弹信号最明确的标的。不要全部 Hold。")
    elif avg_change > 0.5:
        signal = (f"市场方向: BULL {idx_detail} "
                  f"({source_label}{avg_change:+.1f}%)\n"
                  f"【闸门指令】今日大盘偏强，如果你发现 Bull 论据充分且 Bear 反驳薄弱的标的，"
                  f"应输出至少 1 个 Buy 或 Overweight。不要全部 Hold。")
    elif avg_change < -1.5:
        signal = (f"市场方向: STRONG_BEAR {idx_detail} "
                  f"({source_label}{avg_change:+.1f}%)\n"
                  f"【闸门指令】今日大盘暴跌，继续保守：最多输出 1 个 Buy，"
                  f"重点回避高位科技股。大部分应为 Hold。")
    elif avg_change < -0.5:
        signal = (f"市场方向: BEAR {idx_detail} "
                  f"({source_label}{avg_change:+.1f}%)\n"
                  f"【闸门指令】今日大盘偏弱，继续保守。But 对超跌反弹信号（Bull+Reversal一致）的标的仍可考虑 Buy。")
    else:
        signal = (f"市场方向: NEUTRAL {idx_detail} ({source_label}{avg_change:+.1f}%)\n"
                  f"【闸门指令】大盘窄幅震荡，正常模式。按你自身的判断做出有区分度的 Buy/Hold 决策，不要全部 Hold。")

    return signal


def _validate_data(stock_data, public_data):
    missing = []
    for key in CRITICAL_DATA:
        if _is_empty(stock_data.get(key)):
            missing.append(key)
    return missing


def main():
    parser = argparse.ArgumentParser(description="批量一日游预测")
    parser.add_argument("date", nargs="?", default="auto", help="分析日期 (YYYY-MM-DD), 默认今天")
    parser.add_argument("--fresh", action="store_true", help="强制重跑所有股票")
    parser.add_argument("--workers", type=int, default=5, help="并发数 (默认5)")
    parser.add_argument("--no-overview", action="store_true", help="跳过大盘预加载")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 只股票 (默认0=全部)")
    args = parser.parse_args()

    if args.date == "auto":
        from datetime import datetime
        from dataflows.akshare_adapter import _BJ_TIME
        trade_date = datetime.now(_BJ_TIME).strftime("%Y-%m-%d")
    else:
        trade_date = args.date

    next_date = get_next_trade_date(trade_date)

    config = get_config()
    agent_version = config.get("agent_version", "")
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1

    skipped = []
    todo = []
    # (round-15): --limit 支持只跑前 N 只股票 (按板块均匀分配, 避免单板块集中)
    if args.limit and args.limit > 0:
        # (round-15): 按板块均匀分配, 避免单板块集中
        by_sector = defaultdict(list)
        for code, name, sector in ALL_STOCKS:
            by_sector[sector].append((code, name, sector))
        per_sector = max(1, args.limit // len(by_sector))
        remaining = args.limit - per_sector * len(by_sector)
        stocks_to_run = []
        for sec, items in by_sector.items():
            stocks_to_run.extend(items[:per_sector])
        # 补齐余数到前几个板块
        if remaining > 0:
            for sec, items in by_sector.items():
                extra = items[per_sector:per_sector + remaining]
                stocks_to_run.extend(extra)
                remaining -= len(extra)
                if remaining <= 0:
                    break
    else:
        stocks_to_run = ALL_STOCKS

    for code, name, sector in stocks_to_run:
        if args.fresh:
            todo.append((code, name, sector))
        else:
            done, rating, pos_pct = is_done(code, trade_date, agent_version)
            if done:
                # (round-12, C-scripts-4): skipped 元组带上 position_pct（从 cache 读取）
                skipped.append((code, name, sector, rating, pos_pct))
            else:
                todo.append((code, name, sector))

    print("=" * 60)
    print(f"📅 交易日: {trade_date} → {next_date}")
    print(f"📊 总股票: {len(stocks_to_run)} | 跳过: {len(skipped)} | 待跑: {len(todo)} | 🔥 {args.workers} workers")
    print("=" * 60)

    if not todo:
        print("全部完成！")
        return

    shared_overview = ""
    data_bundles = {}
    skipped_data = []

    print("\n📊 Phase 0: 数据集中获取 ...")
    cache = MarketDataCache.get_instance()
    cache.set_trade_date(trade_date)

    # (round-11, C-scripts-3): --no-overview 只跳过大盘 overview，个股数据预取始终执行，
    # 避免 --no-overview 分支 data_bundles={} 导致 agent 多线程并发回源触发反爬
    if not args.no_overview:
        # 1. 大盘概览
        overview = load_overview(trade_date)
        shared_overview = overview_to_prompt(overview)
        idx_parts = []
        for k, v in overview.get('indices', {}).items():
            idx_parts.append(f"{k}({v.get('close', '?')})")
        print(f"   指数: {', '.join(idx_parts)}")

        # 1.5 市场方向信号 (大方向闸门)
        market_direction = compute_market_signal(overview)
        print(f"   {market_direction.split(chr(10))[0]}")

        # 1.6 板块动量加权
        sector_momentum = compute_sector_momentum()
        hot_sectors = [s for s, v in sector_momentum.items() if v and "HOT" in v]
        if hot_sectors:
            print(f"   板块动量: {', '.join(f'{s}({sector_momentum[s][:15]})' for s in hot_sectors)}")
        else:
            print(f"   板块动量: 数据不可用(晚间AKShare)")
    else:
        # H2: --no-overview 分支补默认值，避免 analyze_one 引用未定义变量导致 NameError
        shared_overview = ""
        market_direction = "市场方向: NEUTRAL (跳过预加载)"
        sector_momentum = {}
        print("   (跳过大盘 overview 预加载)")

    # 2. 公共数据 (市场情绪/北向/板块/资金流) — 始终执行
    print(f"   公共数据: 市场情绪 + 北向资金 + 板块排行 + 资金流 ...")
    public_data = _prefetch_public_data()

    # 3. 预加载个股价格到内存缓存 — 始终执行，避免多线程并发回源触发反爬
    symbols = [c for c, n, s in ALL_STOCKS]
    cache.preload_stock_data(symbols)
    cache.load_stock_price_history(symbols, days=30)

    # 4. 逐股拉取数据 + 完整性校验 (串行+节流，避免触发东财风控) — 始终执行
    print(f"   个股数据: 逐股拉取 (间隔≥{_THROTTLE_INTERVAL}s) + 完整性校验 ...")
    for code, name, sector in todo:
        stock_data = _gather_stock_data(code, name)
        missing = _validate_data(stock_data, public_data)
        if missing:
            skipped_data.append((code, name, sector, missing))
            continue
        data_bundles[code] = _build_data_context(stock_data, public_data, shared_overview)
        time.sleep(_THROTTLE_INTERVAL + random.uniform(0.1, 0.4))

    # 去重
    skipped_codes = {x[0] for x in skipped_data}
    todo = [(c, n, s) for c, n, s in todo if c not in skipped_codes]

    if skipped_data:
        print(f"\n⚠️  数据不完整，跳过 {len(skipped_data)} 只:")
        for code, name, sector, missing in skipped_data:
            print(f"   {code} {name} ({sector}) — 缺失: {', '.join(missing)}")

    print(f"\n✅ 数据就绪: {len(todo)} 只，即将开始辩论")
    print("=" * 60)

    if not todo:
        print("全部数据不完整，无股票可分析。")
        return

    # --- Phase 1: Concurrent Debate ---
    print("\n🚀 Phase 1: 并发辩论 ...\n")
    print_lock = Lock()
    # (round-10, M-scripts-2): 线程安全的已完成计数器，替代 idx 用于 ETA 计算
    completed_count = [0]  # 闭包计数器，线程安全用 completed_lock 保护
    completed_lock = Lock()
    results = []
    start_time = time.time()

    def analyze_one(code, name, sector, idx, total):
        t0 = time.time()
        # (round-12, H-scripts-1): 用 deepcopy 替代浅拷贝，避免嵌套 dict 跨线程共享
        cfg = copy.deepcopy(config)
        cfg["market_overview"] = shared_overview
        cfg["market_direction"] = market_direction
        cfg["sector_momentum"] = sector_momentum.get(sector, "")
        cfg["sector_context"] = SECTOR_DESCRIPTIONS.get(sector, "")
        cfg["data_context"] = data_bundles.get(code, "")
        try:
            agent = AStockTradingGraph(config=cfg)
            result = agent.analyze(symbol=code, trade_date=trade_date, stock_name=name)
            dt = time.time() - t0

            # H4 硬过滤：ST/流动性/跌停/停牌 — 双保险（trading_graph 内已过滤，此处再校验）
            rating = result.get("rating", "?")
            # (round-12, C-scripts-1): 记录原始评级，hard_filter 修改后需重新写回 cache
            original_rating = rating
            if rating in ("Buy", "Overweight"):
                try:
                    from agents.utils.agent_utils import hard_filter_stock
                    allowed, reason = hard_filter_stock(code, cfg)
                    if not allowed:
                        rating = "Hold"
                        result["rating"] = "Hold"
                        result["action"] = "Hold"
                        result["decision"] = (result.get("decision", "") or "") + \
                            f"\n\n**硬过滤**: {reason} → 强制 Hold"
                        with print_lock:
                            print(f"   ⚠️ 硬过滤拦截 {code} {name}: {reason} → Hold")
                except Exception as hf_err:
                    logging.warning(f"硬过滤执行失败 [{code}]: {hf_err}")

            # (round-12, C-scripts-1): hard_filter 修改 result 后必须重新写回 cache，
            # 否则下次 is_done 读到旧评级（如 Buy），hard_filter 完全失效
            if result.get("rating") != original_rating:
                try:
                    agent._save_result(result)
                except Exception as save_err:
                    logging.warning(f"重写 cache 失败 [{code}]: {save_err}")

            conf = result.get("confidence", 0)
            pos = result.get("position_pct")
            # (round-10, M-scripts-2): 用线程安全的已完成计数器替代 idx（idx 是任务 ID 非已完成数）
            with completed_lock:
                completed_count[0] += 1
                done = completed_count[0]
            with print_lock:
                elapsed = time.time() - start_time
                # (round-10, M-scripts-2): elapsed/done 已含并发因子，不再 /workers（修复 L-scripts-6 后期低估）
                eta = (elapsed / max(done, 1)) * (total - done) if done > 0 else 0
                pos_str = f" pos={pos:.0%}" if pos else ""
                print(f"[{idx:2d}/{total}] {code} {name} ({sector}) → {rating} ({conf:.0%}){pos_str} ⏱{dt:.0f}s | ETA {eta/60:.0f}min")
            return {"code": code, "name": name, "sector": sector,
                    "rating": rating, "conf": conf,
                    "position_pct": pos, "ok": True}
        except Exception as e:
            dt = time.time() - t0
            with print_lock:
                print(f"[{idx:2d}/{total}] {code} {name} ({sector}) → ❌ {str(e)[:80]} ⏱{dt:.0f}s")
            return {"code": code, "name": name, "sector": sector,
                    "rating": "ERR", "conf": 0, "position_pct": None, "ok": False}

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for i, (code, name, sector) in enumerate(todo):
            fut = executor.submit(analyze_one, code, name, sector, i + 1, len(todo))
            futures[fut] = (code, name, sector)
        for fut in as_completed(futures):
            results.append(fut.result())

    total_t = (time.time() - start_time) / 60
    ok_count = sum(1 for r in results if r["ok"])

    # --- Summary ---
    # (round-12, C-scripts-4): skipped 项带上 position_pct（从 cache 读取），参与归一化
    # (round-15, H-scripts-6): skipped 在异常路径下可能为 None（如 main 提前 return 后被外部调用），
    # 加 None 兜底避免后续列表推导抛 TypeError
    if skipped is None:
        skipped = []
    all_results = [{"code": c, "name": n, "sector": s, "rating": r, "conf": 0, "ok": True,
                    "position_pct": p} for c,n,s,r,p in skipped]
    all_results += [{"code": c, "name": n, "sector": s, "rating": "ERR", "conf": 0, "ok": False}
                    for c, n, s, _ in skipped_data]
    all_results += results
    by_rating = defaultdict(int)
    for r in all_results:
        by_rating[r["rating"]] += 1

    print("\n" + "=" * 60)
    print(f"📊 {trade_date} → {next_date} 预测 ({len(all_results)}只) | 耗时: {total_t:.1f}min | 成功: {ok_count}/{len(todo)}")
    if skipped_data:
        print(f"⚠️  数据跳过: {len(skipped_data)} 只")
    for rating in ["Buy", "Overweight", "Hold", "Underweight", "Sell", "ERR"]:
        if by_rating[rating]:
            emoji = {"Buy": "🟢", "Overweight": "🟡", "Hold": "⚪", "Underweight": "🟠", "Sell": "🔴", "ERR": "❌"}[rating]
            print(f"  {emoji} {rating}: {by_rating[rating]} 只")

    # 仓位归一化：Buy/Overweight 的 position_pct 等比压缩至总仓 ≤ 100%
    max_pos = config.get("max_position_pct", 0.2)
    # (round-12, C-scripts-4): 只对本次新跑的 results 补默认仓位，skipped 项用 cache 中的历史仓位
    for r in results:
        if r["rating"] in ("Buy", "Overweight") and r.get("position_pct") is None:
            r["position_pct"] = max_pos

    # (round-12, C-scripts-4): 归一化含 skipped Buy（恢复 all_results），避免总仓 > 100%
    buy_items = [r for r in all_results if r["rating"] in ("Buy", "Overweight") and r.get("position_pct")]
    total_raw = sum(r["position_pct"] for r in buy_items)
    if total_raw > 1.0:
        # 等比压缩
        scale = 1.0 / total_raw
        for r in buy_items:
            r["position_pct"] = round(r["position_pct"] * scale, 4)
        print(f"\n📐 仓位归一化: 原始总仓 {total_raw:.0%} > 100%，等比压缩至 100%")

    for rating in ["Buy", "Overweight", "Hold", "Underweight", "Sell", "ERR"]:
        if by_rating[rating]:
            items = [r for r in all_results if r["rating"] == rating]
            print(f"\n{rating}:")
            for r in items:
                pos_str = f" pos={r['position_pct']:.0%}" if r.get("position_pct") else ""
                print(f"  {r['code']} {r['name']} ({r['sector']}) conf={r['conf']:.0%}{pos_str}")


if __name__ == "__main__":
    main()
