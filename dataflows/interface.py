"""
统一数据接口层

路由数据请求到对应的 vendor（akshare / tushare），
提供统一的函数签名，Agent 工具函数通过此层获取数据。

借鉴 TradingAgents 的 VENDOR_METHODS 注册模式。
"""

import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, List
import logging

logger = logging.getLogger(__name__)

# ============================================================
# 数据分类
# ============================================================

TOOLS_CATEGORIES = {
    "market_data": ["get_stock_daily", "get_stock_realtime", "get_index_daily", "get_market_sentiment"],
    "fundamental_data": ["get_financial_data", "get_financial_indicators", "get_stock_notices"],
    "money_flow": ["get_money_flow", "get_north_flow"],
    "sector_data": ["get_sector_boards", "get_concept_boards"],
    "news_data": ["get_cn_stock_news"],
}


def _get_akshare_method(name: str) -> Optional[Callable]:
    """延迟加载 AKShare adapter 方法"""
    try:
        from .akshare_adapter import __dict__ as mod_dict
        return mod_dict.get(name, None)
    except ImportError:
        return None


def _get_tushare_method(name: str) -> Optional[Callable]:
    """延迟加载 Tushare adapter 方法"""
    try:
        from .tushare_adapter import __dict__ as mod_dict
        return mod_dict.get(name, None)
    except ImportError:
        return None


# ============================================================
# Vendor 方法注册表
# ============================================================

VENDOR_METHODS: Dict[str, Dict[str, Optional[Callable]]] = {
    "get_stock_daily":     {"akshare": _get_akshare_method("get_stock_daily")},
    "get_stock_realtime":  {"akshare": _get_akshare_method("get_stock_realtime")},
    "get_index_daily":     {"akshare": _get_akshare_method("get_index_daily")},
    "get_financial_data":  {"akshare": _get_akshare_method("get_financial_data")},
    "get_financial_indicators": {"akshare": _get_akshare_method("get_financial_indicators")},
    "get_money_flow":      {"akshare": _get_akshare_method("get_money_flow")},
    "get_north_flow":      {"akshare": _get_akshare_method("get_north_flow")},
    "get_market_sentiment":{"akshare": _get_akshare_method("get_market_sentiment")},
    "get_sector_boards":   {"akshare": _get_akshare_method("get_sector_boards")},
    "get_concept_boards":  {"akshare": _get_akshare_method("get_concept_boards")},
    "get_stock_notices":   {"akshare": _get_akshare_method("get_stock_notices")},
    "get_cn_stock_news":   {"akshare": _get_akshare_method("get_cn_stock_news")},
}


def get_category_for_method(method: str) -> Optional[str]:
    """根据方法名查找所属分类"""
    for category, methods in TOOLS_CATEGORIES.items():
        if method in methods:
            return category
    return None


def get_vendors_for_method(method: str, config: dict) -> List[str]:
    """获取方法的 vendor 优先级列表"""
    data_vendor = config.get("data_vendor", "akshare")
    # 支持逗号分隔的 fallback 链，如 "akshare,tushare"
    vendors = [v.strip() for v in data_vendor.split(",")]
    # 确保方法支持的 vendor
    available = [v for v in vendors if v in VENDOR_METHODS.get(method, {})]
    return available if available else ["akshare"]


def route_to_vendor(method: str, *args, config: dict = None, **kwargs) -> Any:
    """
    路由到数据 vendor

    支持 fallback 链：如果主 vendor 失败，尝试下一个。
    公共数据（市场情绪、北向资金、行业板块等）自动走缓存。

    Args:
        method: 工具方法名
        config: 配置字典（可选，用于读取 data_vendor）
        *args, **kwargs: 传递给底层方法

    Returns:
        底层方法的返回值
    """
    # ———— 缓存拦截：公共数据优先走缓存 ————
    from .market_cache import MarketDataCache
    cache = MarketDataCache.get_instance()
    if cache.is_public_method(method):
        cached = cache.get(method)
        if cached is not None:
            return cached

    if config is None:
        from config.default_config import get_config
        config = get_config()

    vendors = get_vendors_for_method(method, config)

    if method not in VENDOR_METHODS:
        logger.error(f"未知数据方法: {method}")
        return None

    last_error = None
    for vendor in vendors:
        func = VENDOR_METHODS[method].get(vendor)
        if func is None:
            # 延迟加载
            if vendor == "akshare":
                func = _get_akshare_method(method)
                VENDOR_METHODS[method]["akshare"] = func
            elif vendor == "tushare":
                func = _get_tushare_method(method)
                VENDOR_METHODS[method]["tushare"] = func

        if func is None:
            continue

        try:
            result = func(*args, **kwargs)
            if result is not None:
                # ———— 缓存保存：公共数据成功获取后写入缓存 ————
                if cache.is_public_method(method):
                    cache.set(method, result)
                return result
        except Exception as e:
            last_error = e
            logger.warning(f"Vendor [{vendor}] 方法 [{method}] 失败: {e}")
            continue

    if last_error:
        logger.error(f"所有 vendor 方法 [{method}] 均失败，最后错误: {last_error}")
    return None
