"""
TLM Web 入口：胶带机流量仿真、预测与仪表盘。

启动: python run_web.py
默认地址: http://localhost:5173（端口见 src.core.config.WebConfig.PORT）
"""

from src.web.cli import main


if __name__ == "__main__":
    main()
