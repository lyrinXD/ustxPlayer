# renderer_core.py — 共享渲染核心
"""给定时间点 + QPainter 画一帧的纯渲染核心。

实时播放（NoteLyricDisplay）与视频导出（VideoExporter）共用：
状态推进（set_time）与绘制（paint）走同一条路径，保证两边画面一致。
不持有 QMediaPlayer / QTimer / 播放倍率 / 系统时钟，计时器由调用方自行叠加。
"""

import os
import re
import sys
from datetime import timedelta
from typing import List, Tuple, Optional

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QColor, QFont, QFontMetrics, QPen, QPolygonF,
)

from core.log import logger
from core.time_axis import TimeAxis


# 版本号：从项目根目录 VERSION 文件读取（单一真相源，与 build.bat / other_page 共用）
def _read_version() -> str:
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "VERSION")
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "0.0.0"


APP_VERSION = _read_version()


# 音名正则
_NOTE_PURE_RE = re.compile(r'([A-G])(\d+)')
_NOTE_SHARP_RE = re.compile(r'([A-G]#)(\d+)')

# 多语言分组阈值：连续行时间戳相差 ≤ 此值视为同一行的多语言
# - 交错格式：连续 2~3 行时间戳相差 1~5ms
# - 独立格式：排序后不同块中相同时间戳的行也聚到一起
# - 单语言文件：每行间隔远大于此值，每行自成一组
_LRC_GROUP_THRESHOLD = 0.020  # 20ms

# LRC 时间戳正则（兼容 2 位或 3 位毫秒）
_LRC_TIMESTAMP_RE = re.compile(r'\[(\d{1,2}):(\d{1,2})\.(\d{2,3})\]([^\[]*)')

# 多语言 LRC 文件尝试解码的编码顺序
_LRC_ENCODINGS = ['utf-8-sig', 'utf-8', 'gbk', 'gb2312', 'cp932']


# ===================== 工具函数 =====================

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


def calc_total_tick(notes: List[dict]) -> int:
    """音符总 tick：有 position 时取最晚结束的位置+长度，否则按 length 顺序累加。"""
    if notes and "position" in notes[0]:
        return max(
            n.get("position", 0) + max(n.get("length", 480), 1) for n in notes
        )
    return sum(max(n.get("length", 480), 1) for n in notes)


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


