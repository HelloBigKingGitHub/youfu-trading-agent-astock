#!/usr/bin/env python3
"""A 股分析快速入口"""
import os
from dotenv import load_dotenv
load_dotenv()

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# 根据环境变量自动选择 provider
if os.getenv("DEEPSEEK_API_KEY"):
    provider = "deepseek"
    deep_model = "deepseek-chat"
    quick_model = "deepseek-chat"
elif os.getenv("DASHSCOPE_API_KEY"):
    provider = "dashscope"
    deep_model = "qwen-max"
    quick_model = "qwen-plus"
elif os.getenv("MINIMAX_API_KEY"):
    provider = "minimax"
    deep_model = "MiniMax-M2.7"
    quick_model = "MiniMax-M2.7-highspeed"
else:
    raise RuntimeError("请在 .env 中配置 DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / MINIMAX_API_KEY 其一")

config = {**DEFAULT_CONFIG}
config.update({
    "llm_provider": provider,
    "deep_think_llm": deep_model,
    "quick_think_llm": quick_model,
    "max_debate_rounds": 1,
    "output_language": "Chinese",
    # A 股数据源
    "data_vendors": {
        "core_stock_apis": "a_stock",
        "technical_indicators": "a_stock",
        "fundamental_data": "a_stock",
        "news_data": "a_stock",
        "signal_data": "a_stock",
    },
})

ta = TradingAgentsGraph(debug=True, config=config)

# 用法: python run_astock.py <股票代码> [日期]
# 例: python run_astock.py 688017 2026-05-12
import sys
ticker = sys.argv[1] if len(sys.argv) > 1 else "688017"
date = sys.argv[2] if len(sys.argv) > 2 else "2026-06-02"

print(f"\n分析股票: {ticker}  日期: {date}\n")
_, decision = ta.propagate(ticker, date)
print(decision)