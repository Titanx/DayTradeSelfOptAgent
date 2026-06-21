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

# ============================================================
# 项目路径
# ============================================================
PROJECT_DIR = Path(__file__).parent.parent.resolve()
HOME_DIR = Path.home()
CACHE_DIR = HOME_DIR / ".astock_agent"
RESULTS_DIR = PROJECT_DIR / "results"         # 项目目录（供用户查看）
MEMORY_LOG_PATH = HOME_DIR / ".astock_agent" / "memory" / "trading_memory.md"
CHECKPOINT_DIR = HOME_DIR / ".astock_agent" / "checkpoints"
EXPORT_DIR = PROJECT_DIR / "results"           # 分析完成后同步到此

for d in [CACHE_DIR, RESULTS_DIR, MEMORY_LOG_PATH.parent, CHECKPOINT_DIR, EXPORT_DIR]:
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
    "temperature": 0.3,

    # --- A股 数据配置 ---
    "data_vendor": "akshare",            # akshare / tushare
    "tushare_token": None,               # Tushare token（可选）

    # --- 辩论配置 ---
    "max_debate_rounds": 1,              # 多空辩论轮数
    "max_risk_discuss_rounds": 1,        # 风险辩论轮数

    # --- 新闻与舆论配置 ---
    "news_limit": 20,                    # 每条搜索结果数上限
    "opinion_sources": ["xueqiu", "weibo", "wechat", "news"],
    "enable_opinion_monitor": True,      # 启用舆论监控

    # --- 交易参数 ---
    "initial_capital": 100000,           # 初始资金
    "max_position_pct": 0.3,             # 单只股票最大仓位
    "stop_loss_pct": 0.08,              # 止损线 8%
    "take_profit_pct": 0.20,            # 止盈线 20%
    "holding_period_days": 5,            # 默认持仓天数

    # --- 基准指数 ---
    "benchmark_ticker": "000300",        # 默认沪深300
    "benchmark_map": {
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

    # --- 路径 ---
    "project_dir": str(PROJECT_DIR),
    "results_dir": str(HOME_DIR / ".astock_agent" / "results"),
    "export_dir": str(PROJECT_DIR / "results"),
    "data_cache_dir": str(CACHE_DIR / "data_cache"),
    "checkpoint_dir": str(CHECKPOINT_DIR),

    # --- 调试 ---
    "debug": False,
    "checkpoint_enabled": False,
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
    "ASTOCK_STOP_LOSS_PCT": "stop_loss_pct",
    "ASTOCK_TAKE_PROFIT_PCT": "take_profit_pct",
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
