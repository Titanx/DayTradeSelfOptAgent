"""
雪球舆论监控模块

基于 Agent-Reach 的 XueqiuChannel 直接调用，
提供 A股相关舆情数据的获取和格式化。

核心能力：
  1. 获取个股实时行情
  2. 获取雪球热门帖子（舆论热度）
  3. 获取热门股票排行（市场关注度）
  4. 搜索股票相关讨论
"""

import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# 尝试导入 Agent-Reach 的雪球 Channel
try:
    _agent_reach_path = Path(__file__).parent.parent.parent / "Agent-Reach"
    if str(_agent_reach_path) not in sys.path:
        sys.path.insert(0, str(_agent_reach_path))

    from agent_reach.channels.xueqiu import XueqiuChannel
    _XUEQIU_AVAILABLE = True
    _xueqiu = XueqiuChannel()
except Exception as e:
    logger.warning(f"Agent-Reach 雪球Channel 导入失败: {e}，将使用HTTP回退")
    _XUEQIU_AVAILABLE = False
    _xueqiu = None


# ============================================================
# 雪球行情/热度数据
# ============================================================

def get_xueqiu_quote(symbol: str) -> Optional[Dict[str, Any]]:
    """
    获取雪球个股行情

    Args:
        symbol: A股代码（雪球格式），如 "SH600519", "SZ000858"

    Returns:
        行情数据字典
    """
    if _XUEQIU_AVAILABLE and _xueqiu:
        try:
            return _xueqiu.get_stock_quote(symbol)
        except Exception as e:
            logger.warning(f"雪球行情获取失败 [{symbol}]: {e}")

    # HTTP fallback
    try:
        import requests
        symbol_code = symbol[2:] if len(symbol) > 2 else symbol
        market = 17 if symbol.startswith("SZ") else 1  # 17=深交所, 1=上交所
        url = f"https://stock.xueqiu.com/v5/stock/quote.json?symbol={symbol}&extend=detail"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", {}).get("quote", {})
            return {
                "symbol": data.get("symbol", symbol),
                "name": data.get("name", ""),
                "current": data.get("current", 0),
                "percent": data.get("percent", 0),
                "high": data.get("high", 0),
                "low": data.get("low", 0),
                "volume": data.get("volume", 0),
                "amount": data.get("amount", 0),
                "market_capital": data.get("market_capital", 0),
                "pe_ttm": data.get("pe_ttm", 0),
            }
    except Exception as e:
        logger.error(f"雪球HTTP回退失败 [{symbol}]: {e}")

    return None


def get_xueqiu_hot_posts(symbol: str = None, limit: int = 20) -> List[Dict[str, Any]]:
    """
    获取雪球热门帖子

    Args:
        symbol: 可选，按股票代码筛选
        limit: 返回条数

    Returns:
        帖子列表，每个包含: title, text, author, likes, url, created_at
    """
    if _XUEQIU_AVAILABLE and _xueqiu:
        try:
            posts = _xueqiu.get_hot_posts(limit=limit)
            if posts:
                if symbol:
                    code = symbol[2:] if len(symbol) > 2 else symbol
                    posts = [p for p in posts if code in (p.get("title", "") + p.get("text", ""))]
                return posts[:limit]
        except Exception as e:
            logger.warning(f"雪球热门帖子获取失败: {e}")

    # HTTP fallback
    try:
        import requests
        url = "https://xueqiu.com/v4/statuses/public_timeline_by_category.json"
        params = {"page": 1, "count": limit}
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            items = r.json().get("list", [])
            posts = []
            for item in items:
                data = item.get("data", item)
                posts.append({
                    "id": data.get("id", ""),
                    "title": (data.get("title") or data.get("description", ""))[:100],
                    "text": (data.get("text") or data.get("description", ""))[:300],
                    "author": data.get("user", {}).get("screen_name", ""),
                    "likes": data.get("like_count", 0),
                    "url": f"https://xueqiu.com{data.get('target', data.get('id', ''))}",
                })
            return posts[:limit]
    except Exception as e:
        logger.error(f"雪球HTTP回退热门帖子失败: {e}")

    return []


def get_xueqiu_hot_stocks(limit: int = 20) -> List[Dict[str, Any]]:
    """
    获取雪球热门股票排行（市场关注度指标）

    Args:
        limit: 返回条数

    Returns:
        热门股票列表
    """
    if _XUEQIU_AVAILABLE and _xueqiu:
        try:
            return _xueqiu.get_hot_stocks(limit=limit)
        except Exception as e:
            logger.warning(f"雪球热门股票获取失败: {e}")

    # HTTP fallback
    try:
        import requests
        url = "https://stock.xueqiu.com/v5/stock/hot_stock/list.json"
        params = {"size": limit, "_type": 10}
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            items = r.json().get("data", {}).get("items", [])
            return [
                {
                    "symbol": item.get("symbol", ""),
                    "name": item.get("name", ""),
                    "current": item.get("current", 0),
                    "percent": item.get("percent", 0),
                    "rank": i + 1,
                }
                for i, item in enumerate(items)
            ][:limit]
    except Exception as e:
        logger.error(f"雪球HTTP回退热门股票失败: {e}")

    return []


