# ustxplayer.py — 全屏播放器
"""UST 音符可视化播放器，使用 QPainter 渲染全屏动画。"""

import os
import re
import time
import ctypes
from datetime import timedelta
from typing import List, Tuple, Optional

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, QUrl
from PySide6.QtGui import (
    QPainter, QColor, QFont, QFontMetrics, QPen, QPolygonF,
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from core.log import logger


# ===================== 工具函数 =====================

# Windows 媒体键虚拟键码
_VK_VOLUME_UP = 0xAF
_VK_VOLUME_DOWN = 0xAE
_KEYEVENTF_KEYUP = 0x0002

# 音名正则
_NOTE_PURE_RE = re.compile(r'([A-G])(\d+)')
_NOTE_SHARP_RE = re.compile(r'([A-G]#)(\d+)')


def step_system_volume(up: bool):
    """模拟按下音量增/减媒体键，调节 Windows 系统音量（无需第三方依赖）。

    每次调用触发一次按键（按下+抬起），约改变 2~3% 系统音量。
    仅适用于 Windows（本程序已依赖 winreg，限定 Windows 平台）。
    """
    vk = _VK_VOLUME_UP if up else _VK_VOLUME_DOWN
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)


def validate_hex_color(hex_color: str) -> str:
    """校验十六进制颜色，无效时返回 #ffffff。统一输出小写格式。"""
    if re.match(r'^#([0-9A-Fa-f]{6})$', str(hex_color)):
        return hex_color.strip().lower()
    return "#ffffff"


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """#RRGGBB → (R, G, B)。"""
    try:
        h = hex_color.lstrip('#')
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        return (255, 255, 255)


def format_play_time(seconds: float) -> str:
    """秒数 → MM:SS:CC 格式。"""
    try:
        ms = int((seconds - int(seconds)) * 100)
        td = timedelta(seconds=int(seconds))
        return f"{td.seconds // 60:02d}:{td.seconds % 60:02d}:{ms:02d}"
    except Exception:
        return "00:00:00"


# ===================== LRC 多语言解析 =====================

# 多语言分组阈值：连续行时间戳相差 ≤ 此值视为同一行的多语言
# - 交错格式：连续 2~3 行时间戳相差 1~5ms
# - 独立格式：排序后不同块中相同时间戳的行也聚到一起
# - 单语言文件：每行间隔远大于此值，每行自成一组
_LRC_GROUP_THRESHOLD = 0.020  # 20ms

# LRC 时间戳正则（兼容 2 位或 3 位毫秒）
_LRC_TIMESTAMP_RE = re.compile(r'\[(\d{1,2}):(\d{1,2})\.(\d{2,3})\]([^\[]*)')

# 多语言 LRC 文件尝试解码的编码顺序
_LRC_ENCODINGS = ['utf-8-sig', 'utf-8', 'gbk', 'gb2312', 'cp932']


def parse_lrc_file(path: str) -> List[Tuple[float, List[str]]]:
    """解析 .lrc 文件，返回多语言分组结果。

    自动识别交错 / 独立两种多语言编码格式，统一输出为：
        [(timestamp, [lang1, lang2, ...]), ...]

    单语言文件每个内层 list 长度为 1，向后兼容。
    同一组的各行按文件出现顺序保留（时间戳相同时稳定排序）。
    """
    content = ""
    for enc in _LRC_ENCODINGS:
        try:
            with open(path, 'r', encoding=enc) as f:
                content = f.read()
            break
        except Exception:
            continue
    if not content:
        return []

    raw_lines: List[Tuple[float, str]] = []
    for frag in _LRC_TIMESTAMP_RE.findall(content):
        try:
            minutes, seconds, ms = int(frag[0]), int(frag[1]), int(frag[2])
            if len(frag[2]) == 2:
                ms *= 10
            timestamp = minutes * 60 + seconds + ms / 1000
            lyric = frag[3].strip()
            if lyric:
                raw_lines.append((timestamp, lyric))
        except Exception:
            continue
    if not raw_lines:
        return []

    # 稳定排序：时间戳相同时按文件原顺序保留
    raw_lines.sort(key=lambda x: x[0])

    # 分组：连续行时间戳与首行相差 ≤ 阈值视为同一组多语言
    multi_lines: List[Tuple[float, List[str]]] = []
    i = 0
    n = len(raw_lines)
    while i < n:
        ts0, text0 = raw_lines[i]
        langs = [text0]
        j = i + 1
        while j < n and raw_lines[j][0] - ts0 <= _LRC_GROUP_THRESHOLD:
            langs.append(raw_lines[j][1])
            j += 1
        multi_lines.append((ts0, langs))
        i = j
    return multi_lines


def detect_lrc_max_languages(path: str) -> int:
    """快速检测 .lrc 文件的最大语言数（1=单语言，>1=多语言）。

    供 UI 在导入歌词时给出提示，解析失败时返回 1。
    """
    try:
        multi_lines = parse_lrc_file(path)
        if not multi_lines:
            return 1
        return max((len(langs) for _, langs in multi_lines), default=1)
    except Exception:
        return 1


