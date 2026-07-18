"""
Agent 工具函数

提供给 LangGraph Agent 节点调用的工具函数集合。
函数通过 @tool 装饰器暴露给 LLM，或作为 ToolNode 使用。
"""

import logging
import re
# (round-9, L-core-6): 统一在顶部 import re，供 check_liquidity_risk / hard_filter_stock 使用
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

import pandas as pd

from .md_utils import to_markdown
# M1 修复：A股相关时间统一用北京时间（与 akshare_adapter.py H6 修复保持一致）
from dataflows.akshare_adapter import _BJ_TIME

logger = logging.getLogger(__name__)

# ============================================================
# 行情/技术数据工具
# ============================================================

def get_stock_price_data(symbol: str, days: int = 60) -> str:
    """
    获取A股历史价格数据

    Args:
        symbol: 股票代码，如 "600519" 或 "000001"
        days: 回溯天数（最大365）
    """
    # ———— 缓存优先 ————
    try:
        from dataflows.market_cache import MarketDataCache
        cache = MarketDataCache.get_instance()
        cached = cache.get_stock_data(symbol, "get_stock_price_data")
        if cached is not None:
            return cached
    except Exception:
        pass

    from dataflows.interface import route_to_vendor
    from config.default_config import get_config

    config = get_config()
    end_date = datetime.now(_BJ_TIME)
    start_date = end_date - timedelta(days=max(days, 30))

    df = route_to_vendor(
        "get_stock_daily", symbol,
        start_date=start_date.strftime("%Y%m%d"),
        end_date=end_date.strftime("%Y%m%d"),
        config=config,
    )

    if df is None or df.empty:
        try:
            from dataflows.akshare_adapter import get_stock_daily as _get_daily
            df = _get_daily(symbol, start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d"))
        except Exception:
            return f"无法获取 {symbol} 的行情数据"

    if df is None or df.empty:
        return f"{symbol} 无可用数据"

    recent = df.tail(days)
    last = recent.iloc[-1]
    first = recent.iloc[0]

    close = last.get("close", last.get("收盘", 0))
    change_pct = ((close / first.get("close", first.get("收盘", close)) - 1) * 100
                  if first.get("close", first.get("收盘", 0)) else 0)

    closes = [float(recent.iloc[i].get("close", recent.iloc[i].get("收盘", 0)))
              for i in range(len(recent))]
    ma5 = sum(closes[-5:]) / min(5, len(closes[-5:])) if closes else 0
    ma10 = sum(closes[-10:]) / min(10, len(closes[-10:])) if closes else 0
    ma20 = sum(closes[-20:]) / min(20, len(closes[-20:])) if closes else 0

    high = max(closes[-20:]) if len(closes) >= 20 else max(closes)
    low = min(closes[-20:]) if len(closes) >= 20 else min(closes)

    output = to_markdown({
        "symbol": symbol,
        "period": f"最近{days}个交易日",
        "latest_close": close,
        "change_pct": f"{change_pct:+.2f}%",
        "ma5": round(ma5, 2),
        "ma10": round(ma10, 2),
        "ma20": round(ma20, 2),
        "20d_high": round(high, 2),
        "20d_low": round(low, 2),
        "recent_5_days": [
            {
                "date": str(recent.iloc[-i]["date"] if "date" in recent.columns
                           else recent.index[-i])[:10],
                "close": closes[-i],
                "volume": float(recent.iloc[-i].get("volume", recent.iloc[-i].get("成交量", 0))),
            }
            for i in range(min(5, len(closes)), 0, -1)
        ],
    }, title=f"行情数据 — {symbol}")

    # ———— 写入缓存 ————
    try:
        from dataflows.market_cache import MarketDataCache
        cache = MarketDataCache.get_instance()
        cache.set_stock_data(symbol, "get_stock_price_data", output)
    except Exception:
        pass

    return output


def get_stock_realtime_quote(symbol: str) -> str:
    """获取A股实时行情"""
    # ———— 缓存优先 ————
    try:
        from dataflows.market_cache import MarketDataCache
        cache = MarketDataCache.get_instance()
        cached = cache.get_stock_data(symbol, "get_stock_realtime_quote")
        if cached is not None:
            return cached
    except Exception:
        pass

    from dataflows.interface import route_to_vendor

    data = route_to_vendor("get_stock_realtime", symbol)
    if data is None:
        return f"无法获取 {symbol} 实时行情"

    output = to_markdown(data, title=f"实时行情 — {symbol}")

    # ———— 写入缓存 ————
    # C8 修复：盘中实时价不是收盘数据，不能写入磁盘缓存（否则会污染收盘数据，
    # 导致后续运行读取到盘中快照而永远不会刷新为真正的收盘数据）。
    # 盘中只更新内存缓存（当前会话内可复用），收盘后才写磁盘持久化。
    try:
        from dataflows.market_cache import MarketDataCache
        from dataflows.akshare_adapter import is_market_closed
        cache = MarketDataCache.get_instance()
        # 盘中时段：只写内存，不写磁盘
        cache.set_stock_data(
            symbol, "get_stock_realtime_quote", output,
            skip_disk=not is_market_closed(),
        )
    except Exception:
        pass

    return output


# ============================================================
# 财务数据工具
# ============================================================

def get_stock_financials(symbol: str) -> str:
    """
    获取A股财务指标摘要

    Args:
        symbol: 股票代码
    """
    # ———— 缓存优先 ————
    try:
        from dataflows.market_cache import MarketDataCache
        cache = MarketDataCache.get_instance()
        cached = cache.get_stock_data(symbol, "get_stock_financials")
        if cached is not None:
            return cached
    except Exception:
        pass

    from dataflows.interface import route_to_vendor

    indicators = route_to_vendor("get_financial_indicators", symbol)

    if indicators is None or (hasattr(indicators, 'empty') and indicators.empty):
        return f"无法获取 {symbol} 的财务数据"

    try:
        if hasattr(indicators, 'to_dict'):
            if '报告期' in indicators.columns:
                indicators = indicators.sort_values('报告期', ascending=False)
            recent = indicators.head(4)
            output = to_markdown(recent, title=f"财务指标 — {symbol}")
        else:
            output = str(indicators)

        # ———— 写入缓存 ————
        try:
            from dataflows.market_cache import MarketDataCache
            cache = MarketDataCache.get_instance()
            cache.set_stock_data(symbol, "get_stock_financials", output)
        except Exception:
            pass

        return output
    except Exception as e:
        return f"财务数据解析失败: {e}"


# ============================================================
# 市场情绪工具
# ============================================================

def get_market_sentiment_data() -> str:
    """获取A股整体市场情绪（含近期趋势）"""
    from dataflows.interface import route_to_vendor
    from dataflows.market_cache import MarketDataCache

    data = route_to_vendor("get_market_sentiment")
    if data is None:
        return "无法获取市场情绪数据"

    # 附上近期历史趋势
    parts = [to_markdown(data, title="今日市场情绪")]
    try:
        cache = MarketDataCache.get_instance()
        history = cache.get_history("get_market_sentiment", days=10)
        if len(history) > 1:
            parts.append("\n## 近期趋势（上证指数）")
            parts.append(to_markdown([h["data"] for h in history], title=""))
    except Exception:
        pass

    return "\n\n".join(parts)


def get_north_flow_data(days: int = 10) -> str:
    """获取北向资金流向"""
    from dataflows.interface import route_to_vendor

    data = route_to_vendor("get_north_flow", days=days)
    if data is None:
        return "无法获取北向资金数据"

    if isinstance(data, list):
        return to_markdown(data[-days:], title="北向资金流向")
    if data.empty:
        return "无法获取北向资金数据"
    return to_markdown(data.tail(days), title="北向资金流向")


# ============================================================
# 板块数据工具
# ============================================================

def get_sector_data() -> str:
    """获取行业板块行情（含近期趋势摘要）"""
    from dataflows.interface import route_to_vendor
    from dataflows.market_cache import MarketDataCache

    data = route_to_vendor("get_sector_boards")
    if data is None:
        return "无法获取板块数据"

    if isinstance(data, list):
        # 从缓存恢复的 list[dict]，直接排序截取
        sorted_data = sorted(data, key=lambda r: r.get("涨跌幅", 0), reverse=True)
        top_bottom = sorted_data[:10] + sorted_data[-10:]
    else:
        if data.empty:
            return "无法获取板块数据"
        if "涨跌幅" in data.columns:
            sorted_df = data.sort_values("涨跌幅", ascending=False)
            top_bottom_df = pd.concat([sorted_df.head(10), sorted_df.tail(10)])
            top_bottom = top_bottom_df.to_dict(orient="records")
        else:
            top_bottom = data.head(15).to_dict(orient="records")

    parts = [to_markdown(top_bottom, title="行业板块行情")]

    # 附上近期历史趋势摘要
    try:
        cache = MarketDataCache.get_instance()
        history = cache.get_history("get_sector_boards", days=10)
        if len(history) > 1:
            trend_rows = []
            for item in history:
                d = item["data"]
                date = item["date"]
                rising = sum(1 for r in d if isinstance(r, dict) and r.get("涨跌幅", 0) > 0)
                falling = sum(1 for r in d if isinstance(r, dict) and r.get("涨跌幅", 0) < 0)
                total = max(rising + falling, 1)
                trend_rows.append({
                    "日期": date,
                    "上涨板块": rising,
                    "下跌板块": falling,
                    "上涨比例": f"{rising/total*100:.0f}%",
                })
            parts.append("\n## 近期板块涨跌结构")
            parts.append(to_markdown(trend_rows, title=""))
    except Exception:
        pass

    return "\n\n".join(parts)


def get_sector_fund_flow_data(days: int = 3) -> str:
    """获取板块资金流排名 (今日/5日/10日)。

    用于识别主力资金在板块间的流向，辅助判断板块强弱。
    缓存放 MarketDataCache (内存+磁盘双层)。

    Args:
        days: 拉取天数 (3=今日/5日/10日三个维度)

    Returns:
        Markdown 格式的板块资金流报告
    """
    # (round-11, M-core-2): 用 trade_date 而非 date.today()，与 get_global_macro_data 一致
    from dataflows.market_cache import MarketDataCache
    from dataflows.akshare_adapter import _BJ_TIME
    from datetime import datetime
    try:
        trade_date = MarketDataCache.get_instance().get_trade_date()
    except Exception as e:
        logger.debug(f"获取 trade_date 失败: {e}")
        trade_date = ""
    if not trade_date:
        trade_date = datetime.now(_BJ_TIME).strftime("%Y-%m-%d")
    cache_key = f"sector_fund_flow_{trade_date}"

    try:
        from dataflows.market_cache import MarketDataCache
        cache = MarketDataCache.get_instance()
        cached = cache.get_public_data(cache_key)
        if cached:
            return cached
    except Exception:
        pass

    from dataflows.interface import route_to_vendor
    data = route_to_vendor("get_sector_fund_flow", config={}, days=days)
    if not data:
        return "板块资金流数据获取失败"

    lines = ["## 板块资金流排名\n"]
    period_names = {"today": "今日", "5_day": "5日", "10_day": "10日"}
    for key, label in period_names.items():
        entries = data.get(key, [])
        if not entries:
            continue
        lines.append(f"### {label}\n")
        lines.append("| 板块 | 涨跌幅 | 主力净流入(亿) | 净占比 |")
        lines.append("|------|--------|---------------|--------|")
        for e in entries[:10]:
            inflow = e.get("net_inflow", 0)
            pct = e.get("pct_chg", 0)
            ratio = e.get("net_ratio", 0)
            lines.append(
                "| {} | {:+.2f}% | {:+.2f} | {:.2f}% |".format(
                    e.get("name", ""), pct, inflow / 1e8, ratio
                )
            )
        lines.append("")

    # Add portfolio-sector mapping
    sector_map = {
        "光伏设备": "光伏", "风电设备": "风电", "电源设备": "风电",
        "计算机设备": "AI", "半导体": "AI", "软件开发": "AI", "IT服务": "AI",
        "电池": "储能", "能源金属": "储能", "电力行业": "储能",
        "光学光电子": "视觉", "电子元件": "视觉", "汽车零部件": "视觉",
    }
    lines.append("### 与持仓板块的映射\n")
    found_any = False
    for key in period_names.keys():
        entries = data.get(key, [])
        for e in entries:
            mapped = sector_map.get(e.get("name", ""), "")
            if mapped:
                lines.append(
                    "- {} → **{}** ({}: 涨{:+.2f}% 净流入{:+.2f}亿)".format(
                        e.get("name", ""), mapped, key,
                        e.get("pct_chg", 0), e.get("net_inflow", 0) / 1e8
                    )
                )
                found_any = True
    if not found_any:
        lines.append("(未匹配到持仓板块)\n")

    result = "\n".join(lines)
    try:
        from dataflows.market_cache import MarketDataCache
        cache = MarketDataCache.get_instance()
        cache.store_public_data(cache_key, result)
    except Exception:
        pass
    return result


# ============================================================
# 舆论监控工具（基于Agent-Reach）
# ============================================================

def get_opinion_report(symbol: str, stock_name: str = "") -> str:
    """
    获取个股舆论情绪报告

    整合雪球帖子、财经新闻等多源数据。
    个股舆情结果按 (symbol, trade_date) 缓存到磁盘，同交易日不重复拉取。

    Args:
        symbol: A股代码
        stock_name: 股票名称（可选）
    """
    # H7 修复：尊重 enable_opinion_monitor 配置项（main.py --no-opinion 会置为 False）
    # H-core-1 (round-9): 返回明确禁用提示字符串，避免 ToolNode 将 None 转为 "None" 字符串
    # 导致 LLM 误判舆情监控仍可用并反复调用
    from config.default_config import get_config
    if not get_config().get("enable_opinion_monitor", True):
        return "舆情监控已禁用（配置 enable_opinion_monitor=False），跳过舆论数据采集。"
    # ———— 缓存优先 ————
    try:
        from dataflows.market_cache import MarketDataCache
        cache = MarketDataCache.get_instance()
        cached = cache.get_opinion(symbol, "get_opinion_report")
        if cached is not None:
            return cached
    except Exception:
        pass

    try:
        from opinion.sentiment_aggregator import aggregate_sentiment
        from config.default_config import get_config

        config = get_config()
        result = aggregate_sentiment(symbol, stock_name, config)
        report = result.get("summary", "无法获取舆论数据")

        # H16 修复：追加 sources 分项数据（各源 count/score）和 risk_signals（不再丢弃结构化数据）
        sources = result.get("sources", {}) or {}
        if sources:
            report += "\n\n### 各源详情"
            for src_name, src_data in sources.items():
                if not src_data:
                    continue
                if isinstance(src_data, dict):
                    detail_parts = []
                    # count 字段（news/weibo 等可能提供）
                    count = src_data.get("count")
                    if count is not None:
                        detail_parts.append(f"count={count}")
                    # 情绪倾向（xueqiu 提供 sentiment_hint）
                    hint = src_data.get("sentiment_hint")
                    if hint:
                        detail_parts.append(f"情绪={hint}")
                    # 帖子数（xueqiu 的 hot_posts/search_posts）
                    hot_posts = src_data.get("hot_posts")
                    if isinstance(hot_posts, list):
                        detail_parts.append(f"热帖={len(hot_posts)}")
                    search_posts = src_data.get("search_posts")
                    if isinstance(search_posts, list):
                        detail_parts.append(f"搜索帖={len(search_posts)}")
                    # 行情（xueqiu quote）
                    quote = src_data.get("quote")
                    if isinstance(quote, dict) and quote:
                        pct = quote.get("percent")
                        if pct is not None:
                            detail_parts.append(f"涨跌={pct:+.2f}%")
                    # 错误标记
                    if src_data.get("error"):
                        detail_parts.append(f"error={src_data['error']}")
                    detail = ", ".join(detail_parts) if detail_parts else "已获取"
                    report += f"\n- {src_name.upper()}: {detail}"

        risk_signals = result.get("risk_signals", []) or []
        if risk_signals:
            report += "\n\n### ⚠️ 风险信号"
            for sig in risk_signals:
                report += f"\n- {sig}"

        # ———— 写入缓存 ————
        try:
            from dataflows.market_cache import MarketDataCache
            cache = MarketDataCache.get_instance()
            cache.set_opinion(symbol, "get_opinion_report", report)
        except Exception:
            pass

        return report
    except Exception as e:
        logger.error(f"舆论报告生成失败 [{symbol}]: {e}")
        # Fallback: 直接使用雪球
        try:
            from opinion.xueqiu_monitor import build_opinion_summary
            xq_sym = _to_xq(symbol)
            data = build_opinion_summary(xq_sym, stock_name)
            return data.get("summary", "无法获取雪球数据")
        except Exception as e2:
            return f"舆论数据获取失败: {e} / {e2}"


def get_xueqiu_hot_posts_for_symbol(symbol: str, limit: int = 10) -> str:
    """获取个股相关雪球帖子（按个股缓存，同交易日不重复拉取）"""
    # ———— 缓存优先 ————
    try:
        from dataflows.market_cache import MarketDataCache
        cache = MarketDataCache.get_instance()
        cached = cache.get_opinion(symbol, "get_xueqiu_hot_posts")
        if cached is not None:
            return cached
    except Exception:
        pass

    try:
        from opinion.xueqiu_monitor import build_opinion_summary
        xq_sym = _to_xq(symbol)
        data = build_opinion_summary(xq_sym, limit=limit)
        posts = data.get("hot_posts", []) + data.get("search_posts", [])
        result = []
        for p in posts[:limit]:
            result.append({
                "title": p.get("title", "")[:80],
                "text": (p.get("text", "") or "")[:150],
                "likes": p.get("likes", 0),
            })
        output = to_markdown(result, title=f"雪球帖子 — {symbol}")

        # ———— 写入缓存 ————
        try:
            from dataflows.market_cache import MarketDataCache
            cache = MarketDataCache.get_instance()
            cache.set_opinion(symbol, "get_xueqiu_hot_posts", output)
        except Exception:
            pass

        return output
    except Exception as e:
        return f"雪球帖子获取失败: {e}"


def _to_xq(symbol: str) -> str:
    """转换A股代码为雪球格式"""
    symbol = symbol.strip().zfill(6)
    if symbol.startswith(("6", "5")):
        return f"SH{symbol}"
    elif symbol.startswith(("0", "3", "2")):
        return f"SZ{symbol}"
    return f"SH{symbol}"


# ============================================================
# 流动性/风险检查工具 (一日游策略专用)
# ============================================================

def check_liquidity_risk(symbol: str, stock_name: str = "") -> str:
    """
    检查股票的一日游流动性风险（跌停/停牌/成交额/ST）。

    一日游策略硬约束：Day 2 必须能卖出。如果跌停或停牌，策略失效。

    Args:
        symbol: 股票代码
        stock_name: 股票名称（可选）
    """
    lines = [f"# 流动性风险检查 — {stock_name or symbol} ({symbol})", ""]

    try:
        quote_data = get_stock_realtime_quote(symbol)
        price_data = get_stock_price_data(symbol, days=10)
    except Exception as e:
        lines.append(f"> ❌ 无法获取数据，无法评估流动性: {e}")
        lines.append(f"> ⚠️ 保守建议: 回避该股，流动性不可知是最坏情况")
        return "\n".join(lines)

    # (round-9, L-core-6): 删除局部 import re，改用顶部统一 import

    # 1. ST 检查 — 通过股票名称中的 *ST/ST 标记检测（比代码前缀更可靠）
    name_lower = stock_name.lower() if stock_name else ""
    # 使用词边界避免误匹配 "BEST"/"POST" 等含 ST 子串的单词；中文名用 startswith 更精确
    st_match = bool(re.search(r'(\*ST|\bST\b)', quote_data)) or bool(re.search(r'(\*ST|\bST\b)', price_data))
    # (round-11, H-core-2): 统一 ST 判定，避免风险章节和结论章节不一致
    # 去掉 startswith('st ') 的尾部空格要求，匹配中文 ST 名如 "ST天宝"
    is_st = st_match or name_lower.startswith('*st') or name_lower.startswith('st')
    if is_st:
        lines.append("### 1. ST/退市风险")
        lines.append("> 🔴 **该股为 ST 股票，涨跌停仅 5%，流动性极差，一日游策略严禁参与！**")
        lines.append("> 建议: **强制回避**")
    else:
        lines.append("### 1. ST/退市风险")
        lines.append("> ✅ 非 ST 股票")

    # 2. 停牌检查
    lines.append("")
    lines.append("### 2. 停牌风险")
    if "停牌" in quote_data or "停牌" in price_data:
        lines.append("> 🔴 **检测到停牌信息，该股当前可能处于停牌状态！**")
    else:
        lines.append("> ✅ 未检测到停牌信号（注意：停牌通常在下一个交易日才会公告）")

    # 3. 跌停风险（近期是否跌停）
    lines.append("")
    lines.append("### 3. 近期跌停检查")
    limit_down = bool(re.search(r'跌停', quote_data)) or bool(re.search(r'跌停', price_data))
    if limit_down:
        lines.append("> 🔴 **近期有跌停记录！Day 2 跌停将导致无法卖出**")
    else:
        lines.append("> ✅ 近期未检测到跌停")

    # 4. 成交额检查
    lines.append("")
    lines.append("### 4. 成交额流动性")
    amount_patterns = [
        r'成交[额量][：:]\s*([\d.,]+[亿万])',
        r'成交[额量]\s*([\d.,]+[亿万])',
    ]
    found_amount = None
    for pat in amount_patterns:
        m = re.search(pat, quote_data)
        if m:
            found_amount = m.group(1)
            break
    if found_amount:
        lines.append(f"> 最新成交额: {found_amount}")
    lines.append("> 一日游策略要求: 日成交额 ≥ 1 亿元（否则大单卖出可能砸盘或无法成交）")

    lines.append("")
    lines.append("### 结论")
    # (round-11, H-core-2): 结论章节与风险章节使用统一的 is_st 判定
    if is_st:
        lines.append("> 🔴 **坚决回避** — ST 股票不符合一日游策略条件")
    elif limit_down:
        lines.append("> 🟠 **建议观望** — 有跌停记录，Day 2 可能无法顺利卖出")
    else:
        lines.append("> 🟡 **需结合其他分析判断** — 无硬性排除条件")

    return "\n".join(lines)


def hard_filter_stock(symbol: str, config: dict = None) -> tuple:
    """
    硬过滤：ST / 流动性 / 跌停 / 停牌

    结构化字段判断（非 Markdown 正则），用于在 PM 决策后强制拦截 Buy/Overweight。
    数据获取失败时不阻塞（返回 allowed=True）。

    Args:
        symbol: 股票代码
        config: 配置 dict（读取 one_day_swing 子配置）

    Returns:
        (allowed: bool, reason: str)
        - (True, "") 通过
        - (False, "reason") 拒绝
        - 数据获取失败 → (True, "数据不可用，跳过硬过滤")
    """
    if config is None:
        from config.default_config import get_config
        config = get_config()

    swing_cfg = config.get("one_day_swing", {})
    ban_st = swing_cfg.get("ban_st_stocks", True)
    min_amount_yuan = swing_cfg.get("min_daily_amount_yuan", 1e8)

    # 获取结构化实时行情 — 优先腾讯接口（含 limit_up/limit_down/amount_wan）
    data = None
    try:
        from dataflows.direct_http import tencent_realtime
        tx = tencent_realtime(symbol)
        # 有 name 即视为有效响应（停牌股 price 可能为 0，但 name 一定有值）
        if tx and tx.get("name"):
            data = tx
    except Exception as e:
        logger.debug(f"tencent_realtime 失败 [{symbol}]: {e}")

    # 回退到 route_to_vendor → akshare_adapter.get_stock_realtime
    # 该链路第一条回退是 eastmoney_realtime，会返回 limit_up/limit_down；
    # 故需透传（新浪回退时为 None，由下方 limit_down==0 跳过跌停检查）
    if not data:
        try:
            from dataflows.interface import route_to_vendor
            rt = route_to_vendor("get_stock_realtime", symbol)
            if rt and rt.get("name"):
                amount = float(rt.get("amount", 0) or 0)
                volume = rt.get("volume", 0)
                # rt["amount"] 已是元，转回 amount_wan 与腾讯路径一致
                data = {
                    "name": rt.get("name", ""),
                    "price": rt.get("price", 0),
                    "volume": volume,
                    "amount_wan": amount / 10000,
                    # H5: 透传 limit_up/limit_down，跌停保护生效依赖此字段
                    "limit_up": rt.get("limit_up"),
                    "limit_down": rt.get("limit_down"),
                }
        except Exception as e:
            logger.debug(f"route_to_vendor get_stock_realtime 失败 [{symbol}]: {e}")

    if not data:
        return (True, "数据不可用，跳过硬过滤")

    # 数值安全提取
    try:
        price = float(data.get("price", 0) or 0)
    except (ValueError, TypeError):
        price = 0.0
    try:
        amount_wan = float(data.get("amount_wan", 0) or 0)
    except (ValueError, TypeError):
        amount_wan = 0.0
    try:
        ld_raw = data.get("limit_down")
        limit_down = float(ld_raw) if ld_raw is not None else 0.0
    except (ValueError, TypeError):
        limit_down = 0.0

    # a. ST 检测 — 结构化 name 字段
    if ban_st:
        name = str(data.get("name", "") or "")
        # (round-9, L-core-2): 与 check_liquidity_risk 统一用 re.search 词边界匹配，
        # 避免误匹配 "BEST"/"POST" 等含 ST 子串的单词
        if re.search(r'(\*ST|\bST\b)', name):
            return (False, f"ST股票: {name}")

    # b. 停牌 — volume == 0（无 volume 字段时用 amount_wan == 0 作为代理）
    volume = data.get("volume", None)
    if volume is not None:
        try:
            if float(volume) == 0:
                return (False, "停牌: volume=0")
        except (ValueError, TypeError):
            pass
    elif amount_wan == 0:
        return (False, "停牌: 成交额为0")

    # c. 跌停 — price == limit_down（均 > 0）
    # A股最小变动0.01元，0.001容差等价于严格相等（避免浮点精度问题）
    if price > 0 and limit_down > 0 and abs(price - limit_down) < 0.001:
        return (False, f"跌停: price={price} limit_down={limit_down}")

    # d. 流动性 — amount_wan (万元) vs min_daily_amount_yuan (元)
    amount_yuan = amount_wan * 10000
    if amount_yuan < min_amount_yuan:
        return (False, f"流动性不足: 成交额{amount_wan:.0f}万元 < 阈值{min_amount_yuan/1e4:.0f}万元")

    return (True, "")


# ============================================================
# 工具函数映射
# ============================================================

# Agent 可调用的工具列表
MARKET_TOOLS = [
    get_stock_price_data,
    get_stock_realtime_quote,
    get_market_sentiment_data,
    get_sector_data,
    get_north_flow_data,
    get_sector_fund_flow_data,
    check_liquidity_risk,
]

FUNDAMENTAL_TOOLS = [
    get_stock_financials,
    get_stock_realtime_quote,
]

SENTIMENT_TOOLS = [
    get_opinion_report,
    get_xueqiu_hot_posts_for_symbol,
    get_market_sentiment_data,
]

POLICY_TOOLS = [
    get_sector_data,
    get_north_flow_data,
    get_market_sentiment_data,
    get_sector_fund_flow_data,
]


# ============================================================
# 全球宏观数据工具
# ============================================================

def get_global_macro_data() -> str:
    """获取全球资本市场关键指标，用于评估隔夜外盘对次日A股的影响。

    返回结构化的Markdown报告，包含:
    - 美股三大指数 (标普500/纳斯达克/道琼斯)
    - 恒生指数
    - A50期货 (新加坡)
    - VIX恐慌指数
    - 美元/离岸人民币 (USDCNH)
    - 原油/铜期货

    三级回退策略（M3 修正：实际为二级回退——主接口 + 降级标注）:
      1. AKShare 主接口（新浪/东方财富等）
      2. 降级标注（明确告知数据不可用，让分析师自行评估）

    注: 大多数指标仅有 1 个数据源（AKShare），无备用接口；
    数据不可用时以降级标注形式返回，不构成独立的"第三级"。
    """
    lines = []
    lines.append("# 全球宏观数据")
    lines.append(f"生成时间: {datetime.now(_BJ_TIME).strftime('%Y-%m-%d %H:%M')} (北京时间)")
    lines.append("")

    # --- 缓存键 ---
    cache = None
    try:
        from dataflows.market_cache import MarketDataCache
        cache = MarketDataCache.get_instance()
        trade_date = cache.get_trade_date()
    except Exception as e:
        logger.debug(f"获取 trade_date 失败: {e}")
        trade_date = ""

    # trade_date 为空时回退到最近交易日（与 batchanalyze/trading_graph 保持一致，避免跨路径不一致）
    if not trade_date:
        try:
            from dataflows.akshare_adapter import get_latest_trade_date
            trade_date = get_latest_trade_date()
        except Exception as e:
            logger.debug(f"get_latest_trade_date 失败，回退到当前自然日期: {e}")
            trade_date = datetime.now(_BJ_TIME).strftime("%Y-%m-%d")

    cache_key = f"global_macro_{trade_date}"
    if cache is not None:
        try:
            cached = cache.get_public_data(cache_key)
            if cached:
                return cached
        except Exception as e:
            logger.debug(f"读取 global_macro 缓存失败: {e}")

    # ============================================================
    # M6: 美股时区对齐 — 美东时间 9:30-16:00 = 北京时间 21:30-04:00 (夏令时) / 22:30-05:00 (冬令时)
    # 判断美股最近交易日的状态：盘中(数据未完成)、收盘(数据已更新)、盘前(使用前一日数据)
    # ============================================================
    us_session_info = _detect_us_session()
    if us_session_info["status"] == "in_session":
        lines.append(f"⏰ 美股交易中（{us_session_info['note']}），数据为实时盘中价，可能与收盘价有偏差")
    elif us_session_info["status"] == "pre_market":
        lines.append(f"⏰ 美股盘前（{us_session_info['note']}），最近交易日数据应为前一日收盘，今日数据未生成")
    else:
        lines.append(f"⏰ 美股已收盘（{us_session_info['note']}），最近交易日数据应为今日（美东时间）收盘")

    try:
        import akshare as ak
    except ImportError:
        ak = None

    # ============================================================
    # 1. 美股三大指数 (新浪接口)
    #    M7: 主接口 index_us_stock_sina → 备用 stock_us_daily → 降级标注
    # ============================================================
    lines.append("")
    lines.append("## 美股三大指数 (最近交易日)")
    us_indices = {
        ".INX": "标普500",
        ".IXIC": "纳斯达克",
        ".DJI": "道琼斯",
    }
    for code, name in us_indices.items():
        result = _fetch_us_index(ak, code, name)
        if result:
            lines.append(result)
        else:
            lines.append(f"- {name}: 数据不可用（接口失败）")

    # ============================================================
    # 2. 恒生指数 (主: stock_hk_index_daily_em / 备: stock_hk_index_daily_sina)
    # ============================================================
    lines.append("")
    lines.append("## 恒生指数")
    hk_result = _fetch_hk_index(ak)
    if hk_result:
        lines.append(hk_result)
    else:
        lines.append("- 恒生指数: 数据不可用(非交易时间或接口失败)")

    # ============================================================
    # 3. A50期货 (主: futures_foreign_hist / 备: futures_foreign_commodity_realtime)
    # ============================================================
    lines.append("")
    lines.append("## A50期货 (新加坡)")
    a50_result = _fetch_a50(ak)
    if a50_result:
        lines.append(a50_result)
    else:
        lines.append("- A50期货: 数据不可用(非交易时间或接口失败)")

    # ============================================================
    # 4. 美元/人民币 (USDCNH)
    # ============================================================
    lines.append("")
    lines.append("## 美元/离岸人民币 (USDCNH)")
    fx_result = _fetch_usdcnh(ak)
    if fx_result:
        lines.append(fx_result)
    else:
        lines.append("- USDCNH: 数据不可用")

    # ============================================================
    # 5. VIX 恐慌指数 (主: index_us_stock_sina / 备: cnn fear_greed)
    # ============================================================
    lines.append("")
    lines.append("## VIX 恐慌指数")
    vix_result = _fetch_vix(ak)
    if vix_result:
        lines.append(vix_result)
    else:
        lines.append("- VIX: 数据不可用")

    # ============================================================
    # 6. 原油/铜期货
    # ============================================================
    lines.append("")
    lines.append("## 关键商品")
    commodity_map = {"CL": "WTI原油", "HG": "铜"}
    for code, name in commodity_map.items():
        comm_result = _fetch_commodity(ak, code, name)
        if comm_result:
            lines.append(comm_result)
        else:
            lines.append(f"- {name}: 数据不可用")

    result = "\n".join(lines)

    # --- 缓存（H6: 美股盘中不缓存，避免收盘后仍返回盘中快照）---
    # 之前 M10 修复盘中仅写内存，但 get_public_data 读取时优先返回内存，
    # 导致同一 A 股交易日内美股从盘中转为收盘后，仍命中内存中的盘中快照。
    # 正确做法：盘中不写任何缓存，每次调用都重新拉取；收盘后才写内存+磁盘。
    try:
        us_status = _detect_us_session().get("status", "closed")
        if us_status != "in_session":
            cache.store_public_data(cache_key, result)
        # 盘中（in_session）不写任何缓存，下次调用会重新拉取
    except Exception:
        pass

    return result


def _detect_us_session() -> dict:
    """检测美股交易时段状态

    美东时间 9:30-16:00 = 北京时间 21:30-04:00 (夏令时, 3月第二周日-11月第一周日)
                        = 北京时间 22:30-05:00 (冬令时)

    M9: 使用 zoneinfo 精确判断夏令时（替代月份近似，消除过渡期最多14天偏差）

    Returns:
        {"status": "in_session" | "pre_market" | "closed", "note": str}
    """
    try:
        # Python 3.9+ 自带 zoneinfo
        from zoneinfo import ZoneInfo
        us_now = datetime.now(ZoneInfo("America/New_York"))
        # (round-10, L-core-1): dst() 对 aware datetime 恒返回 timedelta（永不返回 None），
        # 原 `is not None` 写法恒为 True；改用 bool() 判断是否处于夏令时。
        is_dst = bool(us_now.dst())
        us_hour = us_now.hour
        us_minute = us_now.minute
    except Exception:
        # 回退到月份近似（zoneinfo 不可用时）
        # (round-9, M-core-1): 用 _BJ_TIME 取北京时间，避免 UTC 服务器上
        # datetime.now() 返回本地时间导致美东时间推算偏差 8 小时
        now_bj = datetime.now(_BJ_TIME)
        is_dst = 3 <= now_bj.month <= 11
        # 简化：假设美东时间 = 北京时间 -12（夏令时）或 -13（冬令时）
        offset_hours = 12 if is_dst else 13
        us_total_min = (now_bj.hour - offset_hours) * 60 + now_bj.minute
        us_hour = (us_total_min // 60) % 24
        us_minute = us_total_min % 60

    # 美东时间 9:30-16:00 为盘中
    in_session = (us_hour > 9 or (us_hour == 9 and us_minute >= 30)) and us_hour < 16

    if in_session:
        return {"status": "in_session", "note": "夏令时盘中" if is_dst else "冬令时盘中"}
    elif us_hour < 9 or (us_hour == 9 and us_minute < 30):
        return {"status": "pre_market", "note": "夏令时盘前" if is_dst else "冬令时盘前"}
    else:
        return {"status": "closed", "note": "夏令时收盘后" if is_dst else "冬令时收盘后"}


def _fetch_us_index(ak, code: str, name: str) -> Optional[str]:
    """美股指数：主 index_us_stock_sina → 备 stock_us_daily"""
    if ak is None:
        return None
    # 主接口
    try:
        df = ak.index_us_stock_sina(symbol=code)
        if df is not None and not df.empty:
            df.columns = df.columns.str.lower()
            last = df.iloc[-1]
            close = float(last.get("close", 0) or 0)
            change_pct = float(last.get("pct_chg", 0) or 0)
            date_val = last.get("date", "")
            date_str = str(date_val)[:10] if date_val else "?"
            emoji = "↑" if change_pct > 0 else ("↓" if change_pct < 0 else "→")
            return f"- {name}: {close:,.0f} {emoji}{change_pct:+.2f}% (截至 {date_str})"
    except Exception as e:
        logger.debug(f"index_us_stock_sina 失败 [{code}]: {e}")
    # 备用接口
    try:
        # stock_us_daily 用美股代码（不带点）：.INX → INX
        sym = code.lstrip(".")
        df = ak.stock_us_daily(symbol=sym, adjust="qfq")
        if df is not None and not df.empty:
            last = df.iloc[-1]
            close = float(last.get("close", 0) or 0)
            date_str = str(last.name)[:10] if hasattr(last, "name") else "?"
            return f"- {name}: {close:,.0f} (截至 {date_str}, 备用源)"
    except Exception as e:
        logger.debug(f"stock_us_daily 失败 [{code}]: {e}")
    return None


def _fetch_hk_index(ak) -> Optional[str]:
    """恒生指数：主 stock_hk_index_daily_em → 备 stock_hk_index_daily_sina"""
    if ak is None:
        return None
    try:
        hk_df = ak.stock_hk_index_daily_em(symbol="HSI")
        if hk_df is not None and not hk_df.empty:
            last = hk_df.iloc[-1]
            close = float(last.get("close", 0) or 0)
            pct = float(last.get("pct_chg", 0) or 0)
            date_str = str(last.get("date", ""))[:10] if "date" in last else "?"
            emoji = "↑" if pct > 0 else ("↓" if pct < 0 else "→")
            return f"- 恒生指数: {close:,.0f} {emoji}{pct:+.2f}% (截至 {date_str})"
    except Exception as e:
        logger.debug(f"stock_hk_index_daily_em 失败: {e}")
    try:
        hk_df = ak.stock_hk_index_daily_sina(symbol="HSI")
        if hk_df is not None and not hk_df.empty:
            last = hk_df.iloc[-1]
            close = float(last.get("close", 0) or 0)
            return f"- 恒生指数: {close:,.0f} (备用源)"
    except Exception as e:
        logger.debug(f"stock_hk_index_daily_sina 失败: {e}")
    return None


def _fetch_a50(ak) -> Optional[str]:
    """A50期货：主 futures_foreign_hist → 备 futures_foreign_commodity_realtime"""
    if ak is None:
        return None
    try:
        a50_df = ak.futures_foreign_hist(symbol="XINA50")
        if a50_df is not None and not a50_df.empty:
            last = a50_df.iloc[-1]
            close = float(last.get("close", 0) or 0)
            pct = float(last.get("pct_chg", 0) or 0)
            date_str = str(last.get("date", ""))[:10] if "date" in last else "?"
            emoji = "↑" if pct > 0 else ("↓" if pct < 0 else "→")
            return f"- A50期货: {close:,.0f} {emoji}{pct:+.2f}% (截至 {date_str})"
    except Exception as e:
        logger.debug(f"futures_foreign_hist 失败 [XINA50]: {e}")
    return None


def _fetch_usdcnh(ak) -> Optional[str]:
    """美元/人民币汇率"""
    if ak is None:
        return None
    try:
        fx_df = ak.fx_spot_quote()
        if fx_df is not None and not fx_df.empty:
            mask = fx_df["货币对"] == "美元/人民币" if "货币对" in fx_df.columns else (fx_df.iloc[:, 0] == "美元/人民币")
            usdcnh_row = fx_df[mask]
            if not usdcnh_row.empty:
                row = usdcnh_row.iloc[0]
                rate = float(row.get("最新价", row.iloc[2] if len(row) > 2 else 0) or 0)
                if rate > 0:
                    return f"- USDCNH: {rate:.4f}"
    except Exception as e:
        logger.debug(f"fx_spot_quote 失败: {e}")
    return None


def _fetch_vix(ak) -> Optional[str]:
    """VIX 恐慌指数"""
    if ak is None:
        return None
    try:
        vix_df = ak.index_us_stock_sina(symbol=".VIX")
        if vix_df is not None and not vix_df.empty:
            last = vix_df.iloc[-1]
            vix_val = float(last.get("close", 0) or 0)
            if vix_val > 0:
                if vix_val > 25:
                    zone = "恐慌 (>25) ⚠️ 全球风险偏好极低"
                elif vix_val > 20:
                    zone = "担忧 (20-25) 市场谨慎"
                elif vix_val > 15:
                    zone = "正常 (15-20)"
                else:
                    zone = "极度平静 (<15) 风险偏好高"
                return f"- VIX: {vix_val:.1f} — {zone}"
    except Exception as e:
        logger.debug(f"VIX fetch 失败: {e}")
    return None


def _fetch_commodity(ak, code: str, name: str) -> Optional[str]:
    """关键商品期货"""
    if ak is None:
        return None
    try:
        comm_df = ak.futures_foreign_hist(symbol=code)
        if comm_df is not None and not comm_df.empty:
            last = comm_df.iloc[-1]
            cp = float(last.get("close", 0) or 0)
            pct = float(last.get("pct_chg", 0) or 0)
            emoji = "↑" if pct > 0 else ("↓" if pct < 0 else "→")
            return f"- {name}: {cp:,.2f} {emoji}{pct:+.2f}%"
    except Exception as e:
        logger.debug(f"commodity fetch 失败 [{code}]: {e}")
    return None