def search_xueqiu_posts(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    搜索雪球帖子（按关键词）

    Args:
        query: 搜索关键词（股票名称/代码/概念）
        limit: 返回条数

    Returns:
        相关帖子列表
    """
    try:
        import requests
        url = "https://xueqiu.com/query/v1/search/web/search.json"
        params = {"q": query, "count": limit, "page": 1}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            statuses = r.json().get("list", {}).get("statuses", [])
            posts = []
            for item in statuses:
                posts.append({
                    "id": item.get("id", ""),
                    "title": item.get("title", "")[:100],
                    "text": item.get("description", item.get("text", ""))[:300],
                    "author": item.get("user", {}).get("screen_name", ""),
                    "likes": item.get("like_count", 0),
                    "comments": item.get("reply_count", 0),
                    "created_at": item.get("created_at", 0),
                })
            return posts[:limit]
    except Exception as e:
        logger.error(f"雪球搜索失败 [{query}]: {e}")

    return []


# ============================================================
# 舆论摘要
# ============================================================

def build_opinion_summary(symbol: str, stock_name: str = "",
                           limit: int = 15) -> Dict[str, Any]:
    """
    构建个股舆论摘要

    Args:
        symbol: 雪球格式代码，如 "SH600519"
        stock_name: 股票名称
        limit: 帖子/数据条数

    Returns:
        {
            "quote": {...},
            "hot_posts": [...],
            "search_posts": [...],
            "summary": "舆论情绪总结文本"
        }
    """
    quote = get_xueqiu_quote(symbol)
    hot_posts = get_xueqiu_hot_posts(symbol, limit=limit)

    # 用股票名称搜索更多相关讨论
    search_name = stock_name or (quote.get("name", "") if quote else "")
    search_code = symbol[2:] if len(symbol) > 2 else symbol
    search_query = f"{search_name} {search_code}" if search_name else search_code
    search_posts = search_xueqiu_posts(search_query, limit=limit)

    # 统计情绪倾向（简单规则）
    total_posts = len(hot_posts) + len(search_posts)
    sentiment_hint = _estimate_sentiment(hot_posts + search_posts)

    summary_lines = [
        f"## {search_name or symbol} 雪球舆论监控",
        f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]

    if quote:
        summary_lines.append(
            f"\n### 行情快照\n"
            f"- 现价: {quote.get('current', 'N/A')} "
            f"({quote.get('percent', 0):+.2f}%)\n"
            f"- 市值: {_format_cap(quote.get('market_capital', 0))}\n"
            f"- PE(TTM): {quote.get('pe_ttm', 'N/A')}"
        )

    summary_lines.append(
        f"\n### 舆论概览\n"
        f"- 相关帖子数: {total_posts}篇\n"
        f"- 情绪倾向: {sentiment_hint}\n"
        f"- 热度评分: {_heat_score(hot_posts, search_posts)}/100"
    )

    # Top 5 热门帖子
    all_posts = sorted(hot_posts + search_posts,
                       key=lambda x: x.get("likes", 0), reverse=True)[:5]
    if all_posts:
        summary_lines.append("\n### 🔥 Top帖子")
        for p in all_posts:
            title = p.get("title", "") or p.get("text", "")[:50]
            summary_lines.append(f"- [{p.get('likes', 0)}赞] {title}")

    return {
        "quote": quote,
        "hot_posts": hot_posts,
        "search_posts": search_posts,
        "summary": "\n".join(summary_lines),
        "sentiment_hint": sentiment_hint,
    }


def _estimate_sentiment(posts: List[Dict]) -> str:
    """简单情绪估计"""
    if not posts:
        return "无数据"

    bullish_words = ["涨", "利好", "买入", "看好", "突破", "牛", "起飞", "涨停",
                     "翻倍", "增持", "超预期", "龙头"]
    bearish_words = ["跌", "利空", "卖出", "看空", "破位", "熊", "崩盘", "跌停",
                     "减持", "亏损", "暴雷", "套牢"]

    bull_score = 0
    bear_score = 0
    for p in posts:
        text = (p.get("title", "") + p.get("text", "")).lower()
        bull_score += sum(1 for w in bullish_words if w in text)
        bear_score += sum(1 for w in bearish_words if w in text)

    if bull_score > bear_score * 1.5:
        return "偏多 🟢"
    elif bear_score > bull_score * 1.5:
        return "偏空 🔴"
    elif bull_score > bear_score:
        return "略偏多 🟡"
    elif bear_score > bull_score:
        return "略偏空 🟠"
    else:
        return "中性 ⚪"


def _heat_score(hot_posts: List[Dict], search_posts: List[Dict]) -> int:
    """计算舆论热度分数 (0-100)"""
    total_likes = sum(p.get("likes", 0) for p in hot_posts + search_posts)
    total_posts = len(hot_posts) + len(search_posts)

    # 基于点赞数和帖子数的加权评分
    score = min(100, int(total_likes * 0.2 + total_posts * 3))
    return score


def _format_cap(cap_value) -> str:
    """格式化市值"""
    if not cap_value:
        return "N/A"
    cap = float(cap_value)
    if cap >= 1e12:
        return f"{cap/1e12:.2f}万亿"
    elif cap >= 1e8:
        return f"{cap/1e8:.2f}亿"
    else:
        return f"{cap/1e4:.2f}万"
