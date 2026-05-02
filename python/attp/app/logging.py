"""ATTP 统一日志模块。

提供带有 [ATTP XXXX] 前缀的 logger。
"""

from __future__ import annotations

import logging

from loguru import logger as _root_logger


# ---------------------------------------------------------------------------
# _ComponentLogger: 在每条消息前拼接 [ATTP {component}] 前缀
# ---------------------------------------------------------------------------


class _ComponentLogger:
    """代理 loguru logger，自动在消息前添加 ``[ATTP {component}]`` 前缀。

    使用 ``opt(depth=1)`` 确保调用栈指向真实调用方而非本类。
    """

    __slots__ = ("_prefix",)

    def __init__(self, component: str) -> None:
        self._prefix = f"[ATTP {component}]"

    # -- public helpers ----------------------------------------------------

    def info(self, __msg: str, *args, **kwargs) -> None:
        _root_logger.opt(depth=1).info(f"{self._prefix} {__msg}", *args, **kwargs)

    def error(self, __msg: str, *args, **kwargs) -> None:
        _root_logger.opt(depth=1).error(f"{self._prefix} {__msg}", *args, **kwargs)

    def warning(self, __msg: str, *args, **kwargs) -> None:
        _root_logger.opt(depth=1).warning(f"{self._prefix} {__msg}", *args, **kwargs)

    def debug(self, __msg: str, *args, **kwargs) -> None:
        _root_logger.opt(depth=1).debug(f"{self._prefix} {__msg}", *args, **kwargs)

    def exception(self, __msg: str, *args, **kwargs) -> None:
        _root_logger.opt(depth=1).exception(f"{self._prefix} {__msg}", *args, **kwargs)

    def critical(self, __msg: str, *args, **kwargs) -> None:
        _root_logger.opt(depth=1).critical(f"{self._prefix} {__msg}", *args, **kwargs)


def get_logger(component: str) -> _ComponentLogger:
    """返回一个自动拼接 ``[ATTP {component}]`` 前缀的 logger。

    Args:
        component: 组件名称，如 ``"Server"``、``"Client"``、``"Heartbeat"``。

    Returns:
        _ComponentLogger 实例。

    Example::

        from attp.app.logging import get_logger
        log = get_logger("Server")
        log.info("started on {}:{}", "0.0.0.0", 8000)
        # 输出: ... | INFO | ... - [ATTP Server] started on 0.0.0.0:8000
    """
    return _ComponentLogger(component)


# ---------------------------------------------------------------------------
# InterceptHandler: 将标准 logging 桥接到 loguru（可选，默认禁用）
# ---------------------------------------------------------------------------

# 取消下方注释可启用 uvicorn 日志拦截（会将 uvicorn 日志转发到 loguru 并添加 [ATTP Uvicorn] 前缀）
# 注意：启用后日志的文件位置可能显示为 logging:callHandlers 而非 uvicorn 源码位置，
# 且多个 uvicorn 实例无法区分，因此默认禁用。

# class _InterceptHandler(logging.Handler):
#     """将 Python 标准 logging 的记录转发到 loguru，并添加 [ATTP Uvicorn] 前缀。"""
#
#     _PREFIX = "[ATTP Uvicorn]"
#
#     def emit(self, record: logging.LogRecord) -> None:
#         try:
#             level = _root_logger.level(record.levelname).name
#         except ValueError:
#             level = record.levelno
#
#         frame, depth = logging.currentframe(), 2
#         while frame and frame.f_code.co_filename == logging.__file__:
#             frame = frame.f_back
#             depth += 1
#
#         msg = f"{self._PREFIX} {record.getMessage()}"
#         _root_logger.opt(depth=depth, exception=record.exc_info).log(level, msg)
#
#
# _UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
#
#
# def _setup_uvicorn_intercept() -> None:
#     """让 uvicorn 的日志走 loguru，并统一前缀为 [ATTP Uvicorn]。"""
#     for name in _UVICORN_LOGGERS:
#         logging.getLogger(name).handlers = [_InterceptHandler()]
#         logging.getLogger(name).propagate = False
#
#
# _setup_uvicorn_intercept()


# ---------------------------------------------------------------------------
# 静默 uvicorn 日志
# ---------------------------------------------------------------------------

#: 传给 ``uvicorn.Config(log_config=...)`` 的字典，让 uvicorn 自身配置 NullHandler，
#: 彻底不输出任何日志。
UVICORN_SILENT_LOG_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "loggers": {
        "uvicorn": {"handlers": ["null"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["null"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["null"], "level": "INFO", "propagate": False},
    },
    "handlers": {
        "null": {"class": "logging.NullHandler"},
    },
}


# ---------------------------------------------------------------------------
# 静默第三方库中的无害/噪音日志
# ---------------------------------------------------------------------------


class _NoiseFilter(logging.Filter):
    """过滤已知的无害第三方日志（标准 logging，非 loguru）。"""

    _RULES: list[tuple[str, str]] = [
        # (logger name, message substring)
        ("mcp.client.sse", "Error in sse_reader"),
        ("anp.anp_crawler.anp_client", "HTTP request failed"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for logger_name, substring in self._RULES:
            if record.name == logger_name and substring in msg:
                return False
        return True


_noise_filter = _NoiseFilter()
logging.getLogger("mcp.client.sse").addFilter(_noise_filter)
logging.getLogger("anp.anp_crawler.anp_client").addFilter(_noise_filter)
