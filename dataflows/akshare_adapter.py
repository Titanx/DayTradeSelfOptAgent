"""
AKShare A股数据适配器

提供 A股行情、财务数据、技术指标、资金流向、市场情绪等数据接口。
AKShare 是免费开源库，无需 API Key，数据源来自东方财富、新浪财经等。
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta, timezone
import functools
import logging

try:
    from zoneinfo import ZoneInfo
    _BJ_TIME = ZoneInfo("Asia/Shanghai")
except ImportError:
    # Python 3.8 或无 zoneinfo，用 UTC+8 固定偏移
    _BJ_TIME = timezone(timedelta(hours=8))

logger = logging.getLogger(__name__)


import time
import random

_SAFE_RETRIES = 3
_SAFE_BASE_DELAY = 1.0

def _safe_akshare_call(func):
    """安全调用包装器：捕获 AKShare 错误，自动重试+指数退避"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        last_error = None
        for attempt in range(1, _SAFE_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < _SAFE_RETRIES:
                    delay = _SAFE_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0.1, 0.5)
                    logger.warning(f"AKShare [{func.__name__}] 第{attempt}次失败，{delay:.1f}s后重试: {e}")
                    time.sleep(delay)
                else:
                    logger.error(f"AKShare [{func.__name__}] {_SAFE_RETRIES}次全部失败: {e}")
        return None
    return wrapper


# ============================================================
# 工具函数
# ============================================================

# 节假日缓存: 同一会话内只拉取一次 akshare 交易日历
_TRADE_DATE_CACHE: Optional[set] = None
_TRADE_DATE_FETCHED_AT: Optional[datetime] = None


