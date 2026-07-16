"""
HTTP直连数据源（不回封IP的备用通道）

当 AKShare 底层不稳定时（晚间限流、网络波动），
直接 HTTP 访问腾讯/新浪等免费公开接口作为数据回退。

数据源特点:
  - 腾讯财经 (qt.gtimg.cn): 不封IP，GBK编码，~ 88字段
  - 新浪财经 (quotes.sina.cn): 财报三表
"""

import urllib.request
import time
import random
import logging
from typing import Optional, Dict


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
