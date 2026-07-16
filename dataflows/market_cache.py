"""
市场公共数据缓存层（多日历史）

批量分析时，大盘指数、北向资金、行业板块、市场情绪等公共数据
对所有个股都相同，缓存后避免重复拉取，减少 API 请求和等待时间。

缓存策略：
  - 内存缓存：当前会话内即时命中（原始 Python 对象，效率最高）
  - 磁盘缓存：按交易日分文件存储为 Markdown（人类可读，跨会话持久化）
  - 历史回填：preload 时扫描磁盘已有缓存，自动加载到内存（近期 30 天）
  - TTL 由交易日决定：同一交易日的数据不变
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.utils.md_utils import to_markdown

logger = logging.getLogger(__name__)


def _to_jsonable(obj: Any) -> Any:
    """递归将 DataFrame / Series / numpy 类型转为 JSON 可序列化的 dict/list"""
    if obj is None:
        return None
    try:
        import numpy as np
        import pandas as pd
        if isinstance(obj, pd.DataFrame):
            return _to_jsonable(obj.replace({np.nan: None}).to_dict(orient="records"))
        if isinstance(obj, pd.Series):
            return _to_jsonable(obj.replace({np.nan: None}).to_dict())
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            if np.isnan(obj):
                return None
            return float(obj)
        if isinstance(obj, np.ndarray):
            return _to_jsonable(obj.tolist())
    except ImportError:
        pass
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, (int, float, str, bool)):
        return obj
    return str(obj)


# ============================================================
# 公共数据方法名（与个股代码无关）
# ============================================================
PUBLIC_DATA_METHODS = frozenset({
    "get_market_sentiment",   # 涨跌家数、涨停跌停数、涨跌比
    "get_north_flow",          # 北向资金流向（沪股通净买额）
    "get_sector_boards",       # 行业板块涨跌排行
    "get_concept_boards",      # 概念板块涨跌排行
    "get_sector_fund_flow",    # 板块资金流排名 (EvoSkill v0.3)
})

# 支持多日历史缓存的方法
#   get_market_sentiment: 用上证指数日线一次性拉30天
#   get_sector_boards:  只能获取当日快照，历史靠每天运行自动累积磁盘
#   get_north_flow:     只能获取当日快照，历史靠每天运行自动累积磁盘
HISTORY_ENABLED_METHODS = frozenset({
    "get_market_sentiment",
    "get_sector_boards",
    "get_north_flow",
})

METHOD_HISTORY_DAYS = {
    "get_market_sentiment": 30,
    "get_sector_boards": 30,
    "get_north_flow": 30,
}

# 方法名 → 中文标题
METHOD_TITLES = {
    "get_market_sentiment": "市场情绪数据",
    "get_north_flow": "北向资金流向",
    "get_sector_boards": "行业板块排行",
    "get_concept_boards": "概念板块排行",
    "get_sector_fund_flow": "板块资金流排名",
    "get_opinion_report": "个股舆论情绪报告",
    "get_xueqiu_hot_posts": "雪球热门帖子",
    "get_stock_price_data": "个股行情数据",
    "get_stock_realtime_quote": "个股实时行情",
    "get_stock_financials": "个股财务指标",
    "price_daily": "个股日线行情",
}


class MarketDataCache:
    """市场公共数据缓存（内存 + Markdown 磁盘双层，支持多日历史）"""

    _instance: Optional["MarketDataCache"] = None

    # ---------- 单例 ----------
    @classmethod
    def get_instance(cls) -> "MarketDataCache":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, cache_dir: Path = None, opinion_cache_dir: Path = None, stock_cache_dir: Path = None):
        _proj = Path(__file__).parent.parent
        _data = _proj / "data"
        self.cache_dir = Path(cache_dir) if cache_dir else (_data / "market_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.opinion_cache_dir = Path(opinion_cache_dir) if opinion_cache_dir else (_data / "opinion_cache")
        self.opinion_cache_dir.mkdir(parents=True, exist_ok=True)
        self.stock_cache_dir = Path(stock_cache_dir) if stock_cache_dir else (_data / "stock_cache")
        self.stock_cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory: Dict[str, Any] = {}
        self._opinion_memory: Dict[str, Any] = {}
        self._stock_memory: Dict[str, Any] = {}
        self._trade_date: str = ""

    # ================================================================
    # 核心 API
    # ================================================================

    def set_trade_date(self, trade_date: str):
        self._trade_date = trade_date

    def get_trade_date(self) -> str:
        """获取当前缓存交易日（若未设置则返回空字符串）"""
        return self._trade_date

    def get_public_data(self, key: str) -> Optional[Any]:
        """通用键值缓存（不限 method 语义，任意 key → 内存+磁盘回退）"""
        if key in self._memory:
            return self._memory[key]
        json_path = self.cache_dir / f"{key}.cache.json"
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                self._memory[key] = data
                return data
            except Exception:
                pass
        return None

    def store_public_data(self, key: str, data: Any):
        """通用键值缓存写入（内存+JSON磁盘）"""
        self._memory[key] = data
        json_path = self.cache_dir / f"{key}.cache.json"
        try:
            json_path.write_text(
                json.dumps(_to_jsonable(data), ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"公共数据缓存写入失败 {key}: {e}")

    def get(self, method: str, date: str = None) -> Optional[Any]:
        """从缓存获取数据（内存 → 磁盘回退）"""
        date = date or self._trade_date
        if not date:
            return None

        key = self._make_key(method, date)
        if key in self._memory:
            logger.info(f"📦 [缓存命中-内存] {date} {method}")
            return self._memory[key]

        # 磁盘回退
        data = self._load_disk(method, date)
        if data is not None:
            self._memory[key] = data
            logger.info(f"📦 [缓存命中-磁盘] {date} {method}")
            return data
        return None

    def set(self, method: str, data: Any, date: str = None):
        """写入缓存（内存 + Markdown 磁盘），可按任意日期存储"""
        date = date or self._trade_date
        if not date:
            return

        key = self._make_key(method, date)
        self._memory[key] = data
        self._save_disk(method, date, data)

    def fetch(self, method: str) -> Optional[Any]:
        """获取或拉取：缓存命中则返回，否则实时拉取并缓存"""
        cached = self.get(method)
        if cached is not None:
            return cached

        logger.info(f"🌐 [实时拉取] {method}...")
        data = self._fetch_raw(method)
        if data is not None:
            self.set(method, data)
        return data

    def preload(self, methods: list = None, symbols: list = None):
        """
        预加载公共数据（含历史回填 + 个股缓存恢复）

        流程：
        1. 扫描已有磁盘缓存 → 加载到内存（跨会话复用）
        2. 实时拉取今天缺失的数据 → 写内存+磁盘
        3. 对历史类数据（市场情绪等），拉取多日数据 → 分日写磁盘
        4. 个股舆情缓存恢复
        5. 个股行情/财务缓存恢复（需传入 symbols）
        """
        if methods is None:
            methods = list(PUBLIC_DATA_METHODS)

        # Step 1: 扫描磁盘已有缓存，加载到内存
        for method in methods:
            n = self._load_history_from_disk(method)
            if n:
                logger.info(f"📂 [历史加载] {method}: 从磁盘恢复 {n} 天缓存")

        # Step 2: 实时拉取今天的缺失数据
        results = {}
        for method in methods:
            if self.get(method):
                results[method] = "✅ 已有"
                continue
            try:
                data = self.fetch(method)
                results[method] = "✅" if data is not None else "❌ 无数据"
            except Exception as e:
                results[method] = f"❌ {e}"

        # Step 3: 历史回填（一次拉多天，按日分文件保存）
        for method in methods:
            if method in HISTORY_ENABLED_METHODS:
                days = METHOD_HISTORY_DAYS.get(method, 30)
                try:
                    self._backfill_history(method, days)
                    results[method] += f" +历史{min(days,self._count_disk(method))}天"
                except Exception as e:
                    logger.warning(f"历史回填失败 {method}: {e}")

        # Step 4: 个股舆情缓存恢复
        self.preload_opinions()

        # Step 5: 个股行情/财务缓存恢复
        if symbols:
            self.preload_stock_data(symbols)

        # Step 6: 个股价格历史加载 + 回填
        if symbols:
            n = self.load_stock_price_history(symbols, days=30)
            if n:
                logger.info(f"📂 [个股价格历史] 从磁盘恢复 {n} 条日线数据")
            n_new = 0
            try:
                self._backfill_stock_prices(symbols, days=30)
            except Exception as e:
                logger.warning(f"个股价格历史回填失败: {e}")

        return results

    def load_history(self, method: str, days: int = 30) -> int:
        """加载指定方法的近期历史（先磁盘后实时）"""
        n_disk = self._load_history_from_disk(method, days)
        try:
            self._backfill_history(method, days)
        except Exception:
            pass
        return self._count_memory(method)

    def get_history(self, method: str, days: int = 30) -> List[Dict]:
        """获取指定方法的多日历史（按日期升序）"""
        results = []
        for key, value in self._memory.items():
            if method in key:
                try:
                    date_str = key.split("_")[0]
                    results.append({"date": date_str, "data": value})
                except Exception:
                    pass
        results.sort(key=lambda x: x["date"])
        return results[-days:] if len(results) > days else results

    def list_cached_dates(self, method: str) -> List[str]:
        """列出某方法所有已缓存的日期（内存+磁盘）"""
        dates = set()
        # 内存
        for key in self._memory:
            if method in key:
                dates.add(key.split("_")[0])
        # 磁盘
        for f in self.cache_dir.glob(f"*_{method}.md"):
            dates.add(f.name.split("_")[0])
        for f in self.opinion_cache_dir.glob(f"*_{method}.md"):
            dates.add(f.name.split("_")[0])
        return sorted(dates)

    def invalidate(self):
        self._memory.clear()
        logger.info("🧹 内存缓存已失效")

    def is_public_method(self, method: str) -> bool:
        return method in PUBLIC_DATA_METHODS

    # ================================================================
    # 个股舆情缓存
    # ================================================================

    def get_opinion(self, symbol: str, method: str) -> Optional[Any]:
        if not self._trade_date:
            return None
        key = self._make_opinion_key(symbol, method)
        if key in self._opinion_memory:
            logger.info(f"📦 [舆情缓存命中-内存] {symbol} {method}")
            return self._opinion_memory[key]

        # 磁盘回退
        data = self._load_opinion_disk(symbol, method)
        if data is not None:
            self._opinion_memory[key] = data
            logger.info(f"📦 [舆情缓存命中-磁盘] {symbol} {method}")
            return data
        return None

    def set_opinion(self, symbol: str, method: str, data: Any):
        if not self._trade_date:
            return
        key = self._make_opinion_key(symbol, method)
        self._opinion_memory[key] = data

        filepath = self._get_opinion_filepath(symbol, method)
        title = METHOD_TITLES.get(method, method)

        # MD 人类可读
        try:
            filepath.write_text(to_markdown(data, f"{title} — {symbol} ({self._trade_date})"), encoding="utf-8")
        except Exception as e:
            logger.warning(f"舆情 MD 写入失败 {symbol} {method}: {e}")

        # JSON 跨会话恢复
        json_path = filepath.with_suffix(".cache.json")
        try:
            json_path.write_text(
                json.dumps(_to_jsonable(data), ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(f"💾 [舆情缓存保存] {symbol} {method}")
        except Exception as e:
            logger.warning(f"舆情 JSON 写入失败 {symbol} {method}: {e}")

    def preload_opinions(self):
        """扫描磁盘已有舆情缓存，加载到内存（跨会话恢复）"""
        if not self._trade_date:
            return
        count = 0
        for f in sorted(self.opinion_cache_dir.glob(f"*/{self._trade_date}_*.md")):
            try:
                symbol = f.parent.name
                method = f.stem.split("_", 1)[1] if "_" in f.stem else f.stem
                date_str = self._trade_date
                key = self._make_opinion_key(symbol, method)
                if key in self._opinion_memory:
                    continue
                data = self._load_opinion_disk(symbol, method)
                if data is not None:
                    self._opinion_memory[key] = data
                    count += 1
            except Exception:
                pass
        if count:
            logger.info(f"📂 [舆情历史加载] 从磁盘恢复 {count} 条舆情缓存")

    def _load_opinion_disk(self, symbol: str, method: str) -> Optional[Any]:
        """从磁盘还原舆情缓存（.cache.json）"""
        filepath = self._get_opinion_filepath(symbol, method)
        json_path = filepath.with_suffix(".cache.json")
        if json_path.exists():
            try:
                return json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return None

    def invalidate_opinion(self, symbol: str = None):
        if symbol:
            keys_to_del = [k for k in self._opinion_memory if symbol in k]
            for k in keys_to_del:
                del self._opinion_memory[k]
        else:
            self._opinion_memory.clear()
        logger.info("🧹 舆情缓存已失效")

    # ================================================================
    # 个股行情/财务数据缓存
    # ================================================================

    STOCK_CACHE_METHODS = frozenset({
        "get_stock_price_data",
        "get_stock_realtime_quote",
        "get_stock_financials",
    })

    def get_stock_data(self, symbol: str, method: str) -> Optional[Any]:
        """从缓存获取个股数据（内存 → 磁盘回退）"""
        if not self._trade_date:
            return None
        key = self._make_stock_key(symbol, method)
        if key in self._stock_memory:
            logger.info(f"📦 [个股缓存命中-内存] {symbol} {method}")
            return self._stock_memory[key]

        data = self._load_stock_disk(symbol, method)
        if data is not None:
            self._stock_memory[key] = data
            logger.info(f"📦 [个股缓存命中-磁盘] {symbol} {method}")
            return data
        return None

    def set_stock_data(self, symbol: str, method: str, data: Any, skip_disk: bool = False):
        """写入个股缓存（内存 + MD + JSON）

        Args:
            symbol: 股票代码
            method: 方法名
            data: 数据
            skip_disk: 若为 True，仅更新内存缓存，不写入磁盘。
                       用于盘中实时行情：盘中价格不是收盘数据，
                       写入磁盘会污染收盘数据缓存（C8 修复）。
        """
        if not self._trade_date:
            return
        key = self._make_stock_key(symbol, method)
        self._stock_memory[key] = data

        # 盘中实时价不写磁盘：避免污染收盘数据缓存
        if skip_disk:
            logger.info(f"📦 [个股缓存-仅内存] {symbol} {method}（盘中，不写磁盘）")
            return

        filepath = self._get_stock_filepath(symbol, method)
        title = METHOD_TITLES.get(method, method)

        try:
            filepath.write_text(to_markdown(data, f"{title} — {symbol} ({self._trade_date})"), encoding="utf-8")
        except Exception as e:
            logger.warning(f"个股 MD 写入失败 {symbol} {method}: {e}")

        json_path = filepath.with_suffix(".cache.json")
        try:
            json_path.write_text(
                json.dumps(_to_jsonable(data), ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(f"💾 [个股缓存保存] {symbol} {method}")
        except Exception as e:
            logger.warning(f"个股 JSON 写入失败 {symbol} {method}: {e}")

    def preload_stock_data(self, symbols: list = None):
        """扫描磁盘已有个股缓存，加载到内存（跨会话恢复）"""
        if not self._trade_date:
            return
        count = 0
        for f in sorted(self.stock_cache_dir.glob(f"*/{self._trade_date}_*.md")):
            try:
                symbol = f.parent.name
                method = f.stem.split("_", 1)[1] if "_" in f.stem else f.stem
                if symbols and symbol not in symbols:
                    continue
                if method not in self.STOCK_CACHE_METHODS:
                    continue
                key = self._make_stock_key(symbol, method)
                if key in self._stock_memory:
                    continue
                data = self._load_stock_disk(symbol, method)
                if data is not None:
                    self._stock_memory[key] = data
                    count += 1
            except Exception:
                pass
        if count:
            logger.info(f"📂 [个股缓存加载] 从磁盘恢复 {count} 条个股缓存")

    def _make_stock_key(self, symbol: str, method: str) -> str:
        return f"{self._trade_date}_{symbol}_{method}"

    def _get_stock_filepath(self, symbol: str, method: str) -> Path:
        dirpath = self.stock_cache_dir / symbol
        dirpath.mkdir(parents=True, exist_ok=True)
        return dirpath / f"{self._trade_date}_{method}.md"

    def _load_stock_disk(self, symbol: str, method: str) -> Optional[Any]:
        filepath = self._get_stock_filepath(symbol, method)
        json_path = filepath.with_suffix(".cache.json")
        if json_path.exists():
            try:
                return json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return None

    def invalidate_stock(self, symbol: str = None):
        """失效个股缓存（内存 + 磁盘）"""
        if symbol:
            keys_to_del = [k for k in self._stock_memory if symbol in k]
            for k in keys_to_del:
                del self._stock_memory[k]
            # 清磁盘：删除该 symbol 的整个目录
            symbol_dir = self.stock_cache_dir / symbol
            if symbol_dir.exists():
                import shutil
                shutil.rmtree(symbol_dir, ignore_errors=True)
        else:
            self._stock_memory.clear()
            # 清磁盘：删除所有 symbol 子目录
            if self.stock_cache_dir.exists():
                import shutil
                for d in self.stock_cache_dir.iterdir():
                    if d.is_dir():
                        shutil.rmtree(d, ignore_errors=True)
        logger.info("🧹 个股缓存已失效 (内存+磁盘)")

    # ================================================================
    # 内部: key / 文件路径
    # ================================================================

    def _make_key(self, method: str, date: str = None) -> str:
        return f"{date or self._trade_date}_{method}"

    def _get_filepath(self, method: str, date: str = None) -> Path:
        return self.cache_dir / f"{date or self._trade_date}_{method}.md"

    def _make_opinion_key(self, symbol: str, method: str) -> str:
        return f"{self._trade_date}_{symbol}_{method}"

    def _get_opinion_filepath(self, symbol: str, method: str) -> Path:
        dirpath = self.opinion_cache_dir / symbol
        dirpath.mkdir(parents=True, exist_ok=True)
        return dirpath / f"{self._trade_date}_{method}.md"

    # ================================================================
    # 内部: 磁盘读写
    # ================================================================

    def _save_disk(self, method: str, date: str, data: Any):
        """写入 MD（人类可读）+ JSON（跨会话恢复）"""
        md_path = self._get_filepath(method, date)
        json_path = md_path.with_suffix(".cache.json")

        # MD 给人类看
        title = METHOD_TITLES.get(method, method)
        try:
            md_path.write_text(to_markdown(data, f"{title} — {date}"), encoding="utf-8")
        except Exception as e:
            logger.warning(f"MD 写入失败 {date} {method}: {e}")

        # JSON 给程序恢复（DataFrame → list[dict]）
        try:
            json_path.write_text(
                json.dumps(_to_jsonable(data), ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(f"💾 [缓存保存] {date} {method}")
        except Exception as e:
            logger.warning(f"JSON 写入失败 {date} {method}: {e}")

    def _load_disk(self, method: str, date: str) -> Optional[Any]:
        """从磁盘还原原始 Python 对象（优先 .cache.json，兼容旧 .json）"""
        md_path = self._get_filepath(method, date)

        # 新格式 .cache.json（与 MD 并行）
        json_path = md_path.with_suffix(".cache.json")
        if json_path.exists():
            try:
                return json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        # 兼容旧格式 .json（迁移前遗留）
        old_json = md_path.with_suffix(".json")
        if old_json.exists():
            try:
                return json.loads(old_json.read_text(encoding="utf-8"))
            except Exception:
                pass

        return None

    def _load_history_from_disk(self, method: str, days: int = 30) -> int:
        """从磁盘加载指定方法的近期缓存到内存（日期由文件名解析）"""
        count = 0
        for f in sorted(self.cache_dir.glob(f"*_{method}.md"), reverse=True):
            try:
                date_str = f.name.split("_")[0]
                if len(date_str) != 10:
                    continue
                key = self._make_key(method, date_str)
                if key in self._memory:
                    continue
                data = self._load_disk(method, date_str)
                if data is not None:
                    self._memory[key] = data
                    count += 1
                if count >= days:
                    break
            except Exception:
                pass
        return count

    def _count_disk(self, method: str) -> int:
        return len(list(self.cache_dir.glob(f"*_{method}.md")))

    def _count_memory(self, method: str) -> int:
        return sum(1 for k in self._memory if method in k)

    # ================================================================
    # 内部: 历史回填（一次拉多天，按日分文件保存）
    # ================================================================

    def _backfill_history(self, method: str, days: int = 30):
        if method == "get_market_sentiment":
            self._backfill_market_sentiment(days)
        elif method == "get_sector_boards":
            self._backfill_sector_boards(days)
        elif method == "get_north_flow":
            self._backfill_north_flow(days)

    def _backfill_market_sentiment(self, days: int = 30):
        """拉取近 N 天市场情绪数据，分日存入缓存"""
        try:
            from .akshare_adapter import get_market_sentiment_history
            history = get_market_sentiment_history(days=days)
        except Exception as e:
            logger.warning(f"拉取市场情绪历史失败: {e}")
            return

        if not history:
            return

        for item in history:
            date = item.get("date", "")
            if not date:
                continue
            key = self._make_key("get_market_sentiment", date)
            if key in self._memory:
                continue
            self._memory[key] = item
            self._save_disk("get_market_sentiment", date, item)

        logger.info(f"📅 [历史回填] get_market_sentiment: {len(history)} 天")

    def _backfill_sector_boards(self, days: int = 30):
        """行业板块每日快照 — 历史靠每天运行自动累积磁盘，_load_history_from_disk 已恢复存量"""
        existing = self._count_disk("get_sector_boards")
        if existing > 0:
            logger.info(f"📅 [历史回填] get_sector_boards: 磁盘已有 {existing} 天，随每日运行累积")

    def _backfill_north_flow(self, days: int = 30):
        """北向资金每日快照 — 历史靠每天运行自动累积磁盘，_load_history_from_disk 已恢复存量"""
        existing = self._count_disk("get_north_flow")
        if existing > 0:
            logger.info(f"📅 [历史回填] get_north_flow: 磁盘已有 {existing} 天，随每日运行累积")

    def _backfill_stock_prices(self, symbols: list, days: int = 30):
        """拉取个股日线历史，按交易日分文件存入 stock_cache

        注意：price_daily 的 key 和文件名只用 K 线日期（date），不含 trade_date，
        避免同一份历史数据因运行日期不同而被重复存储。
        """
        from .akshare_adapter import get_stock_price_history

        for symbol in symbols:
            try:
                history = get_stock_price_history(symbol, days=days)
            except Exception as e:
                logger.warning(f"个股价格历史获取失败 {symbol}: {e}")
                continue

            saved = 0
            for item in history:
                date = item.get("date", "")
                if not date:
                    continue
                # price_daily 的 key 只用 date，不含 trade_date
                key = f"price_daily_{symbol}_{date}"
                if key in self._stock_memory:
                    continue
                # 文件名也只用 date，不含 trade_date
                dirpath = self.stock_cache_dir / symbol
                dirpath.mkdir(parents=True, exist_ok=True)
                filepath = dirpath / f"price_daily_{date}.md"
                if filepath.with_suffix(".cache.json").exists():
                    continue

                self._stock_memory[key] = item
                title = METHOD_TITLES.get("price_daily", "个股日线行情")
                try:
                    filepath.write_text(
                        to_markdown(item, f"{title} — {symbol} ({date})"),
                        encoding="utf-8",
                    )
                    filepath.with_suffix(".cache.json").write_text(
                        json.dumps(_to_jsonable(item), ensure_ascii=False),
                        encoding="utf-8",
                    )
                    saved += 1
                except Exception as e:
                    logger.warning(f"个股价格写入失败 {symbol} {date}: {e}")

            if saved:
                logger.info(f"📅 [个股价格历史回填] {symbol}: {saved} 天")

    def load_stock_price_history(self, symbols: list, days: int = 30) -> int:
        """从磁盘加载指定个股的近期价格历史到内存"""
        count = 0
        for symbol in symbols:
            sdir = self.stock_cache_dir / symbol
            if not sdir.exists():
                continue
            # 文件名格式：price_daily_{date}.md（不含 trade_date）
            for f in sorted(sdir.glob("price_daily_*.md"), reverse=True):
                try:
                    date_str = f.stem.replace("price_daily_", "")
                    key = f"price_daily_{symbol}_{date_str}"
                    if key in self._stock_memory:
                        continue
                    json_path = f.with_suffix(".cache.json")
                    if json_path.exists():
                        data = json.loads(json_path.read_text(encoding="utf-8"))
                        if data is not None:
                            self._stock_memory[key] = data
                            count += 1
                    if count >= days * len(symbols):
                        return count
                except Exception:
                    pass
        return count

    # ================================================================
    # 磁盘缓存清理
    # ================================================================

    def cleanup_disk_cache(self, keep_days: int = 30) -> dict:
        """清理过期磁盘缓存文件，保留最近 keep_days 天。

        清理三个缓存目录：market_cache（公共）、opinion_cache（舆情）、stock_cache（个股）。
        price_daily 文件按文件名中的 date 判断，其他文件按文件修改时间判断。

        Args:
            keep_days: 保留最近多少天的缓存

        Returns:
            {"market": int, "opinion": int, "stock": int} 各目录删除的文件数
        """
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=keep_days)
        deleted = {"market": 0, "opinion": 0, "stock": 0}

        # 1. market_cache：按文件修改时间清理
        if self.market_cache_dir.exists():
            for f in self.market_cache_dir.glob("*"):
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if mtime < cutoff:
                        f.unlink(missing_ok=True)
                        deleted["market"] += 1
                except Exception:
                    pass

        # 2. opinion_cache：按文件修改时间清理
        if self.opinion_cache_dir.exists():
            for f in self.opinion_cache_dir.glob("*"):
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if mtime < cutoff:
                        f.unlink(missing_ok=True)
                        deleted["opinion"] += 1
                except Exception:
                    pass

        # 3. stock_cache：price_daily 按 date 清理，其他按 mtime
        if self.stock_cache_dir.exists():
            for symbol_dir in self.stock_cache_dir.iterdir():
                if not symbol_dir.is_dir():
                    continue
                for f in symbol_dir.glob("*"):
                    try:
                        # price_daily 文件名含 date，优先用 date 判断
                        if f.stem.startswith("price_daily_"):
                            date_str = f.stem.replace("price_daily_", "")
                            try:
                                file_date = datetime.strptime(date_str, "%Y-%m-%d")
                                if file_date < cutoff:
                                    f.unlink(missing_ok=True)
                                    deleted["stock"] += 1
                                continue
                            except ValueError:
                                pass
                        # 其他文件按 mtime 判断
                        mtime = datetime.fromtimestamp(f.stat().st_mtime)
                        if mtime < cutoff:
                            f.unlink(missing_ok=True)
                            deleted["stock"] += 1
                    except Exception:
                        pass

        total = sum(deleted.values())
        if total > 0:
            logger.info(f"🧹 磁盘缓存清理: 删除 {total} 个过期文件 (>={keep_days}天) {deleted}")
        return deleted

    # ================================================================
    # 内部: 实时拉取
    # ================================================================

    def _fetch_raw(self, method: str) -> Optional[Any]:
        try:
            from .akshare_adapter import (
                get_market_sentiment,
                get_north_flow,
                get_sector_boards,
                get_concept_boards,
                get_sector_fund_flow,
            )
            if method == "get_market_sentiment":
                return get_market_sentiment()
            elif method == "get_north_flow":
                return get_north_flow(days=10)
            elif method == "get_sector_boards":
                return get_sector_boards()
            elif method == "get_concept_boards":
                return get_concept_boards()
            elif method == "get_sector_fund_flow":
                return get_sector_fund_flow()
        except Exception as e:
            logger.error(f"实时拉取 {method} 失败: {e}")
            return None
        return None