class RendererCore:
    """纯渲染核心：持有渲染状态，负责状态推进与绘制。"""

    NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    NOTE_LINE_WIDTH = 5  # 音高线线宽（1080p 基准，实际值经 scaled() 后存 note_line_width）
    COPYRIGHT_TEXT = f"ustxPlayer - {APP_VERSION} © 2026 SYEternalR"

    def __init__(self, ustx_info: dict, width: int = 1920, height: int = 1080):
        self.w, self.h = width, height

        # ---- 背景色 ----
        self._bg_color = QColor(validate_hex_color(
            ustx_info["player_style"].get("bg_color", "#000000")
        ))

        # ---- 核心数据 ----
        self.notes = ustx_info.get("notes", [])
        self.tempo = ustx_info.get("tempo", 120)
        self.last_valid_lyric = ""
        pb_notes = sum(1 for n in self.notes if len(n.get("pitch_bend", [])) >= 2)
        logger.info(
            f"渲染核心初始化 — 音符数={len(self.notes)}, BPM={self.tempo}, "
            f"含PitchBend的音符={pb_notes}"
        )

        # ---- 时间轴 ----
        self.tick_per_second = (self.tempo * 480) / 60
        self.total_tick = calc_total_tick(self.notes)
        self.note_tick_ranges = self._calc_note_tick_ranges()
        self.time_axis = TimeAxis(
            ustx_info.get("tempos") or [], ustx_info.get("tempo", 120.0)
        )
        self._current_bpm = self.tempo
        logger.debug(
            f"时间轴 — tick_per_second={self.tick_per_second:.1f}, "
            f"total_tick={self.total_tick}"
        )

        # ---- 显示开关 ----
        sc = ustx_info["show_config"]
        self.show_bpm = sc.get("bpm", True)
        self.show_play_time = sc.get("play_time", True)
        self.show_song_name = sc.get("song_name", True)
        self.show_song_author = sc.get("song_author", True)
        self.show_ustx_author = sc.get("ustx_author", True)
        self.show_copyright = sc.get("copyright", True)
        self.show_lyric = sc.get("lyric", True)
        self.show_lyric_autohide = sc.get("lyric_autohide", True)
        self.lyric_autohide_threshold = sc.get("lyric_autohide_threshold", 3.0)
        self.curve_show = sc.get("curve_show", False)

        # ---- 工程信息 ----
        pi = ustx_info.get("project_info", {})
        self.song_name = pi.get("song_name", "")
        self.song_author = pi.get("song_author", "")
        self.ustx_author = pi.get("ustx_author", "")

        # ---- 播放器样式 ----
        ps = ustx_info["player_style"]
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
        self.ustx_lyric_color = hex_to_rgb(
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

        # ---- LRC 歌词（多语言分组：每项为 (timestamp, [lang1, lang2, ...])）----
        self.multi_lrc_lines: List[Tuple[float, List[str]]] = []
        self.current_lrc_idx = -1
        if self.show_lyric and self.lrc_path:
            self._parse_lrc()

        # ---- 当前渲染状态 ----
        self._play_elapsed = 0.0
        self._current_lyric = ""
        self._current_note_name = ""
        self._current_note: Optional[dict] = None
        self._note_idx_hint = 0
        self._finished = False

        # ---- 字体 ----
        self._init_fonts()

        # ---- 预计算 LRC 隐藏区间（按歌曲时间） ----
        to_sec = self.time_axis.tick_to_seconds
        threshold = self.lyric_autohide_threshold
        self._lrc_hide: List[Tuple[float, float]] = []
        if self.show_lyric and self.show_lyric_autohide and self.notes:
            ns = [(n.get('position', 0), n.get('position', 0) + n.get('length', 0)) for n in self.notes]
            for i in range(len(ns) - 1):
                gap = to_sec(ns[i+1][0]) - to_sec(ns[i][1])
                if gap > threshold:
                    self._lrc_hide.append((to_sec(ns[i][1]) + threshold, to_sec(ns[i+1][0])))
            self._lrc_hide.append((to_sec(ns[-1][1]) + threshold, float('inf')))
            logger.info(f"LRC 隐藏区间: {len(self._lrc_hide)} 段, threshold={threshold}s")

        # ===================== 字体与尺寸 =====================

    def scaled(self, base: int, minimum: int = 0) -> int:
        """按 1080p 基准等比缩放：max(round(base * h / 1080), minimum)。

        所有字号、音高线宽、安全边距等像素尺寸统一走这里，不各自写死。
        """
        return max(round(base * self.h / 1080), minimum)

    def _init_fonts(self):
        """初始化字体和度量缓存（分辨率变化后可重新调用）。

        所有字号统一经 scaled() 按「1080p 基准值 × 画面高度比例」缩放，
        保证各元素相对大小一致，不各自为政。
        """
        wff = self.word_lyric_font_family
        iff = self.info_font_family

        note_fs = self.scaled(288, 50)      # 中央音名
        lyric_fs = self.scaled(32, 10)      # LRC 歌词
        ustx_lyric_fs = self.scaled(144, 80)  # 逐字歌词
        small_fs = self.scaled(15, 9)       # 四角信息/播放时间
        copyright_fs = self.scaled(13, 9)   # 版权

        self.note_font = QFont(iff, note_fs, QFont.Weight.Bold)
        self.lyric_font = QFont(iff, lyric_fs)
        self.ustx_lyric_font = QFont(wff, ustx_lyric_fs, QFont.Weight.Bold)
        self.small_font = QFont(iff, small_fs)
        self._bold_small_font = QFont(iff, small_fs, QFont.Weight.Bold)
        self.copyright_font = QFont(iff, copyright_fs)
        self.timer_font = QFont(iff, small_fs)  # 播放时间与四角信息同号
        self.note_line_width = self.scaled(self.NOTE_LINE_WIDTH, 3)

        # 缓存 QFontMetrics，避免每帧重复创建
        self._fm_note = QFontMetrics(self.note_font)
        self._fm_lyric = QFontMetrics(self.lyric_font)
        self._fm_ustx_lyric = QFontMetrics(self.ustx_lyric_font)
        self._fm_small = QFontMetrics(self.small_font)
        self._fm_copyright = QFontMetrics(self.copyright_font)
        self._fm_timer = QFontMetrics(self.timer_font)

    def set_resolution(self, w: int, h: int):
        """窗口/导出分辨率变化时更新尺寸和字体。"""
        if w > 0 and h > 0 and (w != self.w or h != self.h):
            self.w, self.h = w, h
            self._init_fonts()

    # ===================== 状态推进 =====================

    def set_time(self, elapsed: float):
        """推进到指定时间点，刷新当前音符、歌词、背景色等渲染状态。"""
        self._play_elapsed = elapsed
        self._refresh_note_state()

    @property
    def play_elapsed(self) -> float:
        return self._play_elapsed

    @property
    def finished(self) -> bool:
        return self._finished

    def set_finished(self, value: bool):
        """播放器告知结束状态（END 文本/颜色由渲染核心统一处理）。"""
        self._finished = value

    @property
    def current_lyric(self) -> str:
        return self._current_lyric

    @property
    def current_note(self) -> Optional[dict]:
        return self._current_note

    @property
    def current_note_name(self) -> str:
        return self._current_note_name

    @property
    def note_idx_hint(self) -> int:
        return self._note_idx_hint

    @property
    def duration_seconds(self) -> float:
        """USTX 内容总时长（秒），按 tempos 分段换算，支持变速。"""
        return self.time_axis.tick_to_seconds(self.total_tick)

    @property
    def lrc_idx(self) -> int:
        return self.current_lrc_idx

    @property
    def bg_color(self) -> QColor:
        return self._bg_color

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

    # ===================== 音符/LRC 状态刷新 =====================

    def _refresh_note_state(self):
        """根据当前 _play_elapsed 重新匹配音符、LRC 和背景色。"""
        current_tick = self.time_axis.seconds_to_tick(self._play_elapsed)
        self._current_bpm = self.time_axis.bpm_at_tick(current_tick)
        # 浮点误差下恰好等于 total_tick 的边界时刻钳制到 total_tick 本身，
        # 让它落进最后一个音符区间，避免边界帧提前闪现 END。
        if self.total_tick - 1e-6 <= current_tick < self.total_tick:
            current_tick = self.total_tick

        if current_tick >= self.total_tick or self._finished:
            self._current_lyric = self.get_end_text()
            self._current_note_name = ""
            self._current_note = None
            self._update_lrc()
            self._bg_color = self._get_bg_color()
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
            self._current_lyric = self.get_silent_text()
            self._current_note_name = ""

        self._update_lrc()
        self._bg_color = self._get_bg_color()

    def _process_note(self, note: dict):
        """根据音符数据更新当前显示的歌字和音名。"""
        raw_lyric = note.get("lyric", "")
        note_num = note.get("note_num", 0)

        if raw_lyric == "R":
            self._current_lyric = self.get_silent_text()
            self._current_note_name = ""
        elif raw_lyric in ("-", "+"):
            self._current_lyric = self.last_valid_lyric or self.get_silent_text()
            self._current_note_name = self.get_pitch_text(note_num)
        else:
            self._current_lyric = raw_lyric
            self.last_valid_lyric = raw_lyric
            self._current_note_name = self.get_pitch_text(note_num)

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

    def _pitch_polyline_points(self, note, note_length, start_x, curve_width, cy, wh):
        """构建当前音符的音高线折线（借鉴 OpenUTAU ExpressionCanvas）：
        pitd 相邻点直接线性连接；无数据 = 默认值 0 = 整条水平线；
        首尾数据不足处延伸到默认值 0，不在缺口补零（避免竖线毛刺）。"""
        pb_ticks = note.get("pitch_ticks", [])
        pb_data = note.get("pitch_bend", [])
        pts = [(t, v) for t, v in zip(pb_ticks, pb_data)]
        raw = []
        if pts:
            if pts[0][0] > 0:
                raw.append((0, 0))
            raw.extend(pts)
            if pts[-1][0] < note_length:
                raw.append((note_length, 0))
        else:
            raw = [(0, 0), (note_length, 0)]
        return [
            QPointF(start_x + (t / note_length) * curve_width,
                    cy - (v / 100) * (wh * 0.09))
            for t, v in raw
        ]

    # ===================== 绘制 =====================

    def paint(self, painter: QPainter, ww: int, wh: int, playback_speed: float = 1.0):
        """画一帧（不含计时器，计时器由调用方叠加）。"""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
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
            note_length = note.get("length", 0)
            if note_length > 0:
                # 宽度随分辨率等比缩放（与字体同 1080p 基准），长音符封顶防横向溢出；
                # X 仍按 tick 真实比例映射
                curve_width = min(int(note_length * 1.5 * self.h / 1080), int(ww * 0.9))
                start_x = cx - curve_width / 2
                safe_margin = self.scaled(100, 36)
                max_dev = (wh - 2 * safe_margin) / 2
                points = self._pitch_polyline_points(note, note_length, start_x, curve_width, cy, wh)
                # 超出安全带宽时整条曲线统一等比压缩，保留形状且不压平/贴边
                max_d = max((abs(p.y() - cy) for p in points), default=0) or 1.0
                k = max_dev / max_d if max_d > max_dev else 1.0
                if k != 1.0:
                    points = [QPointF(p.x(), cy + (p.y() - cy) * k) for p in points]
                if len(points) >= 2:
                    pen = QPen(QColor(curve_hex))
                    pen.setWidth(self.note_line_width)
                    painter.setPen(pen)
                    painter.drawPolyline(QPolygonF(points))

        # ---- 逐字歌词 ----
        if self._current_lyric:
            lyric_c = QColor(*lyric_rgb)
            painter.setPen(lyric_c)
            painter.setFont(self.ustx_lyric_font)
            tw = self._fm_ustx_lyric.horizontalAdvance(self._current_lyric)
            th = self._fm_ustx_lyric.height()
            pad = th * 0.2
            painter.drawText(
                QRectF(cx - tw / 2 - pad, cy - th / 2 - pad,
                       tw + pad * 2, th + pad * 2),
                Qt.AlignmentFlag.AlignCenter, self._current_lyric,
            )

        # ---- 左上角静态信息（边距与行距随分辨率等比缩放）----
        painter.setPen(QColor(self.small_font_color_hex))
        painter.setFont(self.small_font)
        margin_x = max(12, int(ww * 0.01))
        margin_y = max(12, int(wh * 0.018))
        fm_small = self._fm_small
        line_step = max(int(fm_small.height() * 1.15), 16)
        y = margin_y + fm_small.ascent()
        if self.show_song_name and self.song_name:
            painter.setFont(self._bold_small_font)
            painter.drawText(margin_x, y, self.song_name)
            painter.setFont(self.small_font)
            y += line_step
        if self.show_song_author and self.song_author:
            painter.drawText(margin_x, y, self.song_author)
            y += line_step
        if self.show_ustx_author and self.ustx_author:
            painter.drawText(margin_x, y, self.ustx_author)

        # BPM（右上角）
        if self.show_bpm:
            painter.setFont(self.small_font)
            bpm_text = f"BPM={self._current_bpm:.1f}"
            bpm_w = self._fm_small.horizontalAdvance(bpm_text)
            painter.drawText(ww - margin_x - bpm_w, margin_y + self._fm_small.ascent(), bpm_text)

        # LRC 歌词（自动隐藏：间奏或尾奏超阈值时隐藏；多语言垂直堆叠）
        if self.show_lyric and self.multi_lrc_lines and 0 <= self.current_lrc_idx < len(self.multi_lrc_lines):
            langs = self.multi_lrc_lines[self.current_lrc_idx][1]
            if langs and not self.is_lrc_hidden():
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

        # 版权（底部居中，可开关）；倍速小字固定显示在版权行上方，避免重叠
        copy_baseline = wh - margin_y - self._fm_copyright.descent()
        if self.show_copyright:
            copy_c = QColor(195, 195, 195)
            copy_c.setAlpha(self.copyright_alpha)
            painter.setPen(copy_c)
            painter.setFont(self.copyright_font)
            copy_w = self._fm_copyright.horizontalAdvance(self.COPYRIGHT_TEXT)
            painter.drawText(ww // 2 - copy_w // 2, copy_baseline, self.COPYRIGHT_TEXT)

        # 倍率（版权上方一行，反色，一倍速不显示；行距随分辨率走 scaled()）
        if abs(playback_speed - 1.0) > 0.005:
            inv_r = 255 - self._bg_color.red()
            inv_g = 255 - self._bg_color.green()
            inv_b = 255 - self._bg_color.blue()
            painter.setPen(QColor(inv_r, inv_g, inv_b))
            painter.setFont(self.small_font)
            speed_text = f"x{playback_speed:.1f}"
            speed_w = self._fm_small.horizontalAdvance(speed_text)
            speed_baseline = copy_baseline - self._fm_copyright.height() - self.scaled(8, 4)
            painter.drawText(ww // 2 - speed_w // 2, speed_baseline, speed_text)

    # ===================== 帧跳过签名 =====================

    def frame_signature(self) -> tuple:
        """当前帧的可见状态签名，用于导出帧跳过判断。"""
        bg = self._bg_color
        return (
            self._note_idx_hint,
            self._current_lyric,
            self._current_note_name,
            round(self._current_bpm, 2),
            self.current_lrc_idx,
            self.is_lrc_hidden(),
            (bg.red(), bg.green(), bg.blue()),
        )

    def is_lrc_hidden(self) -> bool:
        """当前时间 LRC 是否处于自动隐藏区间。"""
        if not (self.show_lyric_autohide and self._lrc_hide):
            return False
        return any(
            s <= self._play_elapsed <= e for s, e in self._lrc_hide
        )

    # ===================== 颜色 =====================

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
        return self.ustx_lyric_color, self.note_color, self.pitch_curve_color_hex

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
        return QColor(self._bg_color)

    # ===================== 文本生成 =====================

    def get_silent_text(self) -> str:
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

    def get_end_text(self) -> str:
        ed = self.end_display
        if ed == "END":
            return "END"
        if ed == "-":
            return "-"
        if ed == "自定义文字":
            return self.end_custom_text or ""
        return ""

    def get_pitch_text(self, note_num: int) -> str:
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
