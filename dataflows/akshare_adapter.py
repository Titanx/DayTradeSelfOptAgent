"""
AKShare A股数据适配器

提供 A股行情、财务数据、技术指标、资金流向、市场情绪等数据接口。
AKShare 是免费开源库，无需 API Key，数据源来自东方财富、新浪财经等。
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
import functools
import logging

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

def get_latest_trade_date() -> str:
    """
    获取最近一个A股交易日日期 (YYYY-MM-DD)。

    逻辑：通过获取上证指数最近K线，取最后一天作为最近交易日。
    如果获取失败，或返回日期距今超过3个自然日，则回退到排除周末的最近工作日。
    """
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol="sh000001")
        if df is not None and not df.empty:
            last_date = pd.to_datetime(df.iloc[-1]["date"])
            trade_date = last_date.strftime("%Y-%m-%d")
            # 如果数据距今超过3天，可能是源端未更新，回退到工作日
            if (datetime.now() - last_date).days <= 3:
                return trade_date
    except Exception:
        pass

    # 回退：排除周末，往前找最近工作日
    today = datetime.now()
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
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

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
    获取A股实时行情快照（多源回退 — 优先单股接口，避免拉取全市场5000+股票）

    Args:
        symbol: 股票代码

    Returns:
        dict with: name, price, change_pct, volume, high, low, open, pre_close
    """
    # 0. 优先用腾讯/新浪单股HTTP接口（轻量级，不拉全市场）
    try:
        from .direct_http import tencent_realtime
        tx = tencent_realtime(symbol)
        if tx and tx.get("price", 0) > 0:
            return {
                "symbol": symbol,
                "name": tx.get("name", ""),
                "price": tx.get("price", 0),
                "change_pct": tx.get("change_pct", 0),
                "change": tx.get("change_amt", 0),
                # NOTE: volume 由 amount/price 反推，为近似值（真实应为 VWAP 除法）
                "volume": int(tx.get("amount_wan", 0) * 10000 / max(tx.get("price", 1), 0.01)),
                "amount": tx.get("amount_wan", 0) * 10000,
                "high": tx.get("high", 0),
                "low": tx.get("low", 0),
                "open": tx.get("open", 0),
                "pre_close": tx.get("last_close", 0),
                "turnover_rate": tx.get("turnover_pct", None),
                "pe": tx.get("pe_ttm", None),
                "total_mv": tx.get("mcap_yi", 0) * 1e8 if tx.get("mcap_yi") else None,
            }
    except Exception:
        pass

    try:
        import akshare as ak
    except ImportError:
        ak = None

    if ak is not None:
        # 1. 尝试东方财富源（全市场快照，作为回退）
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

        # 2. 尝试腾讯源实时行情
        try:
            prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
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

        # 3. 从个股日K线取最近一天数据作为替代
        try:
            prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
            df = ak.stock_zh_a_daily(
                symbol=f"{prefix}{symbol}",
                start_date=(datetime.now() - timedelta(days=7)).strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d"),
                adjust="qfq"
            )
            if df is not None and not df.empty and "date" in df.columns:
                last = df.iloc[-1]
                return {
                    "symbol": symbol,
                    "name": "",
                    "price": float(last.get("close", 0)),
                    "change_pct": float(last.get("pct_change", 0) or 0),
                    "change": float(last.get("change", 0) or 0),
                    "volume": int(float(last.get("volume", 0) or 0)),
                    "amount": float(last.get("amount", 0) or 0),
                    "high": float(last.get("high", 0) or 0),
                    "low": float(last.get("low", 0) or 0),
                    "open": float(last.get("open", 0) or 0),
                    "pre_close": float(last.get("close", 0)) * (1 - float(last.get("pct_change", 0) or 0) / 100) if float(last.get("pct_change", 0) or 0) else float(last.get("close", 0)),
                }
        except Exception:
            pass

    # 4. 腾讯HTTP直连兜底（不封IP，AKShare全挂时最后防线）
    try:
        from .direct_http import tencent_realtime
        rt = tencent_realtime(symbol)
        if rt is not None:
            return {
                "symbol": symbol,
                "name": rt.get("name", ""),
                "price": rt.get("price", 0),
                "change_pct": rt.get("change_pct", 0),
                "change": rt.get("change_amt", 0),
                "volume": 0,
                "amount": rt.get("amount_wan", 0) * 10000 if rt.get("amount_wan") else 0,
                "high": rt.get("high", 0),
                "low": rt.get("low", 0),
                "open": rt.get("open", 0),
                "pre_close": rt.get("last_close", 0),
                "turnover_rate": rt.get("turnover_pct"),
                "pe": rt.get("pe_ttm"),
                "total_mv": rt.get("mcap_yi", 0) * 1e8 if rt.get("mcap_yi") else None,
                "circ_mv": rt.get("float_mcap_yi", 0) * 1e8 if rt.get("float_mcap_yi") else None,
            }
    except Exception:
        pass

    return None


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
        return ak.stock_board_concept_cons_ths()
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

    end = datetime.now()
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
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

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
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days + 15)).strftime("%Y%m%d")

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
