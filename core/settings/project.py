# settings/project.py — 工程信息设置子域
"""工程信息：项目名/曲名/曲师/调音师/音频路径/源文件路径/播放轨。

前四处元信息 + audio_path + selected_track_no 参与 .uprj 序列化；
ustx_path 是会话级源文件路径，不进出 .uprj。
"""

from typing import Optional

from PySide6.QtCore import QObject, Signal


class ProjectSettings(QObject):
    """工程信息设置。"""

    project_name_changed = Signal(str)
    song_name_changed = Signal(str)
    song_author_changed = Signal(str)
    ustx_author_changed = Signal(str)
    audio_path_changed = Signal(str)
    selected_track_changed = Signal(int)
    ustx_path_changed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._project_name = ""
        self._song_name = ""
        self._song_author = ""
        self._ustx_author = ""
        self._audio_path = ""
        self._selected_track_no = 0
        self._ustx_path = ""

    @property
    def project_name(self) -> str:
        return self._project_name

    @project_name.setter
    def project_name(self, v: str):
        if self._project_name != v:
            self._project_name = v
            self.project_name_changed.emit(v)

    @property
    def song_name(self) -> str:
        return self._song_name

    @song_name.setter
    def song_name(self, v: str):
        if self._song_name != v:
            self._song_name = v
            self.song_name_changed.emit(v)

    @property
    def song_author(self) -> str:
        return self._song_author

    @song_author.setter
    def song_author(self, v: str):
        if self._song_author != v:
            self._song_author = v
            self.song_author_changed.emit(v)

    @property
    def ustx_author(self) -> str:
        return self._ustx_author

    @ustx_author.setter
    def ustx_author(self, v: str):
        if self._ustx_author != v:
            self._ustx_author = v
            self.ustx_author_changed.emit(v)

    @property
    def audio_path(self) -> str:
        return self._audio_path

    @audio_path.setter
    def audio_path(self, v: str):
        if self._audio_path != v:
            self._audio_path = v
            self.audio_path_changed.emit(v)

    @property
    def selected_track_no(self) -> int:
        """当前播放的人声轨号（多轨工程专用，默认 0）。"""
        return self._selected_track_no

    @selected_track_no.setter
    def selected_track_no(self, v: int):
        v = int(v) if v is not None else 0
        if self._selected_track_no != v:
            self._selected_track_no = v
            self.selected_track_changed.emit(v)

    @property
    def ustx_path(self) -> str:
        """会话级 .ustx 源文件路径（不进出 .uprj）。"""
        return self._ustx_path

    @ustx_path.setter
    def ustx_path(self, v: str):
        if self._ustx_path != v:
            self._ustx_path = v
            self.ustx_path_changed.emit(v)