# settings_manager.py — 配置管理器
"""Settings.ini 配置读写 + .uplr 工程文件导入/导出。

通过 Qt Signal 通知 UI 所有配置变更。
"""

import os
import sys
import json
import copy
import hashlib
import shutil
import configparser
from typing import Optional

from PySide6.QtCore import QObject, Signal

from core.log import logger


class ProjectFileMissingError(Exception):
    """工程文件中引用的文件路径不存在。

    import_uplr 加载配置后校验 ustx/lrc/audio/custom_font_paths 路径，
    收集全部缺失项后一次性抛出。此时配置已加载到内存，仅文件不可用，
    调用方捕获后仍应同步 UI 供用户重新选择文件。
    """

    def __init__(self, missing: list[tuple[str, str]]):
        # missing: [(字段标签, 路径), ...]
        self.missing = missing
        lines = "\n".join(f"  - {label}: {path}" for label, path in missing)
        super().__init__(f"以下文件路径不存在:\n{lines}")


class SettingsManager(QObject):
    """应用配置管理器，集中管理所有设置项。

    每个配置项对应一个属性，修改时发出对应的 Signal。
    UI 层通过 connect/setValue 模式绑定。
    """

    # ===================== 信号定义 =====================
    # 字符串信号
    ustx_path_changed = Signal(str)
    project_name_changed = Signal(str)
    song_name_changed = Signal(str)
    song_author_changed = Signal(str)
    ust_author_changed = Signal(str)
    bg_color_changed = Signal(str)
    note_color_changed = Signal(str)
    lyric_color_changed = Signal(str)
    pitch_curve_color_changed = Signal(str)
    lyric_pos_changed = Signal(str)
    lrc_path_changed = Signal(str)
    audio_path_changed = Signal(str)
    silent_display_changed = Signal(str)
    silent_custom_text_changed = Signal(str)
    end_display_changed = Signal(str)
    end_custom_text_changed = Signal(str)
    pitch_placeholder_changed = Signal(str)
    pitch_custom_text_changed = Signal(str)

    # 字体（逐字歌词字体 / 歌词及信息字体 分开控制）
    word_lyric_font_family_changed = Signal(str)
    info_font_family_changed = Signal(str)
    # 自定义字体文件路径（写入 .uplr，打开工程时按路径重新加载恢复）
    custom_font_paths_changed = Signal(list)

    # 歌词及信息颜色（独立于样式）
    info_text_color_changed = Signal(str)

    # 样式系统信号
    active_style_index_changed = Signal(int)
    styles_changed = Signal()  # 样式数据变更（颜色/增删）
    global_bg_color_changed = Signal(str)
    global_bg_enabled_changed = Signal(bool)

    # 音符数据信号（供歌词编辑页使用）
    ustx_notes_changed = Signal(list)
    # 逐音符样式（供播放器渲染用）
    note_styles_changed = Signal(object)

    # 布尔信号
    show_bpm_changed = Signal(bool)
    show_play_time_changed = Signal(bool)
    show_song_name_changed = Signal(bool)
    show_song_author_changed = Signal(bool)
    show_ust_author_changed = Signal(bool)
    show_phoneme_changed = Signal(bool)
    show_midinote_changed = Signal(bool)
    show_waveform_changed = Signal(bool)
    fullscreen_changed = Signal(bool)
    show_copyright_changed = Signal(bool)
    curve_show_changed = Signal(bool)
    theme_mode_changed = Signal(str)
    accent_color_mode_changed = Signal(str)
    custom_accent_color_changed = Signal(str)

    # ===================== .uplr 工程文件字段注册表 =====================
    # 数据驱动的字段序列化：导出/导入共用单一真相源。
    # 类型约定: str/bool/int/float/json。
    # 注意：
    #   - 主题/强调色属于用户级 UI 偏好，仅写入 Settings.ini，不参与 .uplr。
    #   - ustx_notes 是解析缓存，由 ustx_content 还原后重新解析得到，不直接持久化。
    #   - 导入顺序敏感字段(ustx_path/styles/active_style_index/note_styles)在 import_uplr 中单独处理。
    PROJECT_SCHEMA = [
        # 基础元信息
        ("project_name", "str"),
        ("ustx_path", "str"),
        ("song_name", "str"),
        ("song_author", "str"),
        ("ust_author", "str"),
        # 颜色（与活动样式联动，build_ust_info 中作为 fallback）
        ("bg_color", "str"),
        ("note_color", "str"),
        ("lyric_color", "str"),
        ("pitch_curve_color", "str"),
        ("info_text_color", "str"),
        # 全局背景
        ("global_bg_color", "str"),
        ("global_bg_enabled", "bool"),
        # 路径与位置
        ("lyric_pos", "str"),
        ("lrc_path", "str"),
        ("audio_path", "str"),
        # 静默/结尾/音高占位显示
        ("silent_display", "str"),
        ("silent_custom_text", "str"),
        ("end_display", "str"),
        ("end_custom_text", "str"),
        ("pitch_placeholder", "str"),
        ("pitch_custom_text", "str"),
        # 字体（逐字歌词字体 / 歌词及信息字体）
        ("word_lyric_font_family", "str"),
        ("info_font_family", "str"),
        # 自定义字体文件路径（打开工程时按路径重新加载恢复）
        ("custom_font_paths", "json"),
        # 布尔显示开关
        ("show_bpm", "bool"),
        ("show_play_time", "bool"),
        ("show_song_name", "bool"),
        ("show_song_author", "bool"),
        ("show_ust_author", "bool"),
        ("show_copyright", "bool"),
        ("show_phoneme", "bool"),
        ("show_midinote", "bool"),
        ("show_waveform", "bool"),
        ("fullscreen", "bool"),
        ("show_lyric", "bool"),
        ("show_lyric_autohide", "bool"),
        ("lyric_autohide_threshold", "float"),
        ("curve_show", "bool"),
        # 样式系统（结构化数据，导入顺序敏感）
        ("styles", "json"),
        ("active_style_index", "int"),
        ("note_styles", "json"),
    ]

    # 导入时需延后/特殊处理的字段名集合
    _DEFERRED_FIELDS = {"ustx_path", "styles", "active_style_index", "note_styles"}

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        # 程序根目录
        self.program_root = os.path.dirname(os.path.abspath(sys.argv[0]))
        self.settings_path = os.path.join(self.program_root, "Settings.ini")

        # 文本文件路径
        self.terms_file_path = os.path.join(self.program_root, "Terms.txt")

        # 缓存目录（程序根目录下，存放 ustx 等还原缓存）
        # 启动与退出时各清空一次：启动确保干净状态，退出释放空间。
        self.cache_dir = os.path.join(self.program_root, "cache")
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
        except Exception:
            logger.exception(f"创建缓存目录失败: {self.cache_dir}")
        self.clear_cache()

        # 默认路径
        default_desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        self.last_open_dir = default_desktop
        self.last_export_dir = default_desktop

        # ===== 工程字段（PROJECT_SCHEMA）默认值 =====
        # 默认值统一定义在 _get_project_defaults()，__init__ 与 import_uplr 共用。
        self._reset_project_to_defaults()

        # ===== 用户级 UI 偏好（不参与 .uplr 工程导入/导出，仅写入 Settings.ini）=====
        self._theme_mode = "auto"  # auto=跟随系统, light=亮色, dark=暗色
        self._accent_color_mode = "auto"  # 持久化于 Settings.ini 的 ThemeSettings（auto=跟随系统, custom=自定义）
        self._custom_accent_color = "#8245aa"  # 自定义强调色（持久化）

        # 初始化配置
        self._config = configparser.ConfigParser()
        self.read_settings()

    # ===================== 字符串属性（getter/setter + signal） =====================

    @property
    def ustx_path(self) -> str:
        return self._ustx_path

    @ustx_path.setter
    def ustx_path(self, v: str):
        if self._ustx_path != v:
            self._ustx_path = v
            self.ustx_path_changed.emit(v)

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
    def ust_author(self) -> str:
        return self._ust_author

    @ust_author.setter
    def ust_author(self, v: str):
        if self._ust_author != v:
            self._ust_author = v
            self.ust_author_changed.emit(v)

    @property
    def bg_color(self) -> str:
        return self._bg_color

    @bg_color.setter
    def bg_color(self, v: str):
        if self._bg_color != v:
            self._bg_color = v
            self.bg_color_changed.emit(v)

    @property
    def note_color(self) -> str:
        return self._note_color

    @note_color.setter
    def note_color(self, v: str):
        if self._note_color != v:
            self._note_color = v
            self.note_color_changed.emit(v)

    @property
    def lyric_color(self) -> str:
        return self._lyric_color

    @lyric_color.setter
    def lyric_color(self, v: str):
        if self._lyric_color != v:
            self._lyric_color = v
            self.lyric_color_changed.emit(v)

    @property
    def pitch_curve_color(self) -> str:
        return self._pitch_curve_color

    @pitch_curve_color.setter
    def pitch_curve_color(self, v: str):
        if self._pitch_curve_color != v:
            self._pitch_curve_color = v
            self.pitch_curve_color_changed.emit(v)

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
    def audio_path(self) -> str:
        return self._audio_path

    @audio_path.setter
    def audio_path(self, v: str):
        if self._audio_path != v:
            self._audio_path = v
            self.audio_path_changed.emit(v)

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

    # ===================== 字体 =====================

    @property
    def word_lyric_font_family(self) -> str:
        """逐字歌词字体（播放器中央大字）。"""
        return self._word_lyric_font_family

    @word_lyric_font_family.setter
    def word_lyric_font_family(self, v: str):
        if self._word_lyric_font_family != v:
            self._word_lyric_font_family = v
            self.word_lyric_font_family_changed.emit(v)

    @property
    def info_font_family(self) -> str:
        """歌词及信息字体（LRC 歌词、音名、BPM、时间、版权等）。"""
        return self._info_font_family

    @info_font_family.setter
    def info_font_family(self, v: str):
        if self._info_font_family != v:
            self._info_font_family = v
            self.info_font_family_changed.emit(v)

    @property
    def custom_font_paths(self) -> list:
        """自定义字体文件路径列表（写入工程文件，打开时按路径重新加载恢复）。"""
        return self._custom_font_paths

    @custom_font_paths.setter
    def custom_font_paths(self, v: list):
        if self._custom_font_paths != v:
            self._custom_font_paths = v
            self.custom_font_paths_changed.emit(v)

    @property
    def info_text_color(self) -> str:
        return self._info_text_color

    @info_text_color.setter
    def info_text_color(self, v: str):
        if self._info_text_color != v:
            self._info_text_color = v
            self.info_text_color_changed.emit(v)

    # ===================== 样式系统属性 =====================

    @property
    def styles(self) -> list:
        return self._styles

    @property
    def active_style_index(self) -> int:
        return self._active_style_index

    @active_style_index.setter
    def active_style_index(self, v: int):
        if 0 <= v < len(self._styles) and self._active_style_index != v:
            self._active_style_index = v
            self.active_style_index_changed.emit(v)
            # 同步当前样式颜色到基础颜色属性（build_ust_info 的 fallback）
            p = self._styles[v]
            self._bg_color = p.get("bg_color", "#000000")
            self._note_color = p.get("note_color", "#6c6c6c")
            self._lyric_color = p.get("lyric_color", "#ffffff")
            self._pitch_curve_color = p.get("pitch_curve_color", "#ffffff")

    @property
    def active_style(self) -> dict:
        """返回当前激活样式的 dict。"""
        return self._styles[self._active_style_index] if self._styles else {}

    def set_style_color(self, style_index: int, key: str, value: str):
        """设置指定样式的某个颜色值。"""
        if 0 <= style_index < len(self._styles):
            if self._styles[style_index].get(key) != value:
                self._styles[style_index][key] = value
                # 如果是当前激活样式，同步基础颜色属性
                if style_index == self._active_style_index:
                    if key == "bg_color":
                        self._bg_color = value
                    elif key == "note_color":
                        self._note_color = value
                    elif key == "lyric_color":
                        self._lyric_color = value
                    elif key == "pitch_curve_color":
                        self._pitch_curve_color = value
                self.styles_changed.emit()

    @property
    def style_count(self) -> int:
        return len(self._styles)

    def add_style(self):
        """新建样式（复制样式1的颜色），返回新索引。"""
        new_idx = len(self._styles)
        self._styles.append(dict(self._styles[0]))  # 复制样式1
        logger.info(f"样式系统: 新建样式{new_idx + 1}（共{len(self._styles)}个）")
        self.styles_changed.emit()
        return new_idx

    def remove_style(self, index: int) -> bool:
        """删除指定索引的样式。至少保留3个样式（默认样式不可删）。"""
        if len(self._styles) <= 3 or index < 0 or index >= len(self._styles):
            return False
        del self._styles[index]
        logger.info(f"样式系统: 删除样式{index + 1}（剩余{len(self._styles)}个）")
        # 调整 active index
        if self._active_style_index >= len(self._styles):
            self._active_style_index = len(self._styles) - 1
        elif self._active_style_index > index:
            self._active_style_index -= 1
        # 重映射逐音符样式：被删样式→样式1，后面的样式索引前移
        new_styles = {}
        for row, si in self._note_styles.items():
            if si == index:
                new_styles[row] = 0
            elif si > index:
                new_styles[row] = si - 1
            else:
                new_styles[row] = si
        self.note_styles = new_styles  # 走 setter 发射 note_styles_changed
        # 同步基础颜色属性
        p = self._styles[self._active_style_index]
        self._bg_color = p.get("bg_color", "#000000")
        self._note_color = p.get("note_color", "#6c6c6c")
        self._lyric_color = p.get("lyric_color", "#ffffff")
        self._pitch_curve_color = p.get("pitch_curve_color", "#ffffff")
        self.styles_changed.emit()
        self.active_style_index_changed.emit(self._active_style_index)
        return True

    def get_style_name(self, index: int) -> str:
        """获取样式显示名称（样式1, 样式2, ...）。"""
        return f"样式{index + 1}"

    # ===================== 音符数据（歌词编辑用） =====================

    @property
    def ustx_notes(self) -> list:
        return self._ustx_notes

    @ustx_notes.setter
    def ustx_notes(self, v: list):
        self._ustx_notes = v
        self._note_styles = {}  # 新音符时清空样式
        self.ustx_notes_changed.emit(v)

    @property
    def cached_ust_info(self) -> Optional[dict]:
        return self._cached_ust_info

    @cached_ust_info.setter
    def cached_ust_info(self, v: Optional[dict]):
        # 纯内存缓存，无 signal
        self._cached_ust_info = v

    def maybe_fill_project_name_from_ustx(self) -> bool:
        """项目名为空时，用 ustx 文件名（不含扩展名）自动填充。

        仅在导入 ustx 文件时调用。project_name 非空则保持不变。
        返回 True 表示执行了填充。
        """
        if not self._project_name.strip() and self._ustx_path:
            base = os.path.splitext(os.path.basename(self._ustx_path))[0]
            if base:
                self.project_name = base  # 走 setter 触发信号
                return True
        return False

    @property
    def note_styles(self) -> dict:
        """逐音符样式映射 {行号: 样式索引}。"""
        return self._note_styles

    @note_styles.setter
    def note_styles(self, v: dict):
        self._note_styles = v
        self.note_styles_changed.emit(v)

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

    def get_effective_bg_color(self) -> str:
        """获取实际生效的背景色（考虑全局背景开关）。"""
        if self._global_bg_enabled:
            return self._global_bg_color
        return self.active_style.get("bg_color", "#000000")

    # ===================== 布尔属性（getter/setter + signal） =====================

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
    def show_ust_author(self) -> bool:
        return self._show_ust_author

    @show_ust_author.setter
    def show_ust_author(self, v: bool):
        if self._show_ust_author != v:
            self._show_ust_author = v
            self.show_ust_author_changed.emit(v)

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

    @property
    def show_lyric_autohide(self) -> bool:
        return self._show_lyric_autohide

    @show_lyric_autohide.setter
    def show_lyric_autohide(self, v: bool):
        if self._show_lyric_autohide != v:
            self._show_lyric_autohide = v

    @property
    def lyric_autohide_threshold(self) -> float:
        return self._lyric_autohide_threshold

    @lyric_autohide_threshold.setter
    def lyric_autohide_threshold(self, v: float):
        if self._lyric_autohide_threshold != v:
            self._lyric_autohide_threshold = v

    @property
    def curve_show(self) -> bool:
        return self._curve_show

    @curve_show.setter
    def curve_show(self, v: bool):
        if self._curve_show != v:
            self._curve_show = v
            self.curve_show_changed.emit(v)

    # ===================== 主题模式属性 =====================

    @property
    def theme_mode(self) -> str:
        return self._theme_mode

    @theme_mode.setter
    def theme_mode(self, v: str):
        if v not in ("auto", "light", "dark"):
            v = "auto"
        if self._theme_mode != v:
            self._theme_mode = v
            self.theme_mode_changed.emit(v)

    # ===================== 强调色属性 =====================

    @property
    def accent_color_mode(self) -> str:
        return self._accent_color_mode

    @accent_color_mode.setter
    def accent_color_mode(self, v: str):
        if v not in ("auto", "custom"):
            v = "auto"
        if self._accent_color_mode != v:
            self._accent_color_mode = v
            self.accent_color_mode_changed.emit(v)

    @property
    def custom_accent_color(self) -> str:
        return self._custom_accent_color

    @custom_accent_color.setter
    def custom_accent_color(self, v: str):
        if self._custom_accent_color != v:
            self._custom_accent_color = v
            self.custom_accent_color_changed.emit(v)

    # ===================== Settings.ini 读写 =====================

    def read_settings(self):
        """读取配置文件，恢复上次的导入/导出路径。"""
        default_desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        try:
            if os.path.exists(self.settings_path):
                self._config.read(self.settings_path, encoding="utf-8")
                if "PathSettings" in self._config:
                    self.last_open_dir = self._config["PathSettings"].get(
                        "last_open_dir", default_desktop
                    )
                    self.last_export_dir = self._config["PathSettings"].get(
                        "last_export_dir", default_desktop
                    )
                    if not os.path.isdir(self.last_open_dir):
                        self.last_open_dir = default_desktop
                    if not os.path.isdir(self.last_export_dir):
                        self.last_export_dir = default_desktop
                # 读取主题设置
                if "ThemeSettings" in self._config:
                    mode = self._config["ThemeSettings"].get("theme_mode", "auto")
                    self._theme_mode = mode if mode in ("auto", "light", "dark") else "auto"
                    amode = self._config["ThemeSettings"].get("accent_color_mode", "auto")
                    self._accent_color_mode = amode if amode in ("auto", "custom") else "auto"
                    self._custom_accent_color = self._config["ThemeSettings"].get(
                        "custom_accent_color", "#8245aa"
                    )
            else:
                self.last_open_dir = default_desktop
                self.last_export_dir = default_desktop
        except Exception:
            self.last_open_dir = default_desktop
            self.last_export_dir = default_desktop
            logger.exception("读取配置文件失败")

    def write_settings(self):
        """将路径和主题偏好写入配置文件（样式等不持久化，由 .uplr 工程文件管理）。"""
        try:
            # 完全重建配置，避免旧数据残留
            self._config = configparser.ConfigParser()
            self._config["PathSettings"] = {
                "last_open_dir": self.last_open_dir,
                "last_export_dir": self.last_export_dir,
            }
            self._config["ThemeSettings"] = {
                "theme_mode": self._theme_mode,
                "accent_color_mode": self._accent_color_mode,
                "custom_accent_color": self._custom_accent_color,
            }

            # 原子写入：先写临时文件再替换，避免中途失败损坏已有配置
            tmp = self.settings_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                self._config.write(f)
            os.replace(tmp, self.settings_path)
        except Exception:
            logger.exception("写入配置文件失败")

    # ===================== 缓存目录管理 =====================

    def clear_cache(self):
        """清空缓存目录中的所有文件（保留目录本身）。

        在程序启动与退出时各调用一次：启动清空确保干净状态并覆盖上次异常
        退出的残留；退出清空释放磁盘空间。单个文件删除失败不影响其余文件。
        """
        try:
            if not os.path.isdir(self.cache_dir):
                return
            for name in os.listdir(self.cache_dir):
                fp = os.path.join(self.cache_dir, name)
                try:
                    if os.path.isfile(fp) or os.path.islink(fp):
                        os.remove(fp)
                    elif os.path.isdir(fp):
                        shutil.rmtree(fp)
                except Exception:
                    logger.exception(f"删除缓存文件失败: {fp}")
        except Exception:
            logger.exception("清空缓存目录失败")

    # ===================== 工程字段默认值与重置 =====================

    def _get_project_defaults(self) -> dict:
        """返回所有 PROJECT_SCHEMA 字段的默认值（每次返回新副本）。

        作为工程字段默认值的单一真相源，__init__ 与 import_uplr 共用。
        styles/custom_font_paths/note_styles 为可变对象，调用方需自行 deepcopy
        （_reset_project_to_defaults 已处理）。
        """
        return {
            # 基础元信息
            "project_name": "",
            "ustx_path": "",
            "song_name": "",
            "song_author": "",
            "ust_author": "",
            # 颜色（与活动样式联动，build_ust_info 中作为 fallback）
            "bg_color": "#000000",
            "note_color": "#6c6c6c",
            "lyric_color": "#ffffff",
            "pitch_curve_color": "#ffffff",
            "info_text_color": "#ffffff",
            # 全局背景
            "global_bg_color": "#00ff00",
            "global_bg_enabled": False,
            # 路径与位置
            "lyric_pos": "上",
            "lrc_path": "",
            "audio_path": "",
            # 静默/结尾/音高占位显示
            "silent_display": "♪",
            "silent_custom_text": "",
            "end_display": "END",
            "end_custom_text": "",
            "pitch_placeholder": "无",
            "pitch_custom_text": "",
            # 字体（逐字歌词字体 / 歌词及信息字体）
            "word_lyric_font_family": "等线",
            "info_font_family": "微软雅黑",
            # 自定义字体文件路径
            "custom_font_paths": [],
            # 布尔显示开关
            "show_bpm": True,
            "show_play_time": True,
            "show_song_name": True,
            "show_song_author": True,
            "show_ust_author": True,
            "show_copyright": True,
            "show_phoneme": False,
            "show_midinote": False,
            "show_waveform": False,
            "fullscreen": True,
            "show_lyric": True,
            "show_lyric_autohide": True,
            "lyric_autohide_threshold": 3.0,
            "curve_show": False,
            # 样式系统（结构化数据，导入顺序敏感）
            "styles": [
                {"bg_color": "#000000", "note_color": "#6c6c6c", "lyric_color": "#ffffff", "pitch_curve_color": "#ffffff"},
                {"bg_color": "#000000", "note_color": "#ff8a80", "lyric_color": "#ff0c0c", "pitch_curve_color": "#ff0c0c"},
                {"bg_color": "#000000", "note_color": "#a1887f", "lyric_color": "#795548", "pitch_curve_color": "#795548"},
            ],
            "active_style_index": 0,
            "note_styles": {},
        }

    def _reset_project_to_defaults(self):
        """将所有 PROJECT_SCHEMA 字段重置为默认值。

        直接写 backing field（不经 setter），避免 active_style_index setter 同步
        颜色、note_styles setter 发信号等副作用。同时清空 ustx_notes 与解析缓存。
        """
        defaults = self._get_project_defaults()
        for name, _ftype in self.PROJECT_SCHEMA:
            setattr(self, f"_{name}", copy.deepcopy(defaults[name]))
        # 派生状态清空
        self._ustx_notes = []
        self._cached_ust_info = None
        # 延迟解析状态（import_uplr parse_ustx=False 暂存，后台解析完成后应用）
        self._deferred_ustx_parse: dict | None = None

    # ===================== .uplr 工程文件导入/导出 =====================

    def export_uplr(self, output_file: str):
        """导出全部配置到 .uplr 工程文件（JSON 格式）。

        全量记录所有注册字段（含默认值），内嵌完整 ustx 文件内容。
        三个文件(ustx/lrc/audio)为空时同样可导出（作为预设配置）。
        """
        # 读取 ustx 文件全文（无文件则为空串 → 预设场景）
        ustx_content = ""
        if self._ustx_path and os.path.isfile(self._ustx_path):
            try:
                with open(self._ustx_path, "r", encoding="utf-8") as f:
                    ustx_content = f.read()
            except Exception:
                logger.exception(f"读取 ustx 文件失败: {self._ustx_path}")
                ustx_content = ""

        # 全量序列化所有注册字段
        settings_data = {}
        for name, _ftype in self.PROJECT_SCHEMA:
            settings_data[name] = getattr(self, name)

        # project_name 为空时兜底为"未命名"（仅写入导出文件）
        if not settings_data["project_name"].strip():
            settings_data["project_name"] = "未命名"

        payload = {
            "format": "ustxPlayer.uplr",
            "version": 2,
            "ustx_content": ustx_content,
            "settings": settings_data,
        }
        # 原子写入：先写临时文件再替换，避免中途失败损坏已有工程文件
        tmp = output_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, output_file)


    def import_uplr(self, input_file: str, parse_ustx: bool = True):
        """从 .uplr 工程文件导入全部配置（JSON 格式）。

        导入顺序规避信号副作用清空结构化数据：
          0) 重置所有 PROJECT_SCHEMA 字段为默认值，确保旧工程配置不残留；
          1) 普通字段循环赋值，跳过顺序敏感字段；
          2) styles（须在 active_style_index 之前）；
          3) active_style_index（setter 同步基础颜色属性）；
          4) ustx 还原：写入缓存（parse_ustx=True 时同步解析，False 时延迟解析）；
          5) note_styles 最后赋值（在 ustx_notes 清空之后）；
          6) 校验文件路径，缺失项一次性抛出 ProjectFileMissingError。
        支持三个文件(ustx/lrc/audio)均为空的预设场景。

        Args:
            parse_ustx: 是否立即解析 USTX。False 时将解析推迟到后台线程，
                        由 _apply_deferred_uplr_styles() 完成。
        """
        with open(input_file, "r", encoding="utf-8") as f:
            payload = json.load(f)

        # 校验工程文件格式，避免误导入任意 JSON 污染当前配置
        if payload.get("format") != "ustxPlayer.uplr" or payload.get("version") != 2:
            raise ValueError("不是有效的 ustxPlayer 工程文件（format/version 不匹配）")

        data = payload.get("settings", {})
        ustx_content = payload.get("ustx_content", "") or ""

        # ---- 阶段0: 重置所有工程字段为默认值 ----
        # 先校验格式再重置：格式非法时抛 ValueError，当前配置不受影响
        self._reset_project_to_defaults()

        # ---- 阶段1: 普通字段（跳过顺序敏感字段）----
        for name, ftype in self.PROJECT_SCHEMA:
            if name in self._DEFERRED_FIELDS:
                continue
            if name not in data:
                continue
            raw = data[name]
            try:
                if ftype == "bool":
                    setattr(self, name, bool(raw))
                elif ftype == "int":
                    setattr(self, name, int(raw))
                elif ftype == "float":
                    setattr(self, name, float(raw))
                else:  # str / json
                    setattr(self, name, raw)
            except (ValueError, TypeError):
                logger.warning(f"工程文件字段 {name} 值非法，已跳过: {raw!r}")

        # ---- 阶段2: styles（须先于 active_style_index）----
        styles = data.get("styles")
        if isinstance(styles, list) and styles:
            # 补齐每个样式 dict 的缺失键，避免下游硬下标 KeyError
            _style_defaults = {
                "bg_color": "#000000",
                "note_color": "#6c6c6c",
                "lyric_color": "#ffffff",
                "pitch_curve_color": "#ffffff",
            }
            self._styles = [
                {**_style_defaults, **s} if isinstance(s, dict) else dict(_style_defaults)
                for s in styles
            ]
            self.styles_changed.emit()

        # ---- 阶段3: active_style_index（setter 同步基础颜色属性）----
        if "active_style_index" in data:
            try:
                idx = int(data["active_style_index"])
            except (ValueError, TypeError):
                logger.warning(f"active_style_index 值非法，已忽略: {data['active_style_index']!r}")
                idx = 0
            # 越界时 clamp 到有效范围，避免下游 self._styles[idx] IndexError
            idx = max(0, min(idx, len(self._styles) - 1)) if self._styles else 0
            self.active_style_index = idx

        # ---- 阶段4: ustx 还原（写入 cache 子目录）----
        if ustx_content:
            digest = hashlib.sha1(ustx_content.encode("utf-8")).hexdigest()[:10]
            cache_path = os.path.join(self.cache_dir, f"ustx_cache_{digest}.ustx")
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(ustx_content)
                self.ustx_path = cache_path
                if parse_ustx:
                    # 同步解析（传统行为，用于 basic_page 等非拖拽场景）
                    from core.ustxreader import get_ustx_info
                    ust_info = get_ustx_info(cache_path)
                    _notes = ust_info.get("notes", [])
                    self.ustx_notes = _notes if isinstance(_notes, list) else []
                else:
                    # 延迟解析：置空音符，由后台线程完成后填充
                    self.ustx_notes = []
            except Exception:
                logger.exception("还原 ustx 缓存失败，音符数据置空")
                # 重置 ustx_path 为工程文件记录的原路径，避免残留指向半成品缓存
                self._ustx_path = data.get("ustx_path", "")
                self.ustx_notes = []
        else:
            # 预设场景：保留工程文件中记录的 ustx_path（可为空），不解析
            self.ustx_path = data.get("ustx_path", "")
            self.ustx_notes = []  # setter 清空 note_styles

        # ---- 阶段5: note_styles（必须在 ustx_notes 之后，否则会被清空）----
        ns = data.get("note_styles")
        if isinstance(ns, dict):
            # JSON 键为字符串，需转回 int（行号/样式索引）
            self.note_styles = {int(k): int(v) for k, v in ns.items()}
        else:
            self.note_styles = {}

        # ---- 延迟解析暂存（parse_ustx=False 时保存，后台解析完成后恢复）----
        if not parse_ustx and ustx_content:
            ns = data.get("note_styles")
            self._deferred_ustx_parse = {
                "cache_path": cache_path,
                "note_styles": {int(k): int(v) for k, v in ns.items()} if isinstance(ns, dict) else {},
            }

        # ---- 阶段6: 校验文件路径（ustx/lrc/audio/custom_font_paths 非空路径必须存在）----
        # 收集全部缺失路径后一次性抛出
        missing: list[tuple[str, str]] = []
        if self._ustx_path and not os.path.exists(self._ustx_path):
            missing.append(("USTX 文件", self._ustx_path))
        if self._lrc_path and not os.path.exists(self._lrc_path):
            missing.append(("歌词文件", self._lrc_path))
        if self._audio_path and not os.path.exists(self._audio_path):
            missing.append(("音频文件", self._audio_path))
        for font_path in self._custom_font_paths:
            if font_path and not os.path.exists(font_path):
                missing.append(("字体文件", font_path))
        if missing:
            raise ProjectFileMissingError(missing)

    def _apply_deferred_uplr_styles(self):
        """后台解析完成后，恢复 UPLR 工程文件中保存的 note_styles。

        由 FilePage._apply_notes 在设置 ustx_notes 之后调用。
        """
        if self._deferred_ustx_parse is None:
            return
        ns = self._deferred_ustx_parse.get("note_styles", {})
        if isinstance(ns, dict):
            self.note_styles = ns
        self._deferred_ustx_parse = None

    # ===================== 构建播放器需要的 ust_info 字典 =====================

    def build_ust_info(self, core_ust_info: dict) -> dict:
        """组装传递给播放器的完整参数 dict。"""
        ap = self.active_style
        return {
            "version": core_ust_info.get("version", "未知版本"),
            "tempo": core_ust_info.get("tempo", 120.0),
            "tracks": core_ust_info.get("tracks", 1),
            "notes": core_ust_info.get("notes", []),
            "show_config": {
                "bpm": self.show_bpm,
                "play_time": self.show_play_time,
                "song_name": self.show_song_name,
                "song_author": self.show_song_author,
                "ust_author": self.show_ust_author,
                "copyright": self.show_copyright,
                "lyric": self.show_lyric,
                "lyric_autohide": self.show_lyric_autohide,
                "lyric_autohide_threshold": self.lyric_autohide_threshold,
                "curve_show": self.curve_show,
            },
            "project_info": {
                "project_name": self.project_name,
                "song_name": self.song_name,
                "song_author": self.song_author,
                "ust_author": self.ust_author,
            },
            "player_style": {
                "bg_color": ap.get("bg_color", self._bg_color),
                "global_bg_color": self._global_bg_color,
                "global_bg_enabled": self._global_bg_enabled,
                "note_color": ap.get("note_color", self._note_color),
                "lyric_color": ap.get("lyric_color", self._lyric_color),
                "info_text_color": self._info_text_color,
                "lyric_pos": self.lyric_pos,
                "show_phoneme": self.show_phoneme,
                "show_midinote": self.show_midinote,
                "show_waveform": self.show_waveform,
                "fullscreen": self.fullscreen,
                "lrc_path": self.lrc_path,
                "audio_path": self.audio_path,
                "silent_display": self.silent_display,
                "silent_custom_text": self.silent_custom_text,
                "end_display": self.end_display,
                "end_custom_text": self.end_custom_text,
                "pitch_placeholder": self.pitch_placeholder,
                "pitch_custom_text": self.pitch_custom_text,
                "pitch_curve_color": ap.get("pitch_curve_color", self._pitch_curve_color),
                "word_lyric_font_family": self.word_lyric_font_family,
                "info_font_family": self.info_font_family,
                "styles": list(self._styles),  # 全部样式数据
                "note_styles": dict(self._note_styles),  # 逐音符样式
            },
        }
