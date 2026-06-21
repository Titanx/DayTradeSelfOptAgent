"""
Agent 工具函数

提供给 LangGraph Agent 节点调用的工具函数集合。
函数通过 @tool 装饰器暴露给 LLM，或作为 ToolNode 使用。
"""

import json
import logging
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime, timedelta

import pandas as pd

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
        # Fallback: try AKShare directly
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

    # 计算技术统计
    closes = [float(recent.iloc[i].get("close", recent.iloc[i].get("收盘", 0)))
              for i in range(len(recent))]
    ma5 = sum(closes[-5:]) / min(5, len(closes[-5:])) if closes else 0
    ma10 = sum(closes[-10:]) / min(10, len(closes[-10:])) if len(closes) >= 10 else closes[-1]
    ma20 = sum(closes[-20:]) / min(20, len(closes[-20:])) if len(closes) >= 20 else closes[-1]

    high = max(closes[-20:]) if len(closes) >= 20 else max(closes)
    low = min(closes[-20:]) if len(closes) >= 20 else min(closes)

    return json.dumps({
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
    }, ensure_ascii=False, indent=2)


def get_stock_realtime_quote(symbol: str) -> str:
    """获取A股实时行情"""
    from dataflows.interface import route_to_vendor

    data = route_to_vendor("get_stock_realtime", symbol)
    if data is None:
        return f"无法获取 {symbol} 实时行情"

    return json.dumps(data, ensure_ascii=False, indent=2)


# ============================================================
# 财务数据工具
# ============================================================

def get_stock_financials(symbol: str) -> str:
    """
    获取A股财务指标摘要

    Args:
        symbol: 股票代码
    """
    from dataflows.interface import route_to_vendor

    indicators = route_to_vendor("get_financial_indicators", symbol)

    if indicators is None or (hasattr(indicators, 'empty') and indicators.empty):
        return f"无法获取 {symbol} 的财务数据"

    try:
        if hasattr(indicators, 'to_dict'):
            # 取最近4期
            recent = indicators.head(4) if hasattr(indicators, 'head') else indicators
            return json.dumps(recent.to_dict(orient="records"), ensure_ascii=False, indent=2)
        return str(indicators)
    except Exception as e:
        return f"财务数据解析失败: {e}"


# ============================================================
# 市场情绪工具
# ============================================================

def get_market_sentiment_data() -> str:
    """获取A股整体市场情绪"""
    from dataflows.interface import route_to_vendor

    data = route_to_vendor("get_market_sentiment")
    if data is None:
        return "无法获取市场情绪数据"

    return json.dumps(data, ensure_ascii=False, indent=2)


def get_north_flow_data(days: int = 10) -> str:
    """获取北向资金流向"""
    from dataflows.interface import route_to_vendor

    df = route_to_vendor("get_north_flow", days=days)
    if df is None or df.empty:
        return "无法获取北向资金数据"

    try:
        return df.tail(days).to_string()
    except Exception:
        return str(df)


# ============================================================
# 板块数据工具
# ============================================================

def get_sector_data() -> str:
    """获取行业板块行情"""
    from dataflows.interface import route_to_vendor

    df = route_to_vendor("get_sector_boards")
    if df is None or df.empty:
        return "无法获取板块数据"

    try:
        # 只返回收益率前10和后10
        if "涨跌幅" in df.columns:
            sorted_df = df.sort_values("涨跌幅", ascending=False)
            top_bottom = pd.concat([sorted_df.head(10), sorted_df.tail(10)])
            return top_bottom[["名称", "涨跌幅", "领涨股"]].to_string() if "领涨股" in df.columns else top_bottom.to_string()
        return df.head(15).to_string()
    except Exception:
        return str(df.head(10))


# ============================================================
# 舆论监控工具（基于Agent-Reach）
# ============================================================

def get_opinion_report(symbol: str, stock_name: str = "") -> str:
    """
    获取个股舆论情绪报告

    整合雪球帖子、财经新闻等多源数据。

    Args:
        symbol: A股代码
        stock_name: 股票名称（可选）
    """
    try:
        from opinion.sentiment_aggregator import aggregate_sentiment
        from config.default_config import get_config

        config = get_config()
        result = aggregate_sentiment(symbol, stock_name, config)
        return result.get("summary", "无法获取舆论数据")
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
    """获取个股相关雪球帖子"""
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
        return json.dumps(result, ensure_ascii=False, indent=2)
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
# 工具函数映射
# ============================================================

# Agent 可调用的工具列表
MARKET_TOOLS = [
    get_stock_price_data,
    get_stock_realtime_quote,
    get_market_sentiment_data,
    get_sector_data,
    get_north_flow_data,
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