# ===================== 播放器窗口 =====================

class NoteLyricDisplay(QWidget):
    """全屏播放器 — QPainter 渲染所有内容。"""

    NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    NOTE_LINE_WIDTH = 5  # 音高线线宽

    def __init__(self, ust_info: dict):
        super().__init__()
        self._info = ust_info

        # ---- 窗口配置 ----
        self.setWindowTitle("ustxPlayer - Player")
        self._fullscreen = ust_info["player_style"].get("fullscreen", True)
        # 窗口标志由 display() 在 show 前统一设置

        # ---- 背景色 ----
        self._bg_color_hex = validate_hex_color(
            ust_info["player_style"].get("bg_color", "#000000")
        )
        self._bg_color = QColor(self._bg_color_hex)

        # ---- 核心数据 ----
        self.notes = ust_info.get("notes", [])
        self.tempo = ust_info.get("tempo", 120)
        self.last_valid_lyric = ""
        pb_notes = sum(1 for n in self.notes if len(n.get("pitch_bend", [])) >= 2)
        logger.info(
            f"播放器初始化 — 音符数={len(self.notes)}, BPM={self.tempo}, "
            f"含PitchBend的音符={pb_notes}"
        )

        # ---- 时间轴 ----
        self.start_real_time = 0.0  # 在 showEvent 中与音乐同步设置
        self.tick_per_second = (self.tempo * 480) / 60
        # total_tick：有 position 时取所有音符中最晚结束的位置+长度，否则按 length 顺序累加
        if self.notes and "position" in self.notes[0]:
            self.total_tick = max(
                n.get("position", 0) + max(n.get("length", 480), 1) for n in self.notes
            )
        else:
            self.total_tick = sum(max(n.get("length", 480), 1) for n in self.notes)
        self.note_tick_ranges = self._calc_note_tick_ranges()
        logger.debug(
            f"时间轴 — tick_per_second={self.tick_per_second:.1f}, "
            f"total_tick={self.total_tick}"
        )

        # ---- 显示开关 ----
        sc = ust_info["show_config"]
        self.show_bpm = sc.get("bpm", True)
        self.show_play_time = sc.get("play_time", True)
        self.show_song_name = sc.get("song_name", True)
        self.show_song_author = sc.get("song_author", True)
        self.show_ust_author = sc.get("ust_author", True)
        self.show_copyright = sc.get("copyright", True)
        self.show_lyric = sc.get("lyric", True)
        self.show_lyric_autohide = sc.get("lyric_autohide", True)
        self.lyric_autohide_threshold = sc.get("lyric_autohide_threshold", 3.0)
        self.curve_show = sc.get("curve_show", False)

        # ---- 项目信息 ----
        pi = ust_info.get("project_info", {})
        self.song_name = pi.get("song_name", "")
        self.song_author = pi.get("song_author", "")
        self.ust_author = pi.get("ust_author", "")

        # ---- 播放器样式 ----
        ps = ust_info["player_style"]
        # 字体拆分：逐字歌词字体（中央大字）/ 歌词及信息字体（其余文字）
        self.word_lyric_font_family = ps.get("word_lyric_font_family", "等线")
        self.info_font_family = ps.get("info_font_family", "微软雅黑")
        self.lyric_pos = ps.get("lyric_pos", "上")
        self.lrc_path = ps.get("lrc_path", "")
        self.silent_display = ps.get("silent_display", "R")
        self.silent_custom_text = ps.get("silent_custom_text", "")
        self.end_display = ps.get("end_display", "END")
        self.end_custom_text = ps.get("end_custom_text", "")
        self.pitch_placeholder = ps.get("pitch_placeholder", "无")
        self.pitch_custom_text = ps.get("pitch_custom_text", "")
        # ---- 颜色 ----
        self.ust_lyric_color = hex_to_rgb(
            validate_hex_color(ps.get("lyric_color", "#ffffff"))
        )
        self.note_color = hex_to_rgb(
            validate_hex_color(ps.get("note_color", "#c3c3c3"))
        )
        self.small_font_color_hex = validate_hex_color(
            ps.get("info_text_color", "#ffffff")
        )
        self.pitch_curve_color_hex = validate_hex_color(
            ps.get("pitch_curve_color", "#ffffff")
        )
        self.note_alpha = 225
        self.copyright_alpha = 100

        # ---- 逐音符样式（歌词编辑页设定） ----
        self._styles = ps.get("styles", [])
        self._note_styles = ps.get("note_styles", {})
        # 全局背景（最高优先级）
        self._global_bg_enabled = ps.get("global_bg_enabled", False)
        self._global_bg_color_hex = validate_hex_color(
            ps.get("global_bg_color", "#00ff00")
        )

        # ---- 播放倍率 ----
        self._playback_speed = 1.0

        # ---- LRC 歌词（多语言分组：每项为 (timestamp, [lang1, lang2, ...])）----
        self.multi_lrc_lines: List[Tuple[float, List[str]]] = []
        self.current_lrc_idx = -1
        if self.show_lyric and self.lrc_path:
            self._parse_lrc()

        # ---- 音频播放 ----
        self.audio_path = ps.get("audio_path", "")
        self._media_player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._media_player.setAudioOutput(self._audio_output)
        self._audio_playing = False
        self._audio_duration_ms = 0  # 音频总时长（毫秒），EndOfMedia 时记录，用于 guard setPosition
        self._cleanup_done = False  # 防重入标记
        self._closing = False  # closeEvent 触发，hideEvent 据此判断
        if self._has_audio():
            self._media_player.setSource(QUrl.fromLocalFile(self.audio_path))
            self._media_player.mediaStatusChanged.connect(self._on_media_status_changed)
            self._media_player.errorChanged.connect(self._on_media_error)
            logger.info(f"音频文件已加载: {self.audio_path}")
        else:
            logger.info("无音频文件或路径无效，使用定时器计时")

        # ---- 屏幕尺寸 & 字体 ----
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            self.w, self.h = geo.width(), geo.height()
        else:
            self.w, self.h = 1920, 1080
        logger.debug(f"屏幕尺寸: {self.w}x{self.h}")

        self._init_fonts()

        # ---- 当前渲染状态 ----
        self._current_lyric = ""
        self._current_note_name = ""
        self._current_note: Optional[dict] = None
        self._play_elapsed = 0.0
        self._last_pb_log_note_idx = -1
        self._note_idx_hint = 0
        self._finished = False
        self._final_elapsed = 0.0

        # ---- 预计算 LRC 隐藏区间（按歌曲时间） ----
        tps = self.tick_per_second
        ticks_to_sec = 1.0 / tps
        threshold = self.lyric_autohide_threshold
        self._lrc_hide: List[Tuple[float, float]] = []
        if self.show_lyric and self.show_lyric_autohide and self.notes:
            ns = [(n.get('position', 0), n.get('position', 0) + n.get('length', 0)) for n in self.notes]
            for i in range(len(ns) - 1):
                gap = (ns[i+1][0] - ns[i][1]) * ticks_to_sec
                if gap > threshold:
                    self._lrc_hide.append((ns[i][1] * ticks_to_sec + threshold, ns[i+1][0] * ticks_to_sec))
            self._lrc_hide.append((ns[-1][1] * ticks_to_sec + threshold, float('inf')))
            logger.info(f"LRC 隐藏区间: {len(self._lrc_hide)} 段, threshold={threshold}s")

        # ---- 定时器（10ms ≈ 100fps，PreciseTimer 保证平滑） ----
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

        # 播放结束后的自动关闭定时器（单次触发，允许 closeEvent 提前停止）
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.timeout.connect(self.close)

        logger.debug("播放器 __init__ 完成")

    def _init_fonts(self):
        """初始化字体和度量缓存（屏幕尺寸变化后可重新调用）。

        逐字歌词字体（ust_lyric_font）用 word_lyric_font_family；
        其余文字（音名/LRC/信息/版权）用 info_font_family。
        """
        wff = self.word_lyric_font_family
        iff = self.info_font_family
        note_fs = max(int(self.h * 2 / 3 * 0.4), 50)
        lyric_fs = max(int(self.h * 0.03), 10)
        ust_lyric_fs = max(int(self.h * 2 / 3 * 0.2), 80)

        self.note_font = QFont(iff, note_fs, QFont.Weight.Bold)
        self.lyric_font = QFont(iff, lyric_fs)
        self.ust_lyric_font = QFont(wff, ust_lyric_fs, QFont.Weight.Bold)
        self.small_font = QFont(iff, 14)
        self._bold_small_font = QFont(iff, 14, QFont.Weight.Bold)
        self.copyright_font = QFont(iff, 12)

        # 缓存 QFontMetrics，避免每帧重复创建
        self._fm_note = QFontMetrics(self.note_font)
        self._fm_lyric = QFontMetrics(self.lyric_font)
        self._fm_ust_lyric = QFontMetrics(self.ust_lyric_font)
        self._fm_small = QFontMetrics(self.small_font)
        self._fm_copyright = QFontMetrics(self.copyright_font)

    def showEvent(self, event):
        """窗口显示后启动音频播放和定时器。"""
        super().showEvent(event)
        self._update_screen_size()
        logger.info(f"播放器窗口已显示 — 实际尺寸: {self.w}x{self.h}")

        # 如果有音频文件，同步播放音频
        if self._has_audio():
            self._media_player.setPosition(0)
            self._media_player.setPlaybackRate(self._playback_speed)
            self._media_player.play()
            self._audio_playing = True
            self.start_real_time = time.time()
            logger.info("音频开始播放")
        else:
            self.start_real_time = time.time()
            logger.info("无音频，使用系统计时")

        self._timer.start(10)
        # 全屏播放时隐藏鼠标
        if self._fullscreen:
            self.setCursor(Qt.CursorShape.BlankCursor)
        logger.debug("定时器已启动 (10ms, Precise)")

    def resizeEvent(self, event):
        """窗口大小变化时更新尺寸和字体。"""
        super().resizeEvent(event)
        self._update_screen_size()

    def hideEvent(self, event):
        """窗口隐藏时确保音频停止（仅在关闭流程中，避免最小化误触发清理）。"""
        if self._closing:
            self._cleanup_audio()
        super().hideEvent(event)

    def _has_audio(self) -> bool:
        """是否有可用的音频文件。"""
        return bool(self.audio_path) and os.path.exists(self.audio_path)

    def _cleanup_audio(self):
        """强制停止并释放音频资源（防重入）。"""
        if self._cleanup_done:
            return
        self._cleanup_done = True
        if self._audio_playing or self._media_player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self._media_player.stop()
            self._audio_playing = False
            logger.debug("音频已强制停止")
        # 断开信号，避免 deleteLater 后仍触发回调
        try:
            self._media_player.mediaStatusChanged.disconnect()
        except (TypeError, RuntimeError):
            pass
        # 清除音频输出并释放（类型存根要求 QAudioOutput，故忽略参数类型检查）
        self._media_player.setAudioOutput(None)  # type: ignore[arg-type]
        self._audio_output.deleteLater()
        self._media_player.deleteLater()

    def _update_screen_size(self):
        """用实际 widget 尺寸更新 w/h 并重建字体。"""
        new_w, new_h = self.width(), self.height()
        if new_w > 0 and new_h > 0 and (new_w != self.w or new_h != self.h):
            self.w, self.h = new_w, new_h
            self._init_fonts()

    def _on_media_status_changed(self, status):
        """音频媒体状态变化回调。"""
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._audio_playing = False
            self._audio_duration_ms = self._media_player.duration()
            logger.info("音频播放完毕")
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._audio_playing = False
            logger.error(f"音频文件无效: {self.audio_path}")

    def _on_media_error(self):
        """音频播放错误回调（编译版缺少后端插件时触发）。"""
        err = self._media_player.errorString()
        if not err:
            return
        pos = self._media_player.position()
        dur = self._media_player.duration()
        # 接近音频末尾（最后 3 秒）的解码错误通常是 FLAC/MP3 尾部填充或
        # 结束标签被误判为音频帧导致的良性警告，不影响正常播放到 EndOfMedia。
        if dur > 0 and pos > 0 and (dur - pos) < 3000:
            logger.debug(f"音频末尾解码警告（可忽略）: {err}")
        else:
            logger.error(f"音频播放错误: {err}")

    # ===================== 预计算音符 Tick 区间 =====================

    def _calc_note_tick_ranges(self):
        ranges = []
        # 如果音符有 position 字段，使用 USTX 绝对位置
        if self.notes and "position" in self.notes[0]:
            for note in self.notes:
                pos = note.get("position", 0)
                length = max(note.get("length", 480), 1)
                ranges.append([pos, pos + length, note])
        else:
            current_tick = 0
            for note in self.notes:
                length = max(note.get("length", 480), 1)
                ranges.append([current_tick, current_tick + length, note])
                current_tick += length
        return ranges

    # ===================== LRC 解析 =====================

    def _parse_lrc(self):
        self.multi_lrc_lines = parse_lrc_file(self.lrc_path)
        if self.multi_lrc_lines:
            max_langs = max((len(langs) for _, langs in self.multi_lrc_lines), default=1)
            logger.info(
                f"LRC 解析完成: {len(self.multi_lrc_lines)} 个时间点, 最大语言数 {max_langs}"
            )

    # ===================== 主循环 =====================

    def _tick(self):
        """定时器回调：统一使用系统时钟计算当前位置 → 更新绘制状态。"""
        try:
            # 统一使用系统时钟，不读取 _media_player.position()，避免双时钟源切换导致的各种边界问题。
            # 注意：USTX 走完（_finished）后若音频仍在播放，必须继续推进 _play_elapsed，
            # 否则左下角时间会提前冻结，与音频实际进度脱节。
            if not self._finished or self._audio_playing:
                self._play_elapsed = (time.time() - self.start_real_time) * self._playback_speed

            if self._finished:
                if not self._audio_playing:
                    self._timer.stop()
                    logger.info("播放完成，1秒后关闭窗口")
                    self._close_timer.start(1000)
                self._update_lrc()
                self.update()
                return

            current_tick = self._play_elapsed * self.tick_per_second

            # 播放结束（音符走完）
            if current_tick >= self.total_tick:
                self._current_lyric = self._get_end_text()
                self._current_note_name = ""
                self._current_note = None
                self._finished = True
                self._final_elapsed = self.total_tick / self.tick_per_second
                self.update()
                if self._audio_playing:
                    logger.info("音符播放完成，等待音频结束")
                else:
                    self._play_elapsed = self._final_elapsed
                    self._timer.stop()
                    logger.info("播放完成，1秒后关闭窗口")
                    self._close_timer.start(1000)
                return

            # 匹配当前音符（从上次位置开始查，加速扫描）
            self._refresh_note_state()

            self.update()  # 触发 paintEvent

        except Exception:
            logger.exception("_tick 异常")

    def _refresh_note_state(self):
        """根据当前 _play_elapsed 重新匹配音符、LRC 和背景色。"""
        current_tick = self._play_elapsed * self.tick_per_second

        if current_tick >= self.total_tick:
            self._current_lyric = self._get_end_text()
            self._current_note_name = ""
            self._current_note = None
            return

        # 匹配当前音符
        current_note = None
        hint = self._note_idx_hint
        ranges = self.note_tick_ranges
        n = len(ranges)

        if hint < n and ranges[hint][0] <= current_tick < ranges[hint][1]:
            current_note = ranges[hint][2]
        else:
            for i in range(hint, n):
                if ranges[i][0] <= current_tick < ranges[i][1]:
                    current_note = ranges[i][2]
                    self._note_idx_hint = i
                    break
            if current_note is None:
                for i in range(0, hint):
                    if ranges[i][0] <= current_tick < ranges[i][1]:
                        current_note = ranges[i][2]
                        self._note_idx_hint = i
                        break

        if current_note:
            self._process_note(current_note)
            self._current_note = current_note
        else:
            self._current_note = None
            self._current_lyric = self._get_silent_text()
            self._current_note_name = ""

        self._update_lrc()
        self._bg_color = self._get_bg_color()

    def _process_note(self, note: dict):
        """根据音符数据更新当前显示的歌字和音名。"""
        raw_lyric = note.get("lyric", "")
        note_num = note.get("note_num", 0)

        if raw_lyric == "R":
            self._current_lyric = self._get_silent_text()
            self._current_note_name = ""
        elif raw_lyric in ("-", "+"):
            self._current_lyric = self.last_valid_lyric or self._get_silent_text()
            self._current_note_name = self._get_pitch_text(note_num)
        else:
            self._current_lyric = raw_lyric
            self.last_valid_lyric = raw_lyric
            self._current_note_name = self._get_pitch_text(note_num)

    def _update_lrc(self):
        if not self.multi_lrc_lines:
            return
        try:
            new_idx = -1
            for i, (ts, _) in enumerate(self.multi_lrc_lines):
                if ts <= self._play_elapsed:
                    new_idx = i
                else:
                    break
            self.current_lrc_idx = new_idx
        except Exception:
            logger.exception("_update_lrc 异常")

    # ===================== 绘制（paintEvent） =====================

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            self._paint_content(painter)
        except Exception:
            logger.exception("paintEvent 异常")
        finally:
            painter.end()

    def _paint_content(self, painter: QPainter):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ww, wh = self.width(), self.height()
        painter.fillRect(0, 0, ww, wh, self._bg_color)
        cx, cy = ww // 2, wh // 2
        # 本帧颜色只解析一次
        lyric_rgb, note_rgb, curve_hex = self._get_note_colors()

        # ---- 音名 ----
        if self._current_note_name:
            note_c = QColor(*note_rgb)
            note_c.setAlpha(self.note_alpha)
            painter.setPen(note_c)
            painter.setFont(self.note_font)
            fm = self._fm_note
            tw = fm.horizontalAdvance(self._current_note_name)
            th = fm.height()
            pad = th * 0.2
            painter.drawText(
                QRectF(cx - tw / 2 - pad, cy - th / 2 - pad,
                       tw + pad * 2, th + pad * 2),
                Qt.AlignmentFlag.AlignCenter, self._current_note_name,
            )

        # ---- 音高线 ----
        if self.curve_show and self._current_note:
            note = self._current_note
            pb_data = note.get("pitch_bend", [])
            note_length = note.get("length", 0)
            note_idx = note.get("index", -1)
            if note_idx != self._last_pb_log_note_idx:
                logger.debug(
                    f"音高线: note_idx={note_idx}, pb_len={len(pb_data)}, "
                    f"note_len={note_length}, "
                    f"{'将绘制' if (pb_data and len(pb_data) >= 2 and note_length > 0) else '数据不足，跳过'}"
                )
                self._last_pb_log_note_idx = note_idx
            if pb_data and len(pb_data) >= 2 and note_length > 0:
                curve_width = note_length
                start_x = cx - curve_width // 2
                pb_count = len(pb_data)
                safe_top, safe_bottom = 100, wh - 100
                points = []
                for i in range(pb_count):
                    x = start_x + (i / (pb_count - 1)) * curve_width
                    y = cy - (pb_data[i] / 100) * (wh * 0.09)
                    # 超出安全区域时按比例压缩，避免音高线溢出屏幕
                    if y < safe_top:
                        exceed = safe_top - y
                        y = safe_top - exceed * max(0.3, 1 - (exceed / wh * 2))
                    elif y > safe_bottom:
                        exceed = y - safe_bottom
                        y = safe_bottom + exceed * max(0.3, 1 - (exceed / wh * 2))
                    y = max(50, min(y, wh - 50))
                    points.append(QPointF(x, y))
                if len(points) >= 2:
                    pen = QPen(QColor(curve_hex))
                    pen.setWidth(self.NOTE_LINE_WIDTH)
                    painter.setPen(pen)
                    painter.drawPolyline(QPolygonF(points))

        # ---- 逐字歌词 ----
        if self._current_lyric:
            lyric_c = QColor(*lyric_rgb)
            painter.setPen(lyric_c)
            painter.setFont(self.ust_lyric_font)
            tw = self._fm_ust_lyric.horizontalAdvance(self._current_lyric)
            th = self._fm_ust_lyric.height()
            pad = th * 0.2
            painter.drawText(
                QRectF(cx - tw / 2 - pad, cy - th / 2 - pad,
                       tw + pad * 2, th + pad * 2),
                Qt.AlignmentFlag.AlignCenter, self._current_lyric,
            )

        # ---- 左上角静态信息 ----
        painter.setPen(QColor(self.small_font_color_hex))
        y_off = 20
        if self.show_song_name and self.song_name:
            painter.setFont(self._bold_small_font)
            painter.drawText(20, y_off + 14, self.song_name)
            painter.setFont(self.small_font)
            y_off += 27
        if self.show_song_author and self.song_author:
            painter.drawText(20, y_off + 14, self.song_author)
            y_off += 25
        if self.show_ust_author and self.ust_author:
            painter.drawText(20, y_off + 14, self.ust_author)

        # BPM（右上角）
        if self.show_bpm:
            painter.setFont(self.small_font)
            bpm_text = f"BPM={self.tempo}"
            bpm_w = self._fm_small.horizontalAdvance(bpm_text)
            painter.drawText(ww - 20 - bpm_w, 34, bpm_text)

        # 播放时间（左下角）
        if self.show_play_time:
            painter.setFont(self.small_font)
            painter.drawText(20, wh - 20, format_play_time(self._play_elapsed))

        # LRC 歌词（自动隐藏：间奏或尾奏超阈值时隐藏；多语言垂直堆叠）
        if self.show_lyric and self.multi_lrc_lines and 0 <= self.current_lrc_idx < len(self.multi_lrc_lines):
            langs = self.multi_lrc_lines[self.current_lrc_idx][1]
            if langs:
                hidden = self.show_lyric_autohide and any(
                    s <= self._play_elapsed <= e for s, e in self._lrc_hide
                )
                if not hidden:
                    anchor_y = int(wh * 0.3) if self.lyric_pos == "上" else int(wh * 0.7)
                    painter.setPen(QColor(self.small_font_color_hex))
                    painter.setFont(self.lyric_font)
                    line_h = self._fm_lyric.height()
                    step = line_h * 1.3  # 行间距 = 0.3 × 字高
                    n = len(langs)
                    # 多语言向远离屏幕中心方向堆叠，避免与中央逐字大字重叠
                    if self.lyric_pos == "上":
                        top_baseline = anchor_y - (n - 1) * step  # 末行落在 anchor_y
                    else:
                        top_baseline = anchor_y                    # 首行落在 anchor_y
                    for i, text in enumerate(langs):
                        baseline = int(top_baseline + i * step)
                        text_w = self._fm_lyric.horizontalAdvance(text)
                        painter.drawText(ww // 2 - text_w // 2, baseline, text)

        # 倍率（底部中央，反色，一倍速不显示）
        if abs(self._playback_speed - 1.0) > 0.005:
            inv_r = 255 - self._bg_color.red()
            inv_g = 255 - self._bg_color.green()
            inv_b = 255 - self._bg_color.blue()
            painter.setPen(QColor(inv_r, inv_g, inv_b))
            painter.setFont(self.small_font)
            speed_text = f"x{self._playback_speed:.1f}"
            speed_w = self._fm_small.horizontalAdvance(speed_text)
            painter.drawText(ww // 2 - speed_w // 2, wh - 40, speed_text)

        # 版权（底部居中，可开关）
        if self.show_copyright:
            copy_c = QColor(195, 195, 195)
            copy_c.setAlpha(self.copyright_alpha)
            painter.setPen(copy_c)
            painter.setFont(self.copyright_font)
            copy_text = "ustxPlayer - v26g30 © 2026 SYEternalR"
            copy_w = self._fm_copyright.horizontalAdvance(copy_text)
            painter.drawText(ww // 2 - copy_w // 2, wh - 20, copy_text)

    def _get_note_colors(self):
        """根据当前音符的样式索引，返回 (lyric_rgb, note_rgb, pitch_curve_hex)。
        无音名显示（静默/结尾/R音符）时立即使用样式1。"""
        is_silent = self._finished or self._current_note_name == ""
        si = 0
        if not is_silent and self._note_styles and self._note_idx_hint is not None:
            si = self._note_styles.get(self._note_idx_hint, 0)
        if si < len(self._styles):
            p = self._styles[si]
            return (
                hex_to_rgb(validate_hex_color(p.get("lyric_color", "#ffffff"))),
                hex_to_rgb(validate_hex_color(p.get("note_color", "#6c6c6c"))),
                validate_hex_color(p.get("pitch_curve_color", "#ffffff")),
            )
        return self.ust_lyric_color, self.note_color, self.pitch_curve_color_hex

    def _get_bg_color(self):
        """根据当前音符样式返回背景色 QColor。全局背景优先级最高。"""
        if self._global_bg_enabled:
            return QColor(self._global_bg_color_hex)
        is_silent = self._finished or self._current_note_name == ""
        si = 0
        if not is_silent and self._note_styles and self._note_idx_hint is not None:
            si = self._note_styles.get(self._note_idx_hint, 0)
        if si < len(self._styles):
            return QColor(validate_hex_color(self._styles[si].get("bg_color", "#000000")))
        return self._bg_color

    # ===================== 文本生成 =====================

    def _get_silent_text(self) -> str:
        sd = self.silent_display
        if sd == "R":
            return "R"
        if sd == "♪":
            return "♪"
        if sd == "-":
            return "-"
        if sd == "自定义文字":
            return self.silent_custom_text or ""
        # "什么都不显示" 或其他未知值 → 不显示
        return ""

    def _get_end_text(self) -> str:
        ed = self.end_display
        if ed == "END":
            return "END"
        if ed == "-":
            return "-"
        if ed == "自定义文字":
            return self.end_custom_text or ""
        return ""

    def _get_pitch_text(self, note_num: int) -> str:
        """MIDI 号 → 音名，应用占位符规则。"""
        try:
            ori = self._midi_to_note(note_num)
            pure = _NOTE_PURE_RE.fullmatch(ori)
            sharp = _NOTE_SHARP_RE.fullmatch(ori)

            if sharp:
                return ori
            if pure:
                note, num = pure.group(1), pure.group(2)
                if self.pitch_placeholder == "无":
                    return f"{note}{num}"
                elif self.pitch_placeholder == "-":
                    return f"{note}-{num}"
                elif self.pitch_placeholder == "自定义文字":
                    suffix = self.pitch_custom_text.strip()
                    return f"{note}({suffix}){num}" if suffix else f"{note}{num}"
            return ori
        except Exception:
            logger.exception("_get_pitch_text 异常")
            return str(note_num)

    def _midi_to_note(self, midi_num: int) -> str:
        try:
            midi_num = int(midi_num)
            octave = (midi_num // 12) - 1
            return f"{self.NOTE_NAMES[midi_num % 12]}{octave}"
        except Exception:
            return str(midi_num)

    # ===================== 键盘/关闭事件 =====================

    def _get_max_play_time(self) -> float:
        """返回当前可达到的最大播放时间（秒）。

        当音频时长超过 USTX 时长时，允许快进到音频结尾；
        否则以 USTX 结尾为上限。无音频时仅以 USTX 结尾为准。
        """
        ustx_end = self.total_tick / self.tick_per_second
        if self._has_audio():
            # _audio_duration_ms 在 EndOfMedia 时记录；在此之前用 duration() 实时查询
            audio_ms = self._audio_duration_ms or self._media_player.duration()
            if audio_ms > 0:
                return max(ustx_end, audio_ms / 1000.0)
        return ustx_end

    def _set_speed(self, speed: float):
        """设置播放倍率，使用 setPlaybackRate 实现变速不变调。"""
        new_speed = max(0.5, min(3.0, speed))
        # 倍率切换前，依据当前 _play_elapsed 重新对齐 start_real_time，
        # 保证 _play_elapsed = (now - start_real_time) * speed 在切换瞬间连续，
        # 不被新倍率整体放大/缩小造成时间跳变。
        # 公式：start_real_time = now - _play_elapsed / new_speed
        self.start_real_time = time.time() - self._play_elapsed / new_speed
        self._playback_speed = new_speed
        logger.info(f"播放倍率: {self._playback_speed:.1f}")
        # 音频变速不变调
        if self._audio_playing:
            self._media_player.setPlaybackRate(self._playback_speed)
            # setPlaybackRate 是异步的，音频管线需要约 100-200ms 才能真正切换到新倍率。
            # 过渡期间解码器仍按旧倍率前进，而系统时钟已按新倍率前进，产生偏差。
            # 过渡稳定后读取一次音频实际位置做校准，消除累积偏移。
            # 注意：这是一次性校准，不是持续的双时钟切换。
            QTimer.singleShot(200, self._recalibrate_from_audio)
        self.update()  # 暂停时也刷新倍率显示

    def _recalibrate_from_audio(self):
        """倍率切换后的一次性音频位置校准。

        setPlaybackRate 异步生效，切换期间解码器与系统时钟会产生偏差。
        切换稳定后读取一次 _media_player.position() 校准 start_real_time，
        消除慢放→原速切换时的音画偏移。仅在偏差显著（>50ms）时才校准，
        避免不必要的时钟抖动。
        """
        if not self._audio_playing or self._finished or self._closing:
            return
        try:
            audio_pos = self._media_player.position() / 1000.0
            drift = audio_pos - self._play_elapsed
            if abs(drift) > 0.05:
                self._play_elapsed = audio_pos
                self.start_real_time = time.time() - self._play_elapsed / self._playback_speed
                logger.debug(
                    f"倍率切换后音频校准: drift={drift * 1000:.0f}ms, "
                    f"elapsed={self._play_elapsed:.3f}s"
                )
        except Exception:
            logger.debug("音频位置校准失败（忽略）")

    def _sync_seek_position(self):
        """快进/快退后同步位置并刷新音符、歌词、背景色。

        统一使用系统时钟计时，仅当快进目标在音频时长内时才操作 media_player。
        """
        pos_ms = int(self._play_elapsed * 1000)
        if self._has_audio():
            # 仅当音频未结束或快进位置在音频时长内才操作播放器
            if self._audio_duration_ms == 0 or pos_ms < self._audio_duration_ms:
                self._media_player.setPosition(pos_ms)
                if self._timer.isActive() and not self._audio_playing:
                    self._media_player.setPlaybackRate(self._playback_speed)
                    self._media_player.play()
                    self._audio_playing = True
            elif self._audio_playing:
                # 快进超出音频时长，停止播放器
                self._media_player.stop()
                self._audio_playing = False
        self.start_real_time = time.time() - self._play_elapsed / self._playback_speed
        self._refresh_note_state()

    def keyPressEvent(self, event):
        key = event.key()
        # ESC - 退出
        if key == Qt.Key.Key_Escape:
            self.close()
        # 空格 - 播放/暂停
        elif key == Qt.Key.Key_Space:
            if self._timer.isActive():
                self._timer.stop()
                if self._audio_playing:
                    self._media_player.pause()
                    self._audio_playing = False
            else:
                # 注意：不重置 _finished。_finished 的状态转换由 _tick（设 True）
                # 和左方向键（设 False）独占。若 USTX 已结束，恢复后 _tick 会自动
                # 走 _finished 分支继续推进音频时间，无需干预。
                self._timer.start(10)
                self.start_real_time = time.time() - self._play_elapsed / self._playback_speed
                if self._has_audio():
                    pos_ms = int(self._play_elapsed * 1000)
                    # 仅当音频未结束或目标位置在音频时长内才操作播放器
                    if self._audio_duration_ms == 0 or pos_ms < self._audio_duration_ms:
                        self._media_player.setPosition(pos_ms)
                        self._media_player.setPlaybackRate(self._playback_speed)
                        self._media_player.play()
                        self._audio_playing = True
        # 左方向键 - 快退10秒
        elif key == Qt.Key.Key_Left:
            self._finished = False
            self._play_elapsed = max(0.0, self._play_elapsed - 10.0)
            self._sync_seek_position()
            self.update()
        # 右方向键 - 快进10秒
        elif key == Qt.Key.Key_Right:
            max_time = self._get_max_play_time()
            self._play_elapsed = min(max_time, self._play_elapsed + 10.0)
            self._sync_seek_position()
            self.update()
        # 上方向键 - 系统音量+
        elif key == Qt.Key.Key_Up:
            step_system_volume(True)
        # 下方向键 - 系统音量-
        elif key == Qt.Key.Key_Down:
            step_system_volume(False)
        # X - 减速0.1
        elif key == Qt.Key.Key_X:
            self._set_speed(self._playback_speed - 0.1)
        # C - 加速0.1
        elif key == Qt.Key.Key_C:
            self._set_speed(self._playback_speed + 0.1)
        # Z - 还原1倍
        elif key == Qt.Key.Key_Z:
            self._set_speed(1.0)

    def closeEvent(self, event):
        """窗口关闭时停止音频并清理资源。"""
        self._closing = True
        self._timer.stop()
        self._close_timer.stop()
        self._cleanup_audio()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().closeEvent(event)


# ===================== 对外接口 =====================

def display(ust_info: dict) -> NoteLyricDisplay:
    """启动播放器窗口，返回窗口引用（调用方需保持引用防止 GC）。

    窗口标志必须在 show 之前统一设置，避免全屏与置顶标志冲突导致边角漏出。
    """
    logger.info("创建播放器窗口...")
    window = NoteLyricDisplay(ust_info)

    # ---- 在 show 之前统一设置所有窗口标志 ----
    if window._fullscreen:
        window.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        window.showFullScreen()
        logger.info("播放器全屏显示")
    else:
        window.setWindowFlags(Qt.WindowType.Window)
        window.show()
        logger.info("播放器窗口显示")
    return window
