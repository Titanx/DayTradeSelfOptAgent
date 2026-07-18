"""
Schema 定义 — Agent 结构化输出的 Pydantic 模型

借鉴 TradingAgents 的设计：结构化输出 + Markdown 渲染双通道。
"""

from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


# ============================================================
# 评级枚举
# ============================================================

class PortfolioRating(str, Enum):
    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(str, Enum):
    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


class SentimentBand(str, Enum):
    VERY_BULLISH = "Very Bullish"
    BULLISH = "Bullish"
    SLIGHTLY_BULLISH = "Slightly Bullish"
    NEUTRAL = "Neutral"
    SLIGHTLY_BEARISH = "Slightly Bearish"
    BEARISH = "Bearish"


# ============================================================
# 分析师输出
# ============================================================

class FundamentalReport(BaseModel):
    """基本面分析报告"""
    rating: PortfolioRating = Field(description="基于基本面的评级")
    roe: Optional[float] = Field(None, description="净资产收益率")
    revenue_growth: Optional[float] = Field(None, description="营收增长率")
    pe_ttm: Optional[float] = Field(None, description="市盈率TTM")
    key_strengths: List[str] = Field(default_factory=list, description="核心优势")
    key_risks: List[str] = Field(default_factory=list, description="主要风险")
    summary: str = Field(description="分析总结")


class TechnicalReport(BaseModel):
    """技术面分析报告"""
    rating: PortfolioRating = Field(description="基于技术面的评级")
    trend: str = Field(description="趋势判断：上涨/下跌/震荡")
    key_signals: List[str] = Field(default_factory=list, description="关键技术信号")
    support_level: Optional[float] = Field(None, description="支撑位")
    resistance_level: Optional[float] = Field(None, description="阻力位")
    summary: str = Field(description="技术分析总结")


class SentimentReport(BaseModel):
    """舆论情绪分析报告"""
    rating: PortfolioRating = Field(description="基于舆论情绪的评级")
    sentiment_band: SentimentBand = Field(description="情绪区间")
    sentiment_score: float = Field(ge=-1, le=1, description="情绪评分")
    key_narratives: List[str] = Field(default_factory=list, description="核心市场叙事")
    risk_signals: List[str] = Field(default_factory=list, description="风险信号")
    summary: str = Field(description="情绪分析总结")


class PolicyReport(BaseModel):
    """政策/宏观分析报告（A股特色）"""
    rating: PortfolioRating = Field(description="基于政策面的评级")
    policy_impact: str = Field(description="政策影响：利好/利空/中性")
    key_policies: List[str] = Field(default_factory=list, description="关键政策/事件")
    sector_rotation_hint: Optional[str] = Field(None, description="板块轮动提示")
    summary: str = Field(description="政策分析总结")


# ============================================================
# 研究员/交易员输出
# ============================================================

class ResearchPlan(BaseModel):
    """研究员投资计划"""
    rating: PortfolioRating = Field(description="投资评级")
    thesis: str = Field(description="投资核心逻辑（聚焦次日一日游机会）")
    catalysts: List[str] = Field(default_factory=list, description="次日催化剂事件")
    risks: List[str] = Field(default_factory=list, description="一日持有期内的风险")
    timeframe: str = Field(default="一日游(Day1买入→Day2强制卖出)", description="固定一日游策略")


class TraderProposal(BaseModel):
    """交易员提案 — 一日游策略专用"""
    action: TraderAction = Field(description="交易动作: Buy=Day1开盘买入 / Hold=观望 / Sell=(策略不出卖单)")
    position_pct: Optional[float] = Field(None, ge=0, le=0.2, description="仓位比例 (单股≤20%)")
    entry_signal: Optional[str] = Field(None, description="Day1入场信号条件")
    day1_upside_catalyst: Optional[str] = Field(None, description="看好Day1上涨≥1%的具体理由")
    expected_gain_pct: Optional[float] = Field(None, ge=1.0, description="预期持仓期（Day1开盘→Day2日内）涨幅%，策略底线≥1%")
    day2_forced_exit_note: str = Field(default="无论盈亏，Day2收盘前强制平仓", description="强制平仓说明")
    reasoning: str = Field(description="一日游交易逻辑（必须论证Day1涨幅≥1%的可行性）")


class PortfolioDecision(BaseModel):
    """最终投资决策 — 一日游策略"""
    rating: PortfolioRating = Field(description="最终评级 (Day1是否值得买入)")
    action: TraderAction = Field(description="最终动作: Buy=Day1开盘买入/Hold=观望")
    position_pct: Optional[float] = Field(None, ge=0, le=0.2, description="建议仓位")
    confidence: float = Field(ge=0, le=1, description="决策信心度 (Day1上涨≥1%的概率)")
    executive_summary: str = Field(description="一日游执行摘要: Day1买入理由 + Day2卖出规则")
    investment_thesis: str = Field(description="看多核心论题 (为什么Day1会涨)")
    key_risks: List[str] = Field(default_factory=list, description="24小时内主要风险 (隔夜/盘中/流动性)")


