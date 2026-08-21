# settings/player.py — 播放器行为设置子域
"""歌词位置、静态显示替换文本（静默/结尾/音高）、字体配置，全部参与 .uprj 序列化。"""

from typing import Optional

from PySide6.QtCore import QObject, Signal


class PlayerSettings(QObject):
    """播放器行为设置（显示文本与字体）。"""

    lyric_pos_changed = Signal(str)
    lrc_path_changed = Signal(str)
    silent_display_changed = Signal(str)
    silent_custom_text_changed = Signal(str)
    end_display_changed = Signal(str)
    end_custom_text_changed = Signal(str)
    pitch_placeholder_changed = Signal(str)
    pitch_custom_text_changed = Signal(str)
    word_lyric_font_family_changed = Signal(str)
    info_font_family_changed = Signal(str)
    custom_font_paths_changed = Signal(list)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._lyric_pos = "上"
        self._lrc_path = ""
        self._silent_display = "♪"
        self._silent_custom_text = ""
        self._end_display = "END"
        self._end_custom_text = ""
        self._pitch_placeholder = "无"
        self._pitch_custom_text = ""
        self._word_lyric_font_family = "等线"
        self._info_font_family = "微软雅黑"
        self._custom_font_paths: list = []

    @property
    def lyric_pos(self) -> str:
        return self._lyric_pos

    @lyric_pos.setter
    def lyric_pos(self, v: str):
        if self._lyric_pos != v:
            self._lyric_pos = v
            self.lyric_pos_changed.emit(v)

    @property
    def lrc_path(self) -> str:
        return self._lrc_path

    @lrc_path.setter
    def lrc_path(self, v: str):
        if self._lrc_path != v:
            self._lrc_path = v
            self.lrc_path_changed.emit(v)

    @property
    def silent_display(self) -> str:
        return self._silent_display

    @silent_display.setter
    def silent_display(self, v: str):
        if self._silent_display != v:
            self._silent_display = v
            self.silent_display_changed.emit(v)

    @property
    def silent_custom_text(self) -> str:
        return self._silent_custom_text

    @silent_custom_text.setter
    def silent_custom_text(self, v: str):
        if self._silent_custom_text != v:
            self._silent_custom_text = v
            self.silent_custom_text_changed.emit(v)

    @property
    def end_display(self) -> str:
        return self._end_display

    @end_display.setter
    def end_display(self, v: str):
        if self._end_display != v:
            self._end_display = v
            self.end_display_changed.emit(v)

    @property
    def end_custom_text(self) -> str:
        return self._end_custom_text

    @end_custom_text.setter
    def end_custom_text(self, v: str):
        if self._end_custom_text != v:
            self._end_custom_text = v
            self.end_custom_text_changed.emit(v)

    @property
    def pitch_placeholder(self) -> str:
        return self._pitch_placeholder

    @pitch_placeholder.setter
    def pitch_placeholder(self, v: str):
        if self._pitch_placeholder != v:
            self._pitch_placeholder = v
            self.pitch_placeholder_changed.emit(v)

    @property
    def pitch_custom_text(self) -> str:
        return self._pitch_custom_text

    @pitch_custom_text.setter
    def pitch_custom_text(self, v: str):
        if self._pitch_custom_text != v:
            self._pitch_custom_text = v
            self.pitch_custom_text_changed.emit(v)

    @property
    def word_lyric_font_family(self) -> str:
        return self._word_lyric_font_family

    @word_lyric_font_family.setter
    def word_lyric_font_family(self, v: str):
        if self._word_lyric_font_family != v:
            self._word_lyric_font_family = v
            self.word_lyric_font_family_changed.emit(v)

    @property
    def info_font_family(self) -> str:
        return self._info_font_family

    @info_font_family.setter
    def info_font_family(self, v: str):
        if self._info_font_family != v:
            self._info_font_family = v
            self.info_font_family_changed.emit(v)

    @property
    def custom_font_paths(self) -> list:
        return self._custom_font_paths

    @custom_font_paths.setter
    def custom_font_paths(self, v: list):
        if self._custom_font_paths != v:
            self._custom_font_paths = v
            self.custom_font_paths_changed.emit(v)