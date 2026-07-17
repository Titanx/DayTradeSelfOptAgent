"""market_overview.py — 大盘 + 板块数据预加载

在批量分析前运行一次，将共享数据注入 AgentState，
避免每个股票的分析师重复调用 akshare 拉取相同的大盘/板块数据。

数据内容:
  1. 三大指数 (上证/深证/创业板) 今日行情
  2. 市场情绪 (涨跌家数/涨跌停)
  3. 北向资金
  4. 5个板块的行业指数 (光伏/风电/AI/储能/视觉)

用法:
  python scripts/market_overview.py 2026-06-26
  → 输出 data/overview_cache/2026-06-26_overview.json
"""

import json, sys, logging
from pathlib import Path
from datetime import datetime

project_dir = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_dir))
sys.path.insert(0, str(project_dir / "libs"))

from dotenv import load_dotenv
load_dotenv(project_dir / ".env", override=True)

logging.basicConfig(level=logging.WARNING)

from dataflows.market_cache import MarketDataCache
from dataflows.interface import route_to_vendor
# L: 时间戳统一用北京时间（与 akshare_adapter H6 修复保持一致）
from dataflows.akshare_adapter import _BJ_TIME

CACHE_DIR = project_dir / "data" / "overview_cache"

MAJOR_INDICES = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
]

SECTOR_BOARDS = {
    "光伏": "BK0447",
    "风电": "BK0443",
    "AI": "BK0734",
    "储能": "BK0602",
    "视觉": "BK0621",
}


def fetch_market_overview(trade_date: str) -> dict:
    """拉取大盘 + 板块全景数据。

    Returns:
        {
            "trade_date": "2026-06-26",
            "indices": { "上证指数": {...}, ... },
            "market_sentiment": "...",
            "north_flow": "...",
            "sector_boards": { "光伏": {"board_name":"...", "pct_chg":...}, ... },
            "generated_at": "2026-06-26T18:00:00"
        }
    """
    cache = MarketDataCache.get_instance()
    cache.set_trade_date(trade_date)

    overview = {"trade_date": trade_date, "generated_at": datetime.now(_BJ_TIME).isoformat()}

    # 1. 市场情绪 (涨跌家数, 涨跌停)
    sentiment = cache.fetch("get_market_sentiment")
    if sentiment:
        overview["market_sentiment"] = str(sentiment)[:2000]
    else:
        overview["market_sentiment"] = "(获取失败)"

    # 2. 北向资金
    north = cache.fetch("get_north_flow")
    if hasattr(north, "__len__") and len(north) > 0:
        overview["north_flow"] = str(north)[:2000]
    else:
        overview["north_flow"] = "(获取失败)"

    # 3. 行业板块列表 (找对应板块的涨跌幅)
    sector_data = {}
    try:
        cache.fetch("get_sector_boards")
        boards = cache.get("get_sector_boards")
        if boards:
            if isinstance(boards, str):
                for sector_name, board_code in SECTOR_BOARDS.items():
                    if board_code in boards:
                        sector_data[sector_name] = {"board_code": board_code, "found": True}
                    else:
                        sector_data[sector_name] = {"board_code": board_code, "found": False}
            elif isinstance(boards, (list, dict)):
                for sector_name, board_code in SECTOR_BOARDS.items():
                    sector_data[sector_name] = {"board_code": board_code, "detail": "见原始数据"}
    except Exception as e:
        logging.warning(f"Sector boards failed: {e}")

    overview["sector_boards"] = sector_data

    # 4. 三大指数日线 (拉最近5天)
    indices = {}
    for idx_code, idx_name in MAJOR_INDICES:
        try:
            df = route_to_vendor("get_index_daily", idx_code, config={}, max_retries=1)
            if df is not None and len(df) > 0:
                last = df.iloc[-1]
                indices[idx_name] = {
                    "code": idx_code,
                    "close": float(last["close"]),
                    "pct_chg": float(last.get("pct_chg", 0)),
                    "volume": float(last.get("volume", 0)),
                }
        except Exception as e:
            indices[idx_name] = {"code": idx_code, "error": str(e)[:100]}
    overview["indices"] = indices

    return overview


def load_overview(trade_date: str) -> dict:
    """从缓存加载 (优先), 缓存不存在则拉取。

    同时预热 MarketDataCache 的公共数据，后续个股分析直接命中缓存。
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{trade_date}_overview.json"

    if cache_file.exists():
        return json.loads(cache_file.read_text("utf-8"))

    print(f"🌐 拉取大盘数据: {trade_date} ...")
    overview = fetch_market_overview(trade_date)
    cache_file.write_text(json.dumps(overview, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 大盘数据已缓存: {cache_file}")
    parts = []
    for k, v in overview['indices'].items():
        if 'close' in v:
            parts.append(f"{k}({v['close']} {v['pct_chg']:+.2f}%)")
    print(f"   指数: {', '.join(parts)}")
    return overview


def overview_to_prompt(overview: dict, sector: str = "") -> str:
    """将大盘数据转为分析师可用的文本片段，注入到 AgentState。

    Args:
        overview: load_overview 的输出
        sector: 如果指定, 追加板块特定信息
    """
    parts = ["## 今日大盘概览\n"]

    indices = overview.get("indices", {})
    if indices:
        for name, info in indices.items():
            if "close" in info:
                parts.append(f"- {name}: {info['close']:.2f} ({info['pct_chg']:+.2f}%)")

    sentiment = overview.get("market_sentiment", "")
    if sentiment and sentiment != "(获取失败)":
        parts.append(f"\n### 市场情绪\n{sentiment[:600]}\n")

    north = overview.get("north_flow", "")
    if north and north != "(获取失败)":
        parts.append(f"\n### 北向资金\n{north[:400]}\n")

    if sector:
        sector_info = overview.get("sector_boards", {}).get(sector, {})
        if sector_info:
            parts.append(f"\n### {sector}板块\n板块代码: {sector_info.get('board_code', '?')}")

    return "\n".join(parts)


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else "2026-06-26"
    overview = load_overview(d)
    prompt = overview_to_prompt(overview, "光伏")
    print("\n--- 注入 Prompt 预览 ---")
    print(prompt[:800])
