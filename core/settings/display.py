# settings/display.py — 显示设置子域
"""播放器画面显示开关与文字配置，全部参与 .uprj 序列化。"""

from typing import Optional

from PySide6.QtCore import QObject, Signal


class DisplaySettings(QObject):
    """播放器显示设置。"""

    show_bpm_changed = Signal(bool)
    show_play_time_changed = Signal(bool)
    show_song_name_changed = Signal(bool)
    show_song_author_changed = Signal(bool)
    show_ustx_author_changed = Signal(bool)
    show_copyright_changed = Signal(bool)
    show_phoneme_changed = Signal(bool)
    show_midinote_changed = Signal(bool)
    show_waveform_changed = Signal(bool)
    fullscreen_changed = Signal(bool)
    show_lyric_changed = Signal(bool)
    show_lyric_autohide_changed = Signal(bool)
    lyric_autohide_threshold_changed = Signal(float)
    curve_show_changed = Signal(bool)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._show_bpm = True
        self._show_play_time = True
        self._show_song_name = True
        self._show_song_author = True
        self._show_ustx_author = True
        self._show_copyright = True
        self._show_phoneme = False
        self._show_midinote = False
        self._show_waveform = False
        self._fullscreen = True
        self._show_lyric = True
        self._show_lyric_autohide = True
        self._lyric_autohide_threshold = 3.0
        self._curve_show = False

    @property
    def show_bpm(self) -> bool:
        return self._show_bpm

    @show_bpm.setter
    def show_bpm(self, v: bool):
        if self._show_bpm != v:
            self._show_bpm = v
            self.show_bpm_changed.emit(v)

    @property
    def show_play_time(self) -> bool:
        return self._show_play_time

    @show_play_time.setter
    def show_play_time(self, v: bool):
        if self._show_play_time != v:
            self._show_play_time = v
            self.show_play_time_changed.emit(v)

    @property
    def show_song_name(self) -> bool:
        return self._show_song_name

    @show_song_name.setter
    def show_song_name(self, v: bool):
        if self._show_song_name != v:
            self._show_song_name = v
            self.show_song_name_changed.emit(v)

    @property
    def show_song_author(self) -> bool:
        return self._show_song_author

    @show_song_author.setter
    def show_song_author(self, v: bool):
        if self._show_song_author != v:
            self._show_song_author = v
            self.show_song_author_changed.emit(v)

    @property
    def show_ustx_author(self) -> bool:
        return self._show_ustx_author

    @show_ustx_author.setter
    def show_ustx_author(self, v: bool):
        if self._show_ustx_author != v:
            self._show_ustx_author = v
            self.show_ustx_author_changed.emit(v)

    @property
    def show_copyright(self) -> bool:
        return self._show_copyright

    @show_copyright.setter
    def show_copyright(self, v: bool):
        if self._show_copyright != v:
            self._show_copyright = v
            self.show_copyright_changed.emit(v)

    @property
    def show_phoneme(self) -> bool:
        return self._show_phoneme

    @show_phoneme.setter
    def show_phoneme(self, v: bool):
        if self._show_phoneme != v:
            self._show_phoneme = v
            self.show_phoneme_changed.emit(v)

    @property
    def show_midinote(self) -> bool:
        return self._show_midinote

    @show_midinote.setter
    def show_midinote(self, v: bool):
        if self._show_midinote != v:
            self._show_midinote = v
            self.show_midinote_changed.emit(v)

    @property
    def show_waveform(self) -> bool:
        return self._show_waveform

    @show_waveform.setter
    def show_waveform(self, v: bool):
        if self._show_waveform != v:
            self._show_waveform = v
            self.show_waveform_changed.emit(v)

    @property
    def fullscreen(self) -> bool:
        return self._fullscreen

    @fullscreen.setter
    def fullscreen(self, v: bool):
        if self._fullscreen != v:
            self._fullscreen = v
            self.fullscreen_changed.emit(v)

    @property
    def show_lyric(self) -> bool:
        return self._show_lyric

    @show_lyric.setter
    def show_lyric(self, v: bool):
        if self._show_lyric != v:
            self._show_lyric = v
            self.show_lyric_changed.emit(v)

    @property
    def show_lyric_autohide(self) -> bool:
        return self._show_lyric_autohide

    @show_lyric_autohide.setter
    def show_lyric_autohide(self, v: bool):
        if self._show_lyric_autohide != v:
            self._show_lyric_autohide = v
            self.show_lyric_autohide_changed.emit(v)

    @property
    def lyric_autohide_threshold(self) -> float:
        return self._lyric_autohide_threshold

    @lyric_autohide_threshold.setter
    def lyric_autohide_threshold(self, v: float):
        if self._lyric_autohide_threshold != v:
            self._lyric_autohide_threshold = v
            self.lyric_autohide_threshold_changed.emit(v)

    @property
    def curve_show(self) -> bool:
        return self._curve_show

    @curve_show.setter
    def curve_show(self, v: bool):
        if self._curve_show != v:
            self._curve_show = v
            self.curve_show_changed.emit(v)