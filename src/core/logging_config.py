"""TLM 统一日志配置：替代散落各处的 print()，支持分级控制。"""
import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """初始化根 logger——仅执行一次。"""
    root = logging.getLogger()
    if root.handlers:
        return  # 已配置过
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.setLevel(level)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """按模块名获取 logger，推荐传入 __name__。"""
    return logging.getLogger(name)
