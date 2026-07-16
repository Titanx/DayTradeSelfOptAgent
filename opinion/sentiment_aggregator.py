"""
舆论情绪聚合器

将多源舆论数据（雪球/微博/新闻等）聚合为统一的情绪指标，
供 Sentiment Analyst Agent 使用。
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# 尝试导入 Agent-Reach 的 Web Channel
try:
    import sys
    from pathlib import Path
    _agent_reach_path = Path(__file__).parent.parent.parent / "Agent-Reach"
    if str(_agent_reach_path) not in sys.path:
        sys.path.insert(0, str(_agent_reach_path))
    from agent_reach.channels.web import WebChannel
    _web = WebChannel()
    _WEB_AVAILABLE = True
except Exception:
    _web = None
    _WEB_AVAILABLE = False


def aggregate_sentiment(symbol: str, stock_name: str = "",
                        config: dict = None) -> Dict[str, Any]:
    """
    聚合多源舆论情绪

    Args:
        symbol: A股代码，如 "600519"
        stock_name: 股票名称
        config: 配置字典

    Returns:
        {
            "xueqiu": {...},        # 雪球数据
            "news": [...],          # 新闻列表
            "overall_score": float, # 综合情绪评分 (-1 到 1)
            "summary": str,         # 汇总文本
            "risk_signals": [...],  # 风险信号
        }
    """
    sources = config.get("opinion_sources", ["xueqiu", "news"]) if config else ["xueqiu", "news"]
    result = {
        "symbol": symbol,
        "stock_name": stock_name,
        "analyzed_at": datetime.now().isoformat(),
        "sources": {},
        "overall_score": 0.0,
        "risk_signals": [],
    }

    # 1. 雪球舆论
    if "xueqiu" in sources:
        try:
            from .xueqiu_monitor import build_opinion_summary as xueqiu_summary
            # 转换为雪球格式
            xq_symbol = _to_xueqiu_symbol(symbol)
            xq_data = xueqiu_summary(xq_symbol, stock_name, limit=15)
            result["sources"]["xueqiu"] = xq_data
        except Exception as e:
            logger.warning(f"雪球舆论聚合失败: {e}")

    # 2. 财经新闻
    if "news" in sources:
        try:
            news_data = _fetch_financial_news(symbol, stock_name, limit=10)
            result["sources"]["news"] = news_data
        except Exception as e:
            logger.warning(f"财经新闻获取失败: {e}")

    # 3. 微博（通过 Jina Reader 搜索）
    if "weibo" in sources and _WEB_AVAILABLE:
        try:
            weibo_data = _fetch_weibo_sentiment(symbol, stock_name)
            result["sources"]["weibo"] = weibo_data
        except Exception as e:
            logger.warning(f"微博情绪获取失败: {e}")

    # 3.5 微信源（配置中可能声明，但代码未实现，跳过避免报错）
    if "wechat" in sources:
        logger.warning("微信源未实现，已跳过")

    # 4. 计算综合评分
    result["overall_score"] = _compute_overall_score(result["sources"])

    # 5. 检测风险信号
    result["risk_signals"] = _detect_risk_signals(result["sources"])

    # 6. 生成汇总文本
    result["summary"] = _generate_summary(result, symbol, stock_name)

    return result


def _to_xueqiu_symbol(symbol: str) -> str:
    """转换A股代码为雪球格式 SH600519 / SZ000858"""
    symbol = symbol.strip().zfill(6)
    if symbol.startswith(("6", "5")):
        return f"SH{symbol}"
    elif symbol.startswith(("0", "3", "2")):
        return f"SZ{symbol}"
    elif symbol.startswith(("4", "8")):
        return f"BJ{symbol}"
    return f"SH{symbol}"


def _fetch_financial_news(symbol: str, stock_name: str,
                          limit: int = 10) -> Dict[str, Any]:
    """获取财经新闻"""
    try:
        from dataflows.interface import route_to_vendor
        news = route_to_vendor("get_cn_stock_news", symbol)
        if news:
            return {"count": len(news), "items": news[:limit]}

        # fallback: 主接口失败时直接返回空（原 Jina Reader 回退因响应未使用已移除）
        return {"count": 0, "items": [], "note": "新闻获取受限"}
    except Exception as e:
        logger.error(f"新闻获取失败: {e}")
        return {"count": 0, "items": [], "error": str(e)}


def _fetch_weibo_sentiment(symbol: str, stock_name: str) -> Dict[str, Any]:
    """通过搜索获取微博相关情绪"""
    # DEPRECATED: 使用 Jina Reader (r.jina.ai) 抓取微博搜索结果，属于脆弱的第三方代理抓取方案。
    # 该函数被 _WEB_AVAILABLE (Agent-Reach WebChannel) 门控，但实际并未使用 WebChannel，
    # 且 Agent-Reach 目录不存在时该函数永远不会被调用。建议迁移到 WebChannel 或直接移除。
    query = stock_name or symbol
    try:
        # 使用 Jina Reader 搜索微博
        import urllib.request
        url = f"https://r.jina.ai/https://s.weibo.com/weibo?q={urllib.parse.quote(query)}"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/markdown"
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
        return {"query": query, "content_snippet": content[:2000], "note": "微博搜索结果摘要"}
    except Exception as e:
        return {"query": query, "error": str(e)}


def _compute_overall_score(sources: Dict[str, Any]) -> float:
    """
    综合情绪评分

    基于多源数据加权计算，范围 -1.0（极度悲观）到 1.0（极度乐观）
    """
    scores = []

    # 雪球评分
    xq = sources.get("xueqiu", {})
    if xq and "sentiment_hint" in xq:
        hint = xq["sentiment_hint"]
        if "偏多" in hint:
            scores.append(0.5)
        elif "偏空" in hint:
            scores.append(-0.5)
        elif "略偏多" in hint:
            scores.append(0.2)
        elif "略偏空" in hint:
            scores.append(-0.2)
        else:
            scores.append(0.0)

    # 行情评分（如果有quote）
    if xq and xq.get("quote"):
        pct = xq["quote"].get("percent", 0)
        if pct > 3:
            scores.append(0.4)
        elif pct > 1:
            scores.append(0.2)
        elif pct < -3:
            scores.append(-0.4)
        elif pct < -1:
            scores.append(-0.2)

    if not scores:
        return 0.0

    return round(sum(scores) / len(scores), 2)


def _detect_risk_signals(sources: Dict[str, Any]) -> List[str]:
    """检测舆论风险信号"""
    signals = []

    xq = sources.get("xueqiu", {})
    if xq:
        # 异常波动检测
        quote = xq.get("quote", {})
        if quote:
            pct = abs(quote.get("percent", 0))
            if pct >= 5:
                signals.append(f"⚠️ 股价异常波动 {quote.get('percent', 0):+.2f}%")

        # 负面关键词检测
        all_text = xq.get("summary", "")
        risk_keywords = {
            "暴雷": '🆘 舆论中出现"暴雷"关键词',
            "退市": '🚨 出现退市相关讨论',
            "立案": '⚠️ 出现监管立案相关消息',
            "违约": '⚠️ 出现违约相关消息',
            "减持": '📉 出现大股东减持讨论',
        }
        for kw, msg in risk_keywords.items():
            if kw in all_text:
                signals.append(msg)

    return signals


def _generate_summary(result: Dict, symbol: str, stock_name: str) -> str:
    """生成舆论情绪汇总报告"""
    name = stock_name or symbol
    score = result["overall_score"]

    if score > 0.3:
        mood = "偏乐观"
        emoji = "🟢"
    elif score > 0:
        mood = "略偏乐观"
        emoji = "🟡"
    elif score > -0.3:
        mood = "略偏悲观"
        emoji = "🟠"
    else:
        mood = "偏悲观"
        emoji = "🔴"

    lines = [
        f"## {emoji} {name}({symbol}) 舆论情绪报告",
        f"分析时间: {result['analyzed_at'][:19]}",
    ]

    # 综合评分
    lines.append(f"\n### 综合情绪评分: {score:+.2f} ({mood})")

    # 各源数据
    for src_name, src_data in result["sources"].items():
        if src_data:
            lines.append(f"\n### {src_name.upper()} 数据")
            lines.append(f"- 状态: ✓ 已获取")
            if isinstance(src_data, dict) and "summary" in src_data:
                lines.append(src_data["summary"])

    # 风险信号
    if result["risk_signals"]:
        lines.append("\n### 🚨 风险信号")
        for sig in result["risk_signals"]:
            lines.append(f"- {sig}")
    else:
        lines.append("\n### ✅ 无明显风险信号")

    return "\n".join(lines)
