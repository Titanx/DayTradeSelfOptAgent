"""
HTTP直连数据源（不回封IP的备用通道）

当 AKShare 底层不稳定时（晚间限流、网络波动），
直接 HTTP 访问腾讯/新浪/东方财富等免费公开接口作为数据回退。

数据源特点:
  - 东方财富 (push2.eastmoney.com): 字段最全，含 PE/PB/流通市值/限价
  - 新浪财经 (hq.sinajs.cn):        轻量，GBK编码，基本字段
  - 腾讯财经 (qt.gtimg.cn):         不封IP，GBK编码，~ 88字段
"""

import urllib.request
import urllib.parse
import json
import time
import random
import logging
from typing import Optional, Dict, List


_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_logger = logging.getLogger(__name__)


def _http_retry(func, max_retries: int = 2):
    """HTTP请求重试装饰器（指数退避，仅对网络/超时异常重试）"""
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(0.5 * (2 ** attempt) + random.uniform(0.1, 0.3))
    _logger.warning(f"HTTP重试{max_retries}次后仍失败: {last_err}")
    return None


def _to_em_secid(symbol: str) -> str:
    """A股代码转东方财富 secid: 1.开头上海/0.开头深圳"""
    if symbol.startswith(("6", "9")):
        return f"1.{symbol}"
    elif symbol.startswith("8"):
        return f"0.{symbol}"  # 北交所
    return f"0.{symbol}"


# ============================================================
# 东方财富直连 (字段最全，含 PE/PB/流通市值/限价)
# ============================================================

def eastmoney_realtime(symbol: str) -> Optional[Dict]:
    """
    东方财富实时行情（push2 接口直连）

    返回字段:
      name, price, last_close, open, high, low,
      amount, volume, turnover_rate, pe_ttm, pb,
      mcap_yi, float_mcap_yi, limit_up, limit_down
    """
    secid = _to_em_secid(symbol)
    fields = ",".join([
        "f57",   # 代码
        "f58",   # 名称
        "f43",   # 最新价
        "f60",   # 昨收
        "f44",   # 最高
        "f45",   # 最低
        "f46",   # 今开
        "f47",   # 成交量(手)
        "f48",   # 成交额
        "f168",  # 换手率
        "f167",  # 市净率
        "f162",  # 市盈率(动态)
        "f116",  # 总市值
        "f117",  # 流通市值
        "f51",   # 涨停价
        "f52",   # 跌停价
    ])
    url = f"http://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields={fields}"

    def _fetch():
        req = urllib.request.Request(url)
        req.add_header("User-Agent", _UA)
        req.add_header("Referer", "https://quote.eastmoney.com/")
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.read().decode("utf-8")

    data = _http_retry(_fetch)
    if data is None:
        return None

    try:
        obj = json.loads(data)
        d = obj.get("data") or {}
        if not d:
            return None

        def _num(key):
            v = d.get(key)
            if v is None or v == "-":
                return 0.0
            try:
                return float(v)
            except (ValueError, TypeError):
                return 0.0

        # 字段含义：f43最新价(需/100)，f44最高/100，f45最低/100，f46今开/100，
        #          f60昨收/100，f47成交量(手)，f48成交额，f168换手率/100，
        #          f167市净率/100，f162市盈率/100，f51涨停价/100，f52跌停价/100
        # 注意：东方财富接口返回的价格字段需要除以100（实际为分）
        return {
            "symbol": symbol,
            "name": d.get("f58") or "",
            "price": _num("f43") / 100,
            "last_close": _num("f60") / 100,
            "open": _num("f46") / 100,
            "high": _num("f44") / 100,
            "low": _num("f45") / 100,
            "volume": _num("f47") * 100,  # 手→股
            "amount": _num("f48"),
            "turnover_pct": _num("f168") / 100,
            "pe_ttm": _num("f162") / 100,
            "pb": _num("f167") / 100,
            "mcap_yi": _num("f116") / 1e8,        # 元→亿元
            "float_mcap_yi": _num("f117") / 1e8,  # 元→亿元
            "limit_up": _num("f51") / 100,
            "limit_down": _num("f52") / 100,
        }
    except (ValueError, KeyError) as e:
        _logger.debug(f"eastmoney_realtime parse fail [{symbol}]: {e}")
        return None


# ============================================================
# 新浪财经直连 (轻量，基本字段)
# ============================================================

