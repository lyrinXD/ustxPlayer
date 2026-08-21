# settings_manager.py — 应用设置门面
"""组装各设置子域并编排用户偏好持久化与播放参数装配。

- 设置子域（属性 + 信号）分布在 core/settings/ 包：
  ProjectSettings / DisplaySettings / StyleSettings / ColorSettings / PlayerSettings / ThemeSettings；
- 用户级偏好存于 Settings.json（含路径与主题），由 core/settings_store.py（SettingsStore）承担；
- .uprj 工程文件导入/导出由 core/uprj_io.py（UprjProjectIO）承担。

UI 通过 settings.<子域>.<属性> 访问，如 settings.display.show_bpm。
"""

import os
import sys
from typing import Optional

from PySide6.QtCore import QObject, Signal

from core.log import logger
from core.settings_store import SettingsStore
from core.uprj_io import UprjProjectIO
from core.settings import (
    ColorSettings,
    DisplaySettings,
    PlayerSettings,
    ProjectSettings,
    StyleSettings,
    ThemeSettings,
)


class SettingsManager(QObject):
    """应用设置门面 — 组装六个子域并编排持久化与播放参数装配。"""

    # 音符数据信号（供歌词编辑页使用）
    ustx_notes_changed = Signal(list)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        # 程序根目录
        self.program_root = os.path.dirname(os.path.abspath(sys.argv[0]))
        self._store = SettingsStore()
        self.settings_path = self._store.settings_path

        # 文本文件路径
        self.terms_file_path = os.path.join(self.program_root, "LICENSE")

        # 默认路径
        default_desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        self.last_open_dir = default_desktop
        self.last_export_dir = default_desktop

        # 设置子域
        self.project = ProjectSettings(self)
        self.display = DisplaySettings(self)
        self.style = StyleSettings(self)
        self.color = ColorSettings(self)
        self.player = PlayerSettings(self)
        self.theme = ThemeSettings(self)

        # 会话状态（不进出 .uprj）
        self._ustx_notes: list = []
        self._cached_ustx_info: Optional[dict] = None
        self._deferred_ustx_parse: dict | None = None

        # .uprj 工程文件序列化服务（依赖子域与会话状态）
        self._uprj = UprjProjectIO(self)

        # 初始化配置
        self.read_settings()

    # ===================== 会话状态（音符/解析缓存） =====================

    @property
    def ustx_notes(self) -> list:
        return self._ustx_notes

    @ustx_notes.setter
    def ustx_notes(self, v: list):
        self._ustx_notes = v
        self.style.clear_note_styles()  # 新音符时清空逐音符样式
        self.ustx_notes_changed.emit(v)

    @property
    def cached_ustx_info(self) -> Optional[dict]:
        return self._cached_ustx_info

    @cached_ustx_info.setter
    def cached_ustx_info(self, v: Optional[dict]):
        # 纯内存缓存，无 signal
        self._cached_ustx_info = v

    def maybe_fill_project_name_from_ustx(self) -> bool:
        """工程名为空时，用 ustx 文件名（不含扩展名）自动填充。

        仅在导入 ustx 文件时调用。project_name 非空则保持不变。
        返回 True 表示执行了填充。
        """
        if not self.project.project_name.strip() and self.project.ustx_path:
            base = os.path.splitext(os.path.basename(self.project.ustx_path))[0]
            if base:
                self.project.project_name = base  # 走 setter 触发信号
                return True
        return False

    # ===================== .uprj 工程文件导入/导出（委托 UprjProjectIO） =====================

    def export_uprj(self, output_file: str):
        """导出 .uprj 工程文件（见 UprjProjectIO.export_uprj）。"""
        self._uprj.export_uprj(output_file)

    def import_uprj(self, input_file: str, parse_ustx: bool = True):
        """导入 .uprj 工程文件（见 UprjProjectIO.import_uprj）。"""
        self._uprj.import_uprj(input_file, parse_ustx)

    def _apply_deferred_uprj_styles(self):
        """延迟应用完成后恢复 note_styles（见 UprjProjectIO.apply_deferred_uprj_styles）。"""
        self._uprj.apply_deferred_uprj_styles()

    # ===================== Settings.json 读写 =====================

    def read_settings(self):
        """读取用户级偏好并恢复上次的导入/导出路径，路径失效时回退桌面。"""
        default_desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        try:
            config = self._store.load()
            if not config:
                self.last_open_dir = default_desktop
                self.last_export_dir = default_desktop
                return
            paths = config.get("PathSettings")
            if isinstance(paths, dict):
                self.last_open_dir = paths.get("last_open_dir", default_desktop)
                self.last_export_dir = paths.get("last_export_dir", default_desktop)
                if not os.path.isdir(self.last_open_dir):
                    self.last_open_dir = default_desktop
                if not os.path.isdir(self.last_export_dir):
                    self.last_export_dir = default_desktop
            self.theme.read_from(config)
        except Exception:
            self.last_open_dir = default_desktop
            self.last_export_dir = default_desktop
            logger.exception("读取配置文件失败")

    def write_settings(self):
        """将路径和用户级偏好写入 Settings.json（样式等不持久化，由 .uprj 工程文件管理）。"""
        try:
            config = {
                "PathSettings": {
                    "last_open_dir": self.last_open_dir,
                    "last_export_dir": self.last_export_dir,
                },
            }
            self.theme.write_to(config)
            self._store.save(config)
        except Exception:
            logger.exception("写入配置文件失败")

    # ===================== 构建播放器需要的 ustx_info 字典 =====================

    def build_ustx_info(self, core_ustx_info: dict) -> dict:
        """组装传递给播放器的完整参数 dict。

        多轨工程按 selected_track_no 过滤音符，并把逐音符样式从全局行号
        重映射到过滤后的下标；变速（根级 tempos）是工程级数据，不受选轨影响。
        """
        ap = self.style.active_style
        all_notes = core_ustx_info.get("notes", []) or []
        selected = self.project.selected_track_no
        # 安全兜底：保存的轨道号不在人声轨列表时回退第一条人声轨
        tracks_info = core_ustx_info.get("tracks_info") or []
        valid_tracks = {t.get("track_no") for t in tracks_info
                        if isinstance(t, dict) and t.get("track_no") is not None}
        if valid_tracks and selected not in valid_tracks:
            selected = min(valid_tracks)
        elif not valid_tracks:
            for n in all_notes:
                if n.get("track_no", 0) == selected:
                    break
            else:
                selected = all_notes[0].get("track_no", 0) if all_notes else 0
        filtered_notes = []
        global_rows = []
        for i, n in enumerate(all_notes):
            if n.get("track_no", 0) == selected:
                filtered_notes.append(n)
                global_rows.append(i)
        note_styles = {
            new_i: self.style.note_styles.get(global_i, 0)
            for new_i, global_i in enumerate(global_rows)
        }
        return {
            "version": core_ustx_info.get("version", "未知版本"),
            "tempo": core_ustx_info.get("tempo", 120.0),
            "tempos": core_ustx_info.get("tempos", []),
            "tracks": core_ustx_info.get("tracks", 1),
            "notes": filtered_notes,
            "show_config": {
                "bpm": self.display.show_bpm,
                "play_time": self.display.show_play_time,
                "song_name": self.display.show_song_name,
                "song_author": self.display.show_song_author,
                "ustx_author": self.display.show_ustx_author,
                "copyright": self.display.show_copyright,
                "lyric": self.display.show_lyric,
                "lyric_autohide": self.display.show_lyric_autohide,
                "lyric_autohide_threshold": self.display.lyric_autohide_threshold,
                "curve_show": self.display.curve_show,
            },
            "project_info": {
                "project_name": self.project.project_name,
                "song_name": self.project.song_name,
                "song_author": self.project.song_author,
                "ustx_author": self.project.ustx_author,
            },
            "player_style": {
                "bg_color": ap.get("bg_color", self.style.bg_color),
                "global_bg_color": self.color.global_bg_color,
                "global_bg_enabled": self.color.global_bg_enabled,
                "note_color": ap.get("note_color", self.style.note_color),
                "lyric_color": ap.get("lyric_color", self.style.lyric_color),
                "info_text_color": self.color.info_text_color,
                "lyric_pos": self.player.lyric_pos,
                "show_phoneme": self.display.show_phoneme,
                "show_midinote": self.display.show_midinote,
                "show_waveform": self.display.show_waveform,
                "fullscreen": self.display.fullscreen,
                "lrc_path": self.player.lrc_path,
                "audio_path": self.project.audio_path,
                "silent_display": self.player.silent_display,
                "silent_custom_text": self.player.silent_custom_text,
                "end_display": self.player.end_display,
                "end_custom_text": self.player.end_custom_text,
                "pitch_placeholder": self.player.pitch_placeholder,
                "pitch_custom_text": self.player.pitch_custom_text,
                "pitch_curve_color": ap.get("pitch_curve_color", self.style.pitch_curve_color),
                "word_lyric_font_family": self.player.word_lyric_font_family,
                "info_font_family": self.player.info_font_family,
                "styles": list(self.style.styles),  # 全部样式数据
                "note_styles": note_styles,  # 逐音符样式（已重映射到过滤后下标）
            },
        }