"""图标统一读取与切换（program_root/icons 目录，运行时只扫 .ico）。"""

import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

# 五十音行序（元音列）：图标按此顺序轮换，而非字母序
_GOJUON_VOWELS = "aiueo"


def icon_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "icons")


def _gojuon_key(path: str):
    stem = os.path.splitext(os.path.basename(path))[0]
    ch = stem[-1] if stem else ""
    idx = _GOJUON_VOWELS.find(ch)
    return (idx if idx >= 0 else len(_GOJUON_VOWELS), os.path.basename(path))


def icon_files() -> list:
    """循环图标列表：icons 目录下的 .ico，按五十音顺序（a i u e o…）。"""
    d = icon_dir()
    if not os.path.isdir(d):
        return []
    return sorted(
        (os.path.join(d, name) for name in os.listdir(d)
         if name.lower().endswith(".ico")),
        key=_gojuon_key,
    )


def resolve_icon_path(saved_name: str | None = None):
    """按持久化文件名解析图标路径；无效或缺失时回退列表第一项。"""
    files = icon_files()
    if not files:
        return None
    if saved_name:
        for p in files:
            if os.path.basename(p) == saved_name:
                return p
    return files[0]


def apply_icon(window, path: str) -> None:
    """设置窗口与应用图标（标题栏/任务栏跟随）。"""
    icon = QIcon(path)
    window.setWindowIcon(icon)
    app = QApplication.instance()
    if isinstance(app, QApplication):
        app.setWindowIcon(icon)