def sina_realtime(symbol: str) -> Optional[Dict]:
    """
    新浪财经实时行情 (hq.sinajs.cn)

    返回字段:
      name, price, last_close, open, high, low,
      volume, amount
    """
    prefix = "sh" if symbol.startswith(("6", "9")) else ("bj" if symbol.startswith("8") else "sz")
    url = f"https://hq.sinajs.cn/list={prefix}{symbol}"

    def _fetch():
        req = urllib.request.Request(url)
        req.add_header("User-Agent", _UA)
        req.add_header("Referer", "https://finance.sina.com.cn/")
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.read().decode("gbk")

    data = _http_retry(_fetch)
    if data is None:
        return None

    try:
        # var hq_str_sh600519="贵州茅台,开盘价,昨收价,最新价,最高价,最低价,...";
        if '="' not in data:
            return None
        payload = data.split('="')[1].split('";')[0]
        parts = payload.split(",")
        if len(parts) < 10:
            return None

        def _f(i):
            try:
                return float(parts[i]) if parts[i] else 0.0
            except (ValueError, TypeError):
                return 0.0

        name = parts[0]
        open_p = _f(1)
        last_close = _f(2)
        price = _f(3)
        high = _f(4)
        low = _f(5)
        volume = _f(8)      # 股
        amount = _f(9)      # 元
        change = price - last_close if last_close else 0.0
        change_pct = (change / last_close * 100) if last_close else 0.0

        if price <= 0:
            return None

        return {
            "symbol": symbol,
            "name": name,
            "price": price,
            "last_close": last_close,
            "open": open_p,
            "high": high,
            "low": low,
            "volume": volume,
            "amount": amount,
            "change_amt": change,
            "change_pct": change_pct,
        }
    except (IndexError, ValueError) as e:
        _logger.debug(f"sina_realtime parse fail [{symbol}]: {e}")
        return None


# ============================================================
# 腾讯财经直连 (不封IP，~88字段)
# ============================================================

def tencent_realtime(symbol: str) -> Optional[Dict]:
    """
    腾讯财经实时行情（HTTP直连，不封IP）

    返回字段:
      name, price, last_close, open, high, low,
      amount_wan, turnover_pct, pe_ttm, pb,
      mcap_yi, limit_up, limit_down

    注意: 腾讯接口返回的字段43是振幅%，不是PB（PB在字段46）。
    """
    prefix = "sh" if symbol.startswith(("6", "9")) else ("bj" if symbol.startswith("8") else "sz")
    url = f"https://qt.gtimg.cn/q={prefix}{symbol}"

    def _fetch():
        req = urllib.request.Request(url)
        req.add_header("User-Agent", _UA)
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.read().decode("gbk")

    data = _http_retry(_fetch)
    if data is None:
        return None

    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue

        def _f(i):
            try:
                return float(vals[i]) if vals[i] else 0.0
            except (ValueError, TypeError):
                return 0.0

        return {
            "symbol": symbol,
            "name": vals[1],
            "price": _f(3),
            "last_close": _f(4),
            "open": _f(5),
            "high": _f(33),
            "low": _f(34),
            "change_amt": _f(31),
            "change_pct": _f(32),
            "amount_wan": _f(37),
            "turnover_pct": _f(38),
            "pe_ttm": _f(39),
            "pb": _f(46),
            "mcap_yi": _f(44),
            "float_mcap_yi": _f(45),
            "limit_up": _f(47),
            "limit_down": _f(48),
            "vol_ratio": _f(49),
        }

    return None


def tencent_batch_realtime(codes: list) -> Dict[str, Dict]:
    """
    批量拉取腾讯财经实时行情（一次HTTP请求多只）

    返回: {code: {name, price, change_pct, ...}}
    """
    prefixed = []
    for c in codes:
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)

    def _fetch():
        req = urllib.request.Request(url)
        req.add_header("User-Agent", _UA)
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.read().decode("gbk")

    data = _http_retry(_fetch, max_retries=2)
    if data is None:
        return {}

    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue

        def _f(i):
            try:
                return float(vals[i]) if vals[i] else 0.0
            except (ValueError, TypeError):
                return 0.0

        code = key[2:]
        result[code] = {
            "symbol": code,
            "name": vals[1],
            "price": _f(3),
            "last_close": _f(4),
            "open": _f(5),
            "high": _f(33),
            "low": _f(34),
            "change_amt": _f(31),
            "change_pct": _f(32),
            "amount_wan": _f(37),
            "turnover_pct": _f(38),
            "pe_ttm": _f(39),
            "pb": _f(46),
            "mcap_yi": _f(44),
            "float_mcap_yi": _f(45),
            "limit_up": _f(47),
            "limit_down": _f(48),
            "vol_ratio": _f(49),
        }
    return result