def _load_trade_calendar() -> Optional[set]:
    """加载 A 股交易日历（含节假日信息）

    使用 akshare.tool_trade_date_hist_sina() 获取历年交易日列表。
    同一会话内只拉取一次，缓存到模块级变量。

    Returns:
        set of "YYYY-MM-DD" 字符串（交易日集合）；失败返回 None
    """
    global _TRADE_DATE_CACHE, _TRADE_DATE_FETCHED_AT

    # 缓存有效期 24 小时（避免会话跨日时使用过期数据）
    if _TRADE_DATE_CACHE is not None and _TRADE_DATE_FETCHED_AT is not None:
        if (datetime.now(_BJ_TIME) - _TRADE_DATE_FETCHED_AT).total_seconds() < 86400:
            return _TRADE_DATE_CACHE

    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        if df is None or df.empty:
            return _TRADE_DATE_CACHE  # 拉取失败时返回上一次缓存（可能为 None）
        # 列名: trade_date (datetime 类型)
        col = "trade_date" if "trade_date" in df.columns else df.columns[0]
        dates = set(pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d").tolist())
        _TRADE_DATE_CACHE = dates
        _TRADE_DATE_FETCHED_AT = datetime.now(_BJ_TIME)
        logger.info(f"📅 A股交易日历加载成功: {len(dates)} 个交易日")
        return dates
    except Exception as e:
        logger.debug(f"加载交易日历失败（将回退到周末判断）: {e}")
        return _TRADE_DATE_CACHE  # 失败时返回上一次缓存


def is_market_closed() -> bool:
    """
    判断 A 股是否已收盘（收盘后数据需要 30 分钟更新）。

    返回 True 当且仅当当前时间 >= 15:30（确保数据已更新）。
    周末返回 False（周末没有盘中，不强制等待；调用方应自行返回最近工作日）。

    Returns:
        True: 市场已收盘，可使用当日收盘数据
        False: 市场未收盘（盘中）或周末，当日数据不完整
    """
    now = datetime.now(_BJ_TIME)
    # 周末视为"未在盘中"（不触发等待收盘逻辑）
    if now.weekday() >= 5:  # 周六=5、周日=6
        return False
    # 工作日：15:30 后视为收盘（留 30 分钟给数据源更新）
    return now.hour > 15 or (now.hour == 15 and now.minute >= 30)


def get_latest_trade_date() -> str:
    """
    获取最近一个A股交易日日期 (YYYY-MM-DD)。

    逻辑：
    - 优先使用 akshare 交易日历（含节假日信息，如国庆/春节）
    - 如果当前为盘中时段（工作日 9:30 前 / 15:30 前），返回昨日交易日
      （因为今日数据未完成，缓存为"昨日数据"会污染收盘数据）
    - 如果当前为收盘后或周末，使用交易日历确认最近交易日

    周末不输出盘中 warning（周末没有盘中）。
    """
    trade_calendar = _load_trade_calendar()
    now = datetime.now(_BJ_TIME)

    # 盘中或周末：返回最近交易日（不调用 akshare 实时接口）
    if not is_market_closed():
        # 用交易日历回退找最近交易日（处理节假日：如周一为节假日时返回上周五）
        if trade_calendar is not None:
            # 从昨日开始往前找最近的交易日
            for offset in range(0, 15):  # 最多往前找 15 天（覆盖春节 7 天假期）
                check_date = (now - timedelta(days=offset + 1)).strftime("%Y-%m-%d")
                if check_date in trade_calendar:
                    if now.weekday() < 5:
                        logger.warning(
                            f"⚠️ 当前非收盘状态（盘中或节假日），使用最近交易日数据: {check_date}"
                        )
                    return check_date
            # 日历中找不到，落到下面的兜底逻辑

        # 无交易日历或日历中找不到 → 回退到排除周末的逻辑
        if now.weekday() == 5:  # 周六
            trade_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        elif now.weekday() == 6:  # 周日
            trade_date = (now - timedelta(days=2)).strftime("%Y-%m-%d")
        elif now.weekday() == 0:  # 周一盘中：返回上周五
            trade_date = (now - timedelta(days=3)).strftime("%Y-%m-%d")
        else:  # 工作日盘中：返回昨日
            trade_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        # 工作日盘中输出 warning（周末不输出，因为周末没有盘中）
        if now.weekday() < 5:
            logger.warning(
                f"⚠️ 当前为盘中时段（未收盘），使用昨日数据: {trade_date}（当日数据不完整）"
            )
        return trade_date

    # 已收盘：用交易日历确认今日是否为交易日
    if trade_calendar is not None:
        today_str = now.strftime("%Y-%m-%d")
        # 今日是交易日 → 返回今日
        if today_str in trade_calendar:
            return today_str
        # 今日不是交易日（如节假日） → 往前找最近的交易日
        for offset in range(1, 15):
            check_date = (now - timedelta(days=offset)).strftime("%Y-%m-%d")
            if check_date in trade_calendar:
                return check_date

    # 回退：使用上证指数最近 K 线确认最近交易日
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol="sh000001")
        if df is not None and not df.empty:
            last_date = pd.to_datetime(df.iloc[-1]["date"])
            trade_date = last_date.strftime("%Y-%m-%d")
            # 如果数据距今超过3天，可能是源端未更新，回退到工作日
            # last_date 为 akshare 返回的 naive 时间戳（视作北京时间），用日期比较避免 aware/naive 冲突
            if (datetime.now(_BJ_TIME).date() - last_date.date()).days <= 3:
                return trade_date
    except Exception:
        pass

    # 最终回退：排除周末，往前找最近工作日
    today = datetime.now(_BJ_TIME)
    if today.weekday() == 5:  # 周六
        today -= timedelta(days=1)
    elif today.weekday() == 6:  # 周日
        today -= timedelta(days=2)
    return today.strftime("%Y-%m-%d")


# ============================================================
# 行情数据
# ============================================================