# ============================================================
# Markdown 渲染函数
# ============================================================

def render_fundamental_report(report: FundamentalReport) -> str:
    return f"""**Rating**: {report.rating.value}

**Key Metrics**:
- ROE: {report.roe if report.roe is not None else 'N/A'}
- Revenue Growth: {report.revenue_growth if report.revenue_growth is not None else 'N/A'}
- PE(TTM): {report.pe_ttm if report.pe_ttm is not None else 'N/A'}

**Strengths**: {', '.join(report.key_strengths) if report.key_strengths else 'N/A'}
**Risks**: {', '.join(report.key_risks) if report.key_risks else 'N/A'}

**Summary**: {report.summary}"""


def render_technical_report(report: TechnicalReport) -> str:
    return f"""**Rating**: {report.rating.value}

**Trend**: {report.trend}
**Support**: {report.support_level if report.support_level is not None else 'N/A'}
**Resistance**: {report.resistance_level if report.resistance_level is not None else 'N/A'}

**Key Signals**: {', '.join(report.key_signals) if report.key_signals else 'N/A'}

**Summary**: {report.summary}"""


def render_sentiment_report(report: SentimentReport) -> str:
    return f"""**Rating**: {report.rating.value}

**Sentiment**: {report.sentiment_band.value} (Score: {report.sentiment_score:+.2f})

**Market Narratives**: {', '.join(report.key_narratives) if report.key_narratives else 'N/A'}
**Risk Signals**: {', '.join(report.risk_signals) if report.risk_signals else 'None'}

**Summary**: {report.summary}"""


def render_policy_report(report: PolicyReport) -> str:
    return f"""**Rating**: {report.rating.value}

**Policy Impact**: {report.policy_impact}
**Key Policies**: {', '.join(report.key_policies) if report.key_policies else 'N/A'}
**Sector Rotation**: {report.sector_rotation_hint if report.sector_rotation_hint is not None else 'N/A'}

**Summary**: {report.summary}"""


def render_research_plan(plan: ResearchPlan) -> str:
    return f"""**Rating**: {plan.rating.value}

**Investment Thesis**: {plan.thesis}
**Catalysts**: {', '.join(plan.catalysts) if plan.catalysts else 'N/A'}
**Risks**: {', '.join(plan.risks) if plan.risks else 'N/A'}
**Timeframe**: {plan.timeframe}"""


def render_trader_proposal(proposal: TraderProposal) -> str:
    lines = [f"**Action**: {proposal.action.value}"]
    if proposal.position_pct is not None:
        # (round-10, L-core-2): 仓位格式同步 :.1%，与 PortfolioDecision 渲染保持一致
        lines.append(f"**Position**: {proposal.position_pct:.1%}")
    if proposal.entry_signal:
        lines.append(f"**Day1入场信号**: {proposal.entry_signal}")
    if proposal.day1_upside_catalyst:
        lines.append(f"**看好Day1上涨≥1%的理由**: {proposal.day1_upside_catalyst}")
    if proposal.expected_gain_pct is not None:
        lines.append(f"**预期Day1涨幅**: {proposal.expected_gain_pct:.1f}%")
    lines.append(f"**Day2卖出规则**: {proposal.day2_forced_exit_note}")
    lines.append(f"\n**Reasoning**: {proposal.reasoning}")
    return "\n".join(lines)


def render_portfolio_decision(decision: PortfolioDecision) -> str:
    lines = [
        f"**Rating**: {decision.rating.value}",
        f"**Action**: {decision.action.value}",
        f"**Confidence**: {decision.confidence:.0%}",
    ]
    if decision.position_pct is not None:
        # (round-9, L-core-3): :.0% 把 0.155→"16%" 解析回 0.16 丢失精度，改 :.1%
        lines.append(f"**Position**: {decision.position_pct:.1%}")
    lines.append(f"\n**Executive Summary**: {decision.executive_summary}")
    lines.append(f"\n**Investment Thesis**: {decision.investment_thesis}")
    if decision.key_risks:
        lines.append(f"\n**Key Risks**: {', '.join(decision.key_risks)}")
    lines.append("\n---")
    lines.append(f"*策略: Day0收盘分析 → Day1开盘买入 → Day2收盘前强制平仓*")
    return "\n".join(lines)
