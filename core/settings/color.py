# settings/color.py — 独立颜色设置子域
"""独立于样式系统的颜色：信息文字色 + 全局背景。

背景/音符/歌词/音高四色与样式系统一起归 StyleSettings（style.py）。
"""

from typing import Optional

from PySide6.QtCore import QObject, Signal


class ColorSettings(QObject):
    """独立颜色设置（与样式系统解耦）。"""

    info_text_color_changed = Signal(str)
    global_bg_color_changed = Signal(str)
    global_bg_enabled_changed = Signal(bool)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._info_text_color = "#ffffff"
        self._global_bg_color = "#00ff00"
        self._global_bg_enabled = False

    @property
    def info_text_color(self) -> str:
        return self._info_text_color

    @info_text_color.setter
    def info_text_color(self, v: str):
        if self._info_text_color != v:
            self._info_text_color = v
            self.info_text_color_changed.emit(v)

    @property
    def global_bg_color(self) -> str:
        return self._global_bg_color

    @global_bg_color.setter
    def global_bg_color(self, v: str):
        if self._global_bg_color != v:
            self._global_bg_color = v
            self.global_bg_color_changed.emit(v)

    @property
    def global_bg_enabled(self) -> bool:
        return self._global_bg_enabled

    @global_bg_enabled.setter
    def global_bg_enabled(self, v: bool):
        if self._global_bg_enabled != v:
            self._global_bg_enabled = v
            self.global_bg_enabled_changed.emit(v)