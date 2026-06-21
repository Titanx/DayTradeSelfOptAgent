"""
市场公共数据缓存层

批量分析时，大盘指数、北向资金、行业板块、市场情绪等公共数据
对所有个股都相同，缓存后避免重复拉取，减少 API 请求和等待时间。

缓存策略：
  - 内存缓存：当前会话内即时命中
  - 磁盘缓存：跨会话复用（按交易日分文件存储）
  - TTL 由交易日决定：同一交易日的数据不变
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ============================================================
# 公共数据方法名（与个股代码无关）
# ============================================================
PUBLIC_DATA_METHODS = frozenset({
    "get_market_sentiment",   # 涨跌家数、涨停跌停数、涨跌比
    "get_north_flow",          # 北向资金流向（沪股通净买额）
    "get_sector_boards",       # 行业板块涨跌排行
    "get_concept_boards",      # 概念板块涨跌排行
})

# 部分公共方法需要额外参数
METHOD_EXTRA_ARGS = {
    "get_north_flow": {"days": 10},
}

# ============================================================
# 默认缓存目录
# ============================================================
DEFAULT_CACHE_DIR = Path.home() / ".astock_agent" / "market_cache"


class MarketDataCache:
    """市场公共数据缓存（内存 + 磁盘双层）"""

    _instance: Optional["MarketDataCache"] = None

    @classmethod
    def get_instance(cls) -> "MarketDataCache":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, cache_dir: Path = None):
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory: Dict[str, Any] = {}  # 内存缓存: key → data
        self._trade_date: str = ""

    # -------- 核心 API --------

    def set_trade_date(self, trade_date: str):
        """设置当前交易日（每次批量运行开始时调用）"""
        self._trade_date = trade_date

    def get(self, method: str) -> Optional[Any]:
        """从缓存获取数据（先内存后磁盘）"""
        if not self._trade_date:
            return None

        key = self._make_key(method)

        # 1. 内存缓存
        if key in self._memory:
            logger.info(f"📦 [缓存命中-内存] {method}")
            return self._memory[key]

        # 2. 磁盘缓存
        filepath = self._get_filepath(method)
        if filepath.exists():
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                self._memory[key] = data
                logger.info(f"📦 [缓存命中-磁盘] {method}")
                return data
            except Exception as e:
                logger.warning(f"磁盘缓存读取失败 {method}: {e}")
                return None
        return None

    def set(self, method: str, data: Any):
        """写入缓存（内存 + 磁盘）"""
        if not self._trade_date:
            return

        key = self._make_key(method)
        self._memory[key] = data

        filepath = self._get_filepath(method)
        try:
            filepath.write_text(
                json.dumps(data, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            logger.info(f"💾 [缓存保存] {method}")
        except Exception as e:
            logger.warning(f"磁盘缓存写入失败 {method}: {e}")

    def fetch(self, method: str) -> Optional[Any]:
        """获取或拉取：缓存命中则返回，否则实时拉取并缓存"""
        cached = self.get(method)
        if cached is not None:
            return cached

        # 实时拉取
        logger.info(f"🌐 [实时拉取] {method}...")
        data = self._fetch_raw(method)
        if data is not None:
            self.set(method, data)
        return data

    def preload(self, methods: list = None) -> Dict[str, str]:
        """预加载指定公共数据（一般在批量分析开始时调用一次）"""
        if methods is None:
            methods = list(PUBLIC_DATA_METHODS)

        results = {}
        for method in methods:
            try:
                data = self.fetch(method)
                results[method] = "✅" if data is not None else "❌ 无数据"
            except Exception as e:
                results[method] = f"❌ {e}"
        return results

    def invalidate(self):
        """清空当前交易日的内存缓存（用于强制刷新）"""
        self._memory.clear()
        logger.info("🧹 缓存已失效")

    def is_public_method(self, method: str) -> bool:
        return method in PUBLIC_DATA_METHODS

    # -------- 内部方法 --------

    def _make_key(self, method: str) -> str:
        return f"{self._trade_date}_{method}"

    def _get_filepath(self, method: str) -> Path:
        return self.cache_dir / f"{self._trade_date}_{method}.json"

    def _fetch_raw(self, method: str) -> Optional[Any]:
        """实时拉取原始数据（绕过缓存直接调 AKShare）"""
        try:
            from .akshare_adapter import (
                get_market_sentiment,
                get_north_flow,
                get_sector_boards,
                get_concept_boards,
            )

            if method == "get_market_sentiment":
                return get_market_sentiment()
            elif method == "get_north_flow":
                return get_north_flow(days=10)
            elif method == "get_sector_boards":
                return get_sector_boards()
            elif method == "get_concept_boards":
                return get_concept_boards()
        except Exception as e:
            logger.error(f"实时拉取 {method} 失败: {e}")
            return None
        return None
