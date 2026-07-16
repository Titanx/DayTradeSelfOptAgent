"""
批量回填行业板块历史数据（近30天）

通过 stock_board_industry_index_ths 逐板块拉取日线数据，
按日期聚合后写入 market_cache（与 get_sector_boards 同 key）。
"""
import sys
import time
import json
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import akshare as ak
import pandas as pd

from dataflows.market_cache import MarketDataCache
from dataflows.akshare_adapter import get_latest_trade_date

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")
logger = logging.getLogger(__name__)

TODAY = get_latest_trade_date()

# ── 1. 获取板块名称 ──
try:
    names_df = ak.stock_board_industry_name_ths()
    sector_names = names_df["name"].tolist()
except Exception:
    # 回退到本地缓存（路径相对项目根目录，避免硬编码绝对路径）
    cache_path = (Path(__file__).parent.parent / "data" / "market_cache"
                  / f"{TODAY}_get_sector_boards.cache.json")
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    sector_names = list({r["板块"] for r in data})

print(f"📡 {len(sector_names)} 个行业板块, 回填近30天")

# ── 2. 逐板块拉取 ──
start_date = (pd.Timestamp.now() - pd.Timedelta(days=35)).strftime("%Y%m%d")
end_date = pd.Timestamp.now().strftime("%Y%m%d")

per_sector = {}       # sector_name → DataFrame
success = 0
failed = 0

for i, name in enumerate(sector_names):
    try:
        df = ak.stock_board_industry_index_ths(
            symbol=name, start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            # 列名统一
            col_map = {"日期": "date", "收盘价": "close", "成交量": "volume", "成交额": "amount"}
            df = df.rename(columns={c: v for c, v in col_map.items() if c in df.columns})
            df["date"] = df["date"].astype(str).str[:10]
            per_sector[name] = df
            success += 1
            if (i + 1) % 25 == 0:
                print(f"   {i+1}/{len(sector_names)}")
            time.sleep(0.12)
        else:
            failed += 1
    except Exception:
        failed += 1
        continue

print(f"✅ 拉取完成: {success} 成功 / {failed} 失败")

# ── 3. 按日期桶分组，计算涨跌幅 ──
all_dates = set()
for df in per_sector.values():
    all_dates.update(df["date"].tolist())
all_dates = sorted(all_dates)

buckets = {d: [] for d in all_dates}

for name, df in per_sector.items():
    # 计算涨跌幅
    df = df.sort_values("date")
    closes = df["close"].values
    chgs = [0.0]
    for j in range(1, len(closes)):
        if closes[j - 1] and closes[j - 1] > 0:
            chgs.append(round((closes[j] / closes[j - 1] - 1) * 100, 2))
        else:
            chgs.append(0.0)
    df["change_pct"] = chgs

    for _, row in df.iterrows():
        d = row["date"]
        if d in buckets:
            buckets[d].append({
                "板块": name,
                "涨跌幅": row["change_pct"],
                "成交量": float(row.get("volume", 0)),
                "成交额": float(row.get("amount", 0)),
            })

# ── 4. 写入缓存 ──
cache = MarketDataCache.get_instance()
cache.set_trade_date(TODAY)

saved = 0
for date in sorted(buckets.keys()):
    records = buckets[date]
    if not records:
        continue

    # 跳过已有磁盘缓存
    if (cache.cache_dir / f"{date}_get_sector_boards.md").exists():
        continue

    records.sort(key=lambda r: r["涨跌幅"], reverse=True)
    for idx, r in enumerate(records):
        r["序号"] = idx + 1

    key = cache._make_key("get_sector_boards", date)
    cache._memory[key] = records
    cache._save_disk("get_sector_boards", date, records)
    saved += 1

print(f"\n💾 已保存: {saved} 天到 market_cache")
print("📂 文件列表:")
for f in sorted(cache.cache_dir.glob("*_get_sector_boards.md")):
    print(f"   {f.name} ({f.stat().st_size:,} 字节)")
print("✅ 全部完成")