@_safe_akshare_call
def get_stock_daily(symbol: str, start_date: str = None, end_date: str = None,
                    adjust: str = "") -> Optional[pd.DataFrame]:
    """
    获取A股日线行情数据（新浪源，避免 push2.eastmoney.com 被阻断）

    Args:
        symbol: 股票代码，如 "000001" (平安银行), "600519" (贵州茅台)
        start_date: 起始日期 "YYYYMMDD"，默认最近1年
        end_date: 结束日期 "YYYYMMDD"，默认今天
        adjust: 复权方式 ""=不复权 / "qfq"=前复权 / "hfq"=后复权

    Returns:
        DataFrame with columns: date, open, high, low, close, volume, amount, ...
    """
    import akshare as ak

    if start_date is None:
        start_date = (datetime.now(_BJ_TIME) - timedelta(days=365)).strftime("%Y%m%d")
    if end_date is None:
        end_date = datetime.now(_BJ_TIME).strftime("%Y%m%d")

    # 优先使用东方财富源（部分网络环境可用）
    try:
        df = ak.stock_zh_a_hist(
            symbol=symbol, period="daily",
            start_date=start_date, end_date=end_date, adjust=adjust or "qfq"
        )
        if df is not None and not df.empty:
            col_map = {
                "日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume",
                "成交额": "amount", "振幅": "amplitude", "涨跌幅": "pct_change",
                "涨跌额": "change", "换手率": "turnover_rate"
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
            return df
    except Exception:
        pass

    # 回退到新浪源 (需要 sh/sz 前缀)
    prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
    try:
        df = ak.stock_zh_a_daily(
            symbol=f"{prefix}{symbol}",
            start_date=start_date, end_date=end_date, adjust=adjust or "qfq"
        )
        if df is not None and not df.empty and "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
            return df
    except Exception:
        pass

    # 最后尝试腾讯源
    try:
        df = ak.stock_zh_a_hist_tx(
            symbol=symbol, start_date=start_date, end_date=end_date
        )
        if df is not None and not df.empty:
            if "交易日" in df.columns:
                df = df.rename(columns={
                    "交易日": "date", "开盘价": "open", "收盘价": "close",
                    "最高价": "high", "最低价": "low", "成交量(股)": "volume"
                })
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date")
                return df
    except Exception:
        pass

    return None


@_safe_akshare_call
def get_stock_realtime(symbol: str) -> Optional[Dict[str, Any]]:
    """
    获取A股实时行情快照（多源回退）

    回退链: 东财直连(单股) → 新浪直连(单股) → 腾讯直连(单股)
            → AKShare 东方财富(全市场快照) → AKShare 新浪(全市场快照)
            → AKShare 日K线最后一日

    Args:
        symbol: 股票代码

    Returns:
        dict with: name, price, change_pct, volume, high, low, open, pre_close
    """
    # M4+M5: 优先使用 direct_http 的三家直连单股接口（轻量、不拉全市场）
    # 回退顺序与项目设计一致: 东财 → 新浪 → 腾讯
    from .direct_http import eastmoney_realtime, sina_realtime, tencent_realtime

    for fetcher_name, fetcher in [
        ("eastmoney", eastmoney_realtime),
        ("sina", sina_realtime),
        ("tencent", tencent_realtime),
    ]:
        try:
            data = fetcher(symbol)
            if data and data.get("price", 0) > 0:
                # 统一字段名（直连接口返回 amount/limit_up/limit_down，与下方 akshare 路径保持兼容）
                return _normalize_realtime(data, symbol)
        except Exception as e:
            logger.debug(f"{fetcher_name}_realtime 失败 [{symbol}]: {e}")

    try:
        import akshare as ak
    except ImportError:
        ak = None

    if ak is not None:
        # AKShare 东方财富源（全市场快照，作为回退，开销大但稳定）
        try:
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                row = df[df["代码"] == symbol]
                if not row.empty:
                    row = row.iloc[0]
                    return {
                        "symbol": symbol,
                        "name": row.get("名称", ""),
                        "price": float(row.get("最新价", 0)),
                        "change_pct": float(row.get("涨跌幅", 0)),
                        "change": float(row.get("涨跌额", 0)),
                        "volume": int(row.get("成交量", 0)),
                        "amount": float(row.get("成交额", 0)),
                        "high": float(row.get("最高", 0)),
                        "low": float(row.get("最低", 0)),
                        "open": float(row.get("今开", 0)),
                        "pre_close": float(row.get("昨收", 0)),
                        "turnover_rate": float(row.get("换手率", 0)) if "换手率" in row else None,
                        "pe": float(row.get("市盈率-动态", 0)) if "市盈率-动态" in row else None,
                        "total_mv": float(row.get("总市值", 0)) if "总市值" in row else None,
                        "circ_mv": float(row.get("流通市值", 0)) if "流通市值" in row else None,
                    }
        except Exception:
            pass

        # AKShare 新浪源（全市场快照，作为再回退）
        try:
            df = ak.stock_zh_a_spot()
            if df is not None and not df.empty:
                row = df[df["代码"] == symbol]
                if not row.empty:
                    row = row.iloc[0]
                    return {
                        "symbol": symbol,
                        "name": str(row.get("名称", "")),
                        "price": float(row.get("最新价", 0) or 0),
                        "change_pct": float(row.get("涨跌幅", 0) or 0),
                        "change": float(row.get("涨跌额", 0) or 0),
                        "volume": int(float(row.get("成交量", 0) or 0)),
                        "amount": float(row.get("成交额", 0) or 0),
                        "high": float(row.get("最高", 0) or 0),
                        "low": float(row.get("最低", 0) or 0),
                        "open": float(row.get("今开", 0) or 0),
                        "pre_close": float(row.get("昨收", 0) or 0),
                    }
        except Exception:
            pass

        # 从个股日K线取最近一天数据作为最终回退（非实时，但保证有数据）
        try:
            prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
            df = ak.stock_zh_a_daily(
                symbol=f"{prefix}{symbol}",
                start_date=(datetime.now(_BJ_TIME) - timedelta(days=7)).strftime("%Y%m%d"),
                end_date=datetime.now(_BJ_TIME).strftime("%Y%m%d"),
                adjust="qfq"
            )
            if df is not None and not df.empty and "date" in df.columns:
                last = df.iloc[-1]
                close = float(last.get("close", 0))
                pct = float(last.get("pct_change", 0) or 0)
                return {
                    "symbol": symbol,
                    "name": "",
                    "price": close,
                    "change_pct": pct,
                    "change": float(last.get("change", 0) or 0),
                    "volume": int(float(last.get("volume", 0) or 0)),
                    "amount": float(last.get("amount", 0) or 0),
                    "high": float(last.get("high", 0) or 0),
                    "low": float(last.get("low", 0) or 0),
                    "open": float(last.get("open", 0) or 0),
                    "pre_close": close / (1 + pct / 100) if pct else close,
                }
        except Exception:
            pass

    return None


def _normalize_realtime(data: dict, symbol: str) -> Dict[str, Any]:
    """将 direct_http 各源返回的 dict 统一为 get_stock_realtime 的标准输出格式

    直连接口字段: name/price/last_close/open/high/low/volume/amount/...
    标准输出:     name/price/pre_close/change/change_pct/volume/amount/high/low/open
                 + 可选 turnover_rate/pe/total_mv/circ_mv/limit_up/limit_down
    """
    price = float(data.get("price", 0) or 0)
    last_close = float(data.get("last_close", 0) or 0)
    change = float(data.get("change_amt", price - last_close) or 0)
    change_pct = float(data.get("change_pct", 0) or 0)
    if change_pct == 0 and last_close > 0:
        change_pct = (price - last_close) / last_close * 100
    # amount: 东财/新浪返回元；腾讯返回 amount_wan (万元)
    if "amount" in data and data["amount"]:
        amount = float(data["amount"] or 0)
    elif "amount_wan" in data and data["amount_wan"]:
        amount = float(data["amount_wan"] or 0) * 10000
    else:
        amount = 0.0
    # volume: 东财/新浪返回股；腾讯无 volume（需通过 amount/price 反推近似）
    if "volume" in data and data["volume"]:
        volume = float(data["volume"] or 0)
    elif amount > 0 and price > 0:
        # 近似值，盘中 price 偏离 VWAP 时有 5-10% 误差，仅用于停牌判断（volume==0）
        volume = amount / price
    else:
        volume = 0.0
    mcap_yi = float(data.get("mcap_yi", 0) or 0)
    float_mcap_yi = float(data.get("float_mcap_yi", 0) or 0)

    result = {
        "symbol": symbol,
        "name": data.get("name", ""),
        "price": price,
        "change_pct": change_pct,
        "change": change,
        "volume": int(volume),
        "amount": amount,
        "high": float(data.get("high", 0) or 0),
        "low": float(data.get("low", 0) or 0),
        "open": float(data.get("open", 0) or 0),
        "pre_close": last_close,
    }

    # 可选字段（直连接口才有，akshare 全市场快照有部分）
    turnover = data.get("turnover_pct") or data.get("turnover_rate")
    if turnover is not None:
        result["turnover_rate"] = float(turnover)
    pe = data.get("pe_ttm") or data.get("pe")
    if pe is not None:
        result["pe"] = float(pe)
    pb = data.get("pb")
    if pb is not None:
        result["pb"] = float(pb)
    if mcap_yi:
        result["total_mv"] = mcap_yi * 1e8
    if float_mcap_yi:
        result["circ_mv"] = float_mcap_yi * 1e8
    # limit_up/limit_down（结构化硬过滤需要）
    if "limit_up" in data:
        result["limit_up"] = float(data["limit_up"])
    if "limit_down" in data:
        result["limit_down"] = float(data["limit_down"])
    return result


def get_sector_fund_flow(sector_name: str = None, days: int = 3) -> Optional[Dict]:
    """获取板块资金流排名 (东方财富 industry funds flow)

    返回: {
        "today":  [{"name":"光伏设备", "net_inflow":..., "pct_chg":..., "rank":1}, ...],
        "5_day":  [...],
        "10_day": [...],
    }
    如果 sector_name 非空, 额外附加该板块的个股资金流明细。
    """
    import akshare as ak
    result = {}
    periods = {"today": "今日", "5_day": "5日", "10_day": "10日"}
    try:
        for key, label in periods.items():
            df = ak.stock_sector_fund_flow_rank(indicator=label, sector_type="行业资金流")
            if df is not None and len(df) > 0:
                short = df.head(15)
                result[key] = []
                for _, row in short.iterrows():
                    result[key].append({
                        "name": str(row.get("名称", "")),
                        "pct_chg": float(row.get("涨跌幅", 0)) if row.get("涨跌幅") is not None else 0,
                        "net_inflow": float(row.get("主力净流入-净额", 0)) if row.get("主力净流入-净额") is not None else 0,
                        "net_ratio": float(row.get("主力净流入-净占比", 0)) if row.get("主力净流入-净占比") is not None else 0,
                        "rank": int(row.get("序号", 0)) if row.get("序号") is not None else 0,
                    })
    except Exception as e:
        logger.warning(f"板块资金流拉取失败: {e}")
        return None

    if not result:
        return None
    return result


# ============================================================
# 财务数据
# ============================================================

@_safe_akshare_call
def get_financial_data(symbol: str) -> Optional[Dict[str, pd.DataFrame]]:
    """
    获取A股财务数据（资产负债表、利润表、现金流量表）

    Returns:
        {"balance": DataFrame, "income": DataFrame, "cashflow": DataFrame}
    """
    import akshare as ak

    result = {}

    try:
        result["balance"] = ak.stock_financial_balance_sheet_by_report_em(symbol=symbol)
    except Exception:
        result["balance"] = None

    try:
        result["income"] = ak.stock_financial_profit_by_report_em(symbol=symbol)
    except Exception:
        result["income"] = None

    try:
        result["cashflow"] = ak.stock_financial_cash_flow_by_report_em(symbol=symbol)
    except Exception:
        result["cashflow"] = None

    return result


@_safe_akshare_call
def get_financial_indicators(symbol: str) -> Optional[pd.DataFrame]:
    """
    获取财务指标（ROE、ROA、毛利率、净利率等）

    Returns:
        DataFrame with 报告期 as index, indicators as columns
    """
    import akshare as ak
    return ak.stock_financial_abstract_ths(symbol=symbol)


# ============================================================
# 资金流向
# ============================================================

@_safe_akshare_call
def get_money_flow(symbol: str, days: int = 20) -> Optional[pd.DataFrame]:
    """
    获取个股资金流向（主力/超大单/大单/中单/小单）

    Args:
        symbol: 股票代码
        days: 获取天数

    Returns:
        DataFrame
    """
    import akshare as ak
    df = ak.stock_individual_fund_flow(stock=symbol, market="sh" if symbol.startswith("6") else "sz")
    if df is not None and not df.empty:
        df["日期"] = pd.to_datetime(df["日期"])
        df = df.sort_values("日期").tail(days)
    return df


@_safe_akshare_call
def get_north_flow(days: int = 10) -> Optional[pd.DataFrame]:
    """
    获取北向资金流向

    Args:
        days: 获取天数

    Returns:
        DataFrame with columns: 日期, 当日成交净买额(亿), 买入成交额, 卖出成交额
    """
    import akshare as ak
    df = ak.stock_hsgt_hist_em(symbol="沪股通")
    if df is not None and not df.empty:
        cols = {"日期": "date", "当日成交净买额": "net_buy", "买入成交额": "buy_amount",
                "卖出成交额": "sell_amount", "持股市值": "holding_value"}
        df = df.rename(columns={k: v for k, v in cols.items() if k in df.columns})
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").tail(days)
        return df
    return None


# ============================================================
# 板块/行业数据
# ============================================================

@_safe_akshare_call
def get_sector_boards() -> Optional[pd.DataFrame]:
    """获取行业板块涨跌排行（东方财富源优先，同花顺源回退）"""
    import akshare as ak
    try:
        return ak.stock_board_industry_spot_em()
    except Exception:
        pass
    try:
        return ak.stock_board_industry_summary_ths()
    except Exception:
        pass
    return None


@_safe_akshare_call
def get_concept_boards() -> Optional[pd.DataFrame]:
    """获取概念板块涨跌排行（东方财富源优先，同花顺源回退）"""
    import akshare as ak
    try:
        return ak.stock_board_concept_spot_em()
    except Exception:
        pass
    try:
        return ak.stock_board_concept_summary_ths()  # (round-12, H-opt-1): 修正接口名，cons_ths 不存在
    except Exception:
        pass
    return None


# ============================================================
# 市场情绪指标
# ============================================================

@_safe_akshare_call
def get_market_sentiment() -> Optional[Dict[str, Any]]:
    """
    获取A股市场整体情绪指标
    包括：涨跌家数、涨停跌停数、市场总成交额等
    """
    import akshare as ak

    result = {}

    # 涨跌家数统计 (优先使用乐咕乐股源)
    try:
        df = ak.stock_market_activity_legu()
        if df is not None and not df.empty:
            # 乐咕乐股返回格式: item / number
            legu_map = {}
            for _, row in df.iterrows():
                key = str(row.iloc[0]).strip()
                try:
                    val = int(float(row.iloc[1]))
                except (ValueError, TypeError):
                    val = 0
                legu_map[key] = val
            result["up_count"] = legu_map.get("上涨", 0)
            result["down_count"] = legu_map.get("下跌", 0)
            result["flat_count"] = legu_map.get("平盘", 0)
            result["limit_up"] = legu_map.get("涨停", 0)
            result["limit_down"] = legu_map.get("跌停", 0)
    except Exception:
        pass

    # 如果乐咕没有拿到涨跌数据，回退到新浪个股列表
    if result.get("up_count", 0) == 0 and result.get("down_count", 0) == 0:
        try:
            df = ak.stock_zh_a_spot()
            if df is not None and not df.empty:
                pct_col = None
                for c in df.columns:
                    if "涨跌" in str(c) and "幅" in str(c):
                        pct_col = c
                        break
                if pct_col:
                    result["up_count"] = int((df[pct_col] > 0).sum())
                    result["down_count"] = int((df[pct_col] < 0).sum())
                    result["flat_count"] = int((df[pct_col] == 0).sum())
                    result["limit_up"] = int((df[pct_col] >= 9.9).sum())
                    result["limit_down"] = int((df[pct_col] <= -9.9).sum())
        except Exception:
            pass

    # 恐慌指数（涨跌比）
    if result.get("down_count", 0) > 0:
        result["advance_decline_ratio"] = round(
            result["up_count"] / result["down_count"], 2
        )
    else:
        result["advance_decline_ratio"] = None

    return result


@_safe_akshare_call
def get_market_sentiment_history(days: int = 30) -> List[Dict[str, Any]]:
    """
    获取近 N 个交易日市场情绪历史（基于上证指数日线数据作为代理）

    返回按日期升序排列的列表，每条记录含:
      date / close / change_pct / volume / amount
    """
    import akshare as ak

    end = datetime.now(_BJ_TIME)
    start = end - timedelta(days=days + 15)

    try:
        df = ak.stock_zh_index_daily(symbol="sh000001")
    except Exception:
        try:
            df = ak.stock_zh_index_daily_em(symbol="sh000001")
        except Exception:
            logger.warning("无法获取指数历史数据")
            return []

    if df is None or df.empty:
        return []

    date_col = "date" if "date" in df.columns else "日期"
    df[date_col] = pd.to_datetime(df[date_col])
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")
    df = df[(df[date_col] >= start_str) & (df[date_col] <= end_str)]
    df = df.sort_values(date_col)

    if df.empty:
        return []

    results = []
    for _, row in df.iterrows():
        d = str(row[date_col])[:10]
        close_val = float(row.get("close", row.get("收盘", 0)))
        open_val = float(row.get("open", row.get("开盘", 0)))
        high_val = float(row.get("high", row.get("最高", 0)))
        low_val = float(row.get("low", row.get("最低", 0)))
        vol = float(row.get("volume", row.get("成交量", 0)))
        amt = float(row.get("amount", row.get("成交额", 0))) if ("amount" in row or "成交额" in df.columns) else 0

        prev_close = results[-1]["close"] if results else open_val
        chg = round((close_val / prev_close - 1) * 100, 2) if prev_close and prev_close > 0 else 0

        results.append({
            "date": d, "open": open_val, "high": high_val, "low": low_val,
            "close": close_val, "volume": vol, "amount": amt, "change_pct": chg,
        })

    logger.info(f"市场情绪历史: {len(results)} 天 (上证指数)")
    return results


# ============================================================
# 指数数据
# ============================================================

@_safe_akshare_call
def get_index_daily(symbol: str, start_date: str = None,
                    end_date: str = None) -> Optional[pd.DataFrame]:
    """
    获取指数日线数据

    Args:
        symbol: 指数代码，如 "000300" (沪深300), "000001" (上证指数)
    """
    import akshare as ak

    if start_date is None:
        start_date = (datetime.now(_BJ_TIME) - timedelta(days=365)).strftime("%Y%m%d")
    if end_date is None:
        end_date = datetime.now(_BJ_TIME).strftime("%Y%m%d")

    df = ak.stock_zh_index_daily_em(symbol=symbol)
    if df is not None and not df.empty:
        df["日期"] = pd.to_datetime(df["date"] if "date" in df.columns else df["日期"])
        df = df[(df["日期"] >= start_date) & (df["日期"] <= end_date)]
        df = df.sort_values("日期")
    return df


# ============================================================
# 公告与新闻
# ============================================================

@_safe_akshare_call
def get_stock_notices(symbol: str, limit: int = 20) -> Optional[List[Dict]]:
    """获取个股公告"""
    import akshare as ak
    df = ak.stock_notice_report(symbol=symbol)
    if df is not None and not df.empty:
        df = df.head(limit)
        return df.to_dict(orient="records")
    return []


@_safe_akshare_call
def get_cn_stock_news(symbol: str, limit: int = 20) -> Optional[List[Dict]]:
    """获取个股相关新闻（东方财富来源）"""
    import akshare as ak
    try:
        df = ak.stock_news_em(symbol=symbol)
        if df is not None and not df.empty:
            return df.head(limit).to_dict(orient="records")
    except Exception:
        pass
    return []


# ============================================================
# 个股价格历史（用于多日缓存回填）
# ============================================================

def get_stock_price_history(symbol: str, days: int = 30) -> List[Dict]:
    """
    获取个股日线价格历史（裸数据，按日拆分）

    Returns:
        [{"date": "2026-06-18", "open": ..., "close": ..., "volume": ..., "change_pct": ...}, ...]
    """
    end_date = datetime.now(_BJ_TIME).strftime("%Y%m%d")
    start_date = (datetime.now(_BJ_TIME) - timedelta(days=days + 15)).strftime("%Y%m%d")

    df = get_stock_daily(symbol, start_date=start_date, end_date=end_date)
    if df is None or df.empty:
        logger.warning(f"个股价格历史获取失败: {symbol}")
        return []

    results = []
    for _, row in df.iterrows():
        date_val = row.get("date")
        if date_val is None:
            continue
        if hasattr(date_val, "strftime"):
            date_str = date_val.strftime("%Y-%m-%d")
        else:
            date_str = str(date_val)[:10]
        results.append({
            "date": date_str,
            "open": _safe_float(row.get("open")),
            "high": _safe_float(row.get("high")),
            "low": _safe_float(row.get("low")),
            "close": _safe_float(row.get("close")),
            "volume": _safe_float(row.get("volume")),
            "amount": _safe_float(row.get("amount")),
            "change_pct": _safe_float(row.get("pct_change", row.get("change_pct"))),
        })

    results = [r for r in results if r["close"] is not None]
    results.sort(key=lambda r: r["date"], reverse=True)
    return results[:days]


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        import numpy as np
        if np.isnan(f):
            return None
        return f
    except (ValueError, TypeError):
        return None
