"""
AStockAgent 默认配置

三层配置优先级：
  1. DEFAULT_CONFIG 硬编码默认值
  2. ASTOCK_* 环境变量覆盖
  3. 运行时 set_config() 编程式覆盖
"""

import os
import copy
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(override=True)

# ============================================================
# 项目路径（所有缓存/结果/记忆均存放在项目目录 data/ 下）
# ============================================================
PROJECT_DIR = Path(__file__).parent.parent.resolve()
DATA_DIR = PROJECT_DIR / "data"
RESULTS_DIR = DATA_DIR / "results"
MEMORY_LOG_PATH = DATA_DIR / "memory" / "trading_memory.md"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
OPINION_CACHE_DIR = DATA_DIR / "opinion_cache"
MARKET_CACHE_DIR = DATA_DIR / "market_cache"
DATA_CACHE_DIR = DATA_DIR / "data_cache"
BATCH_RESULTS_DIR = DATA_DIR / "batch_results"

for d in [
    RESULTS_DIR, MEMORY_LOG_PATH.parent, CHECKPOINT_DIR,
    OPINION_CACHE_DIR, MARKET_CACHE_DIR, DATA_CACHE_DIR, BATCH_RESULTS_DIR,
]:
    try:
        d.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError):
        pass

# ============================================================
# 默认配置
# ============================================================
DEFAULT_CONFIG = {
    # --- LLM 配置 ---
    "llm_provider": "deepseek",          # openai / anthropic / google / deepseek / qwen / glm / ollama
    "deep_think_llm": "deepseek-chat",    # 深度推理模型（研究经理/投资经理）
    "quick_think_llm": "deepseek-chat",   # 快速推理模型（分析师/研究员/交易员）
    "backend_url": None,                  # 自定义 API 端点（如国内中转）
    "temperature": 0.1,                   # 低温度 → 输出高度确定性 (一日游策略避免评分漂移)
    "agent_version": "v10",               # agent 版本标签 → 注入文件名 (v8/v9/v10)

    # --- A股 数据配置 ---
    "data_vendor": "akshare",            # akshare / tushare
    "tushare_token": None,               # Tushare token（可选）

    # --- 辩论配置 ---
    "max_debate_rounds": 1,              # 多空辩论轮数
    "max_risk_discuss_rounds": 1,        # 风险辩论轮数

    # --- 新闻与舆论配置 ---
    "news_limit": 20,                    # 每条搜索结果数上限
    "opinion_sources": ["xueqiu", "weibo", "news"],
    "enable_opinion_monitor": True,      # 启用舆论监控

    # --- 交易参数 ---
    "initial_capital": 100000,           # 初始资金
    "max_position_pct": 0.2,             # 单只股票最大仓位 (与 README 一致: 20%)
    # (round-9, L-core-7): LangGraph recursion_limit，默认 120 (4 分析师工具循环 + 辩论 + 风险辩论 + PM)
    "recursion_limit": 120,

    # --- 一日游策略参数 (One-Day Swing) ---
    "strategy_mode": "one_day_swing",    # 策略模式: one_day_swing (默认)
    "one_day_swing": {
        "holding_days": 1,               # 持有 1 个交易日
        "exit_rule": "forced_close",     # Day 2 收盘前强制平仓
        "target_gain_pct": 1.0,          # 目标涨幅 ≥1%（止盈线，扣除 0.11% 成本后净利约 0.89%）
        "stop_loss_pct": 3.0,            # 止损线 -3% (Day2 日内最低 ≤ 买价-3% 强制平仓)
        "min_daily_amount_yuan": 1e8,    # 最小日成交额: 1 亿元 (流动性门槛)
        "max_recent_gain_pct": 15,       # 近 5 日最大涨幅: 15% (追高过滤)
        "ban_st_stocks": True,           # 禁止 ST 股票
        # (round-9, L-core-8): max_position_pct 见顶层（去重，原重复定义在此）
    },

    # --- 基准指数 --- (M4: 以下两项 legacy, not read — 实际基准在 akshare_adapter 中硬编码)
    "benchmark_ticker": "000300",        # legacy, not read
    "benchmark_map": {                   # legacy, not read
        "SH": "000001",   # 上证综指
        "SZ": "399001",   # 深证成指
        "BJ": "899050",   # 北证50
        "000300": "000300",  # 沪深300
        "000905": "000905",  # 中证500
        "000852": "000852",  # 中证1000
    },

    # --- 记忆系统 ---
    "memory_log_path": str(MEMORY_LOG_PATH),
    "memory_log_max_entries": 50,        # 记忆日志最大条目数

    # --- 路径 --- (M4: project_dir/export_dir/data_cache_dir/checkpoint_dir/opinion_cache_dir 均为 legacy, not read — 实际路径用模块级常量)
    "project_dir": str(PROJECT_DIR),      # legacy, not read
    "results_dir": str(RESULTS_DIR),
    "export_dir": str(RESULTS_DIR),       # legacy, not read
    "data_cache_dir": str(DATA_CACHE_DIR),  # legacy, not read
    "checkpoint_dir": str(CHECKPOINT_DIR),  # legacy, not read
    "opinion_cache_dir": str(OPINION_CACHE_DIR),  # legacy, not read

    # --- 调试 ---
    "debug": False,
    "checkpoint_enabled": False,          # legacy, not read
}

# ============================================================
# 环境变量覆盖映射
# ============================================================
_ENV_OVERRIDES = {
    "ASTOCK_LLM_PROVIDER": "llm_provider",
    "ASTOCK_DEEP_THINK_LLM": "deep_think_llm",
    "ASTOCK_QUICK_THINK_LLM": "quick_think_llm",
    "ASTOCK_BACKEND_URL": "backend_url",
    "ASTOCK_TEMPERATURE": "temperature",
    "ASTOCK_DATA_VENDOR": "data_vendor",
    "ASTOCK_TUSHARE_TOKEN": "tushare_token",
    "ASTOCK_MAX_DEBATE_ROUNDS": "max_debate_rounds",
    "ASTOCK_MAX_RISK_ROUNDS": "max_risk_discuss_rounds",
    "ASTOCK_DEBUG": "debug",
    "ASTOCK_INITIAL_CAPITAL": "initial_capital",
}


def _coerce(value_str: str, default_val):
    """根据默认值类型自动转换环境变量字符串"""
    if default_val is None:
        return value_str
    if isinstance(default_val, bool):
        return value_str.lower() in ("true", "1", "yes")
    if isinstance(default_val, int):
        return int(value_str)
    if isinstance(default_val, float):
        return float(value_str)
    return value_str


def _apply_env_overrides(config: dict) -> dict:
    """应用 ASTOCK_* 环境变量覆盖"""
    for env_key, config_key in _ENV_OVERRIDES.items():
        env_val = os.environ.get(env_key)
        if env_val is not None:
            config[config_key] = _coerce(env_val, config.get(config_key))
    return config


def get_config() -> dict:
    """获取完整配置（含环境变量覆盖）"""
    return _apply_env_overrides(copy.deepcopy(DEFAULT_CONFIG))


def set_config(config: dict) -> dict:
    """运行时设置配置（浅合并到默认配置）"""
    merged = copy.deepcopy(DEFAULT_CONFIG)
    for k, v in config.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k].update(v)
        else:
            merged[k] = v
    return _apply_env_overrides(merged)
