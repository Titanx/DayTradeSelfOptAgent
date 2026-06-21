# 舆论监控模块

多渠道舆论数据采集与情绪聚合分析。

## 文件说明

| 文件 | 说明 |
|------|------|
| `xueqiu_monitor.py` | 雪球社区监控，采集行情数据、热门帖子和热门股票 |
| `sentiment_aggregator.py` | 情绪聚合器，汇总雪球、微博、社交媒体等多渠道情绪信号 |

## 数据来源

| 渠道 | 方式 | 说明 |
|------|------|------|
| 雪球 | HTTP 直连 / Agent-Reach Channel | 个股行情、热门帖子、股吧讨论 |
| 微博 | Jina Reader 搜索 | 关键词搜索相关讨论情绪 |
| 财经新闻 | AKShare + HTTP | 相关新闻头条 |

## 设计思路

- 借鉴 Agent-Reach 的多渠道信息获取模式
- 保留对 Agent-Reach Channel 接口的可选兼容（`try/except` 导入，失败后走 HTTP 回退）
- 完全可独立运行，不依赖 Agent-Reach
