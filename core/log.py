# log.py — 日志配置
"""基于 loguru 的全局日志。

用法:
    from core.log import logger

    logger.info("正常信息")
    logger.debug("调试信息")
    logger.exception("自动附完整堆栈")
"""

import sys
import os

from loguru import logger

logger.remove()

# 统一使用程序根目录（与 settings_manager.program_root 一致，基于 sys.argv[0]），
# 禁止写入系统缓存目录。
_log_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

try:
    logger.add(
        os.path.join(_log_dir, "ustxPlayer.log"),
        level="DEBUG",
        rotation="1 MB",
        retention="7 days",
    )
except Exception:
    # 日志文件不可写时降级（如目录无权限），不应阻塞主程序启动
    pass

if sys.stdout is not None:
    logger.add(sys.stdout, level="INFO", colorize=True)
