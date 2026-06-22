"""
Agent 工具函数

提供给 LangGraph Agent 节点调用的工具函数集合。
函数通过 @tool 装饰器暴露给 LLM，或作为 ToolNode 使用。
"""

import logging
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime, timedelta

import pandas as pd

from .md_utils import to_markdown

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
    end_date = datetime.now()
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
    ma10 = sum(closes[-10:]) / min(10, len(closes[-10:])) if len(closes) >= 10 else closes[-1]
    ma20 = sum(closes[-20:]) / min(20, len(closes[-20:])) if len(closes) >= 20 else closes[-1]

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
    try:
        from dataflows.market_cache import MarketDataCache
        cache = MarketDataCache.get_instance()
        cache.set_stock_data(symbol, "get_stock_realtime_quote", output)
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

    import re

    # 1. ST 检查
    is_st = symbol.startswith("600") is False and symbol.startswith("000") is False and symbol.startswith("002") is False
    name_lower = stock_name.lower() if stock_name else ""
    st_match = bool(re.search(r'[*]?ST', quote_data)) or bool(re.search(r'[*]?ST', price_data))
    if st_match or 'st' in name_lower:
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
    if st_match:
        lines.append("> 🔴 **坚决回避** — ST 股票不符合一日游策略条件")
    elif limit_down:
        lines.append("> 🟠 **建议观望** — 有跌停记录，Day 2 可能无法顺利卖出")
    else:
        lines.append("> 🟡 **需结合其他分析判断** — 无硬性排除条件")

    return "\n".join(lines)


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
]
