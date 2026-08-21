# file_page.py — "文件" 导航页
"""USTX 文件选择和解析。"""

import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
)
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QObject

from qfluentwidgets import (
    LineEdit, PushButton, TextEdit, CheckBox,
    BodyLabel,
    InfoBar, InfoBarPosition,
)

from core.settings_manager import SettingsManager
from core.log import logger
import core.ustxreader as ur
from ui.accent_card import AccentHeaderCardWidget, PAGE_MARGIN, PAGE_SPACING


# ===================== 后台解析工作线程 =====================

class _ParseWorker(QObject):
    """在后台线程中解析 USTX 文件，避免阻塞 UI。"""
    finished = Signal(object)  # ustx_info dict
    failed = Signal(str)       # 错误信息

    def __init__(self, ustx_path: str, parent=None):
        super().__init__(parent)
        self._path = ustx_path

    def run(self):
        try:
            result = ur.get_ustx_info(self._path)
            self.finished.emit(result)
        except Exception as e:
            logger.exception("后台解析 USTX 失败")
            self.failed.emit(str(e))


class FilePage(QWidget):
    """文件选择页面 - 支持 USTX 文件解析。"""

    def __init__(self, settings: SettingsManager, parent=None):
        super().__init__(parent=parent)
        self._s = settings
        self._parse_thread: QThread | None = None  # 后台解析线程
        self._parse_worker: _ParseWorker | None = None
        self._parsing = False  # 是否正在解析
        self._pending_notes: list | None = None  # 延迟写入的音符数据
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*PAGE_MARGIN)
        layout.setSpacing(PAGE_SPACING)

        # ========== USTX 文件卡片 ==========
        ustx_card = AccentHeaderCardWidget("USTX 文件")
        ustx_vbox = QVBoxLayout()
        ustx_vbox.setSpacing(8)

        ustx_row = QHBoxLayout()
        ustx_row.setSpacing(8)
        ustx_row.addWidget(BodyLabel("USTX 文件:"))
        self.ustx_edit = LineEdit()
        self.ustx_edit.setPlaceholderText("请选择或拖入 .ustx 文件路径...")
        ustx_row.addWidget(self.ustx_edit, 1)
        self.select_ustx_btn = PushButton("选择 USTX")
        ustx_row.addWidget(self.select_ustx_btn)
        ustx_vbox.addLayout(ustx_row)

        self.cb_curve = CheckBox("显示音高线变化")
        self.cb_curve.setChecked(self._s.display.curve_show)
        ustx_vbox.addWidget(self.cb_curve)
        ustx_card.viewLayout.addLayout(ustx_vbox)
        layout.addWidget(ustx_card)

        # ========== 音频文件卡片 ==========
        audio_card = AccentHeaderCardWidget("音频文件")
        audio_vbox = QVBoxLayout()
        audio_vbox.setSpacing(8)

        audio_row = QHBoxLayout()
        audio_row.setSpacing(8)
        audio_row.addWidget(BodyLabel("音频文件:"))
        self.audio_edit = LineEdit()
        self.audio_edit.setPlaceholderText("请选择 .mp3/.wav/.flac 音频文件...")
        audio_row.addWidget(self.audio_edit, 1)
        self.select_audio_btn = PushButton("选择音频")
        audio_row.addWidget(self.select_audio_btn)
        audio_vbox.addLayout(audio_row)
        audio_card.viewLayout.addLayout(audio_vbox)
        layout.addWidget(audio_card)

        # ========== 歌词文件卡片 ==========
        lyric_card = AccentHeaderCardWidget("歌词文件")
        lyric_vbox = QVBoxLayout()
        lyric_vbox.setSpacing(8)

        self.cb_show_lyric = CheckBox("播放器中显示歌词")
        self.cb_show_lyric.setChecked(self._s.display.show_lyric)
        lyric_vbox.addWidget(self.cb_show_lyric)

        # 自动隐藏歌词
        autohide_row = QHBoxLayout()
        autohide_row.setSpacing(6)
        self.cb_autohide = CheckBox("间奏自动隐藏歌词")
        self.cb_autohide.setChecked(self._s.display.show_lyric_autohide)
        autohide_row.addWidget(self.cb_autohide)
        autohide_row.addWidget(BodyLabel("阈值(秒):"))
        self.autohide_threshold_edit = LineEdit()
        self.autohide_threshold_edit.setPlaceholderText("3.0")
        self.autohide_threshold_edit.setText(str(self._s.display.lyric_autohide_threshold))
        self.autohide_threshold_edit.setFixedWidth(50)
        autohide_row.addWidget(self.autohide_threshold_edit)
        autohide_row.addStretch()
        lyric_vbox.addLayout(autohide_row)

        lrc_row = QHBoxLayout()
        lrc_row.setSpacing(8)
        lrc_row.addWidget(BodyLabel("歌词文件 (.lrc):"))
        self.lyric_edit = LineEdit()
        self.lyric_edit.setPlaceholderText("请选择 .lrc 歌词文件...")
        lrc_row.addWidget(self.lyric_edit, 1)
        self.select_lyric_btn = PushButton("选择歌词")
        lrc_row.addWidget(self.select_lyric_btn)
        lyric_vbox.addLayout(lrc_row)
        lyric_card.viewLayout.addLayout(lyric_vbox)
        layout.addWidget(lyric_card)

        # ========== 解析结果卡片（无标题） ==========
        result_card = AccentHeaderCardWidget()
        result_vbox = QVBoxLayout()
        result_vbox.setSpacing(8)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.match_btn = PushButton("解析 USTX")
        self.match_btn.setEnabled(False)
        action_row.addWidget(self.match_btn)
        action_row.addStretch()
        result_vbox.addLayout(action_row)

        self.result_edit = TextEdit()
        self.result_edit.setReadOnly(True)
        self.result_edit.setPlaceholderText("点击 [解析 USTX] 查看解析结果...")
        self.result_edit.setMinimumHeight(200)
        result_vbox.addWidget(self.result_edit)
        result_card.viewLayout.addLayout(result_vbox)
        layout.addWidget(result_card)

    def _connect_signals(self):
        self.ustx_edit.textChanged.connect(self._on_ustx_path_changed)
        self.select_ustx_btn.clicked.connect(self._on_select_ustx)

        self.audio_edit.textChanged.connect(
            lambda v: setattr(self._s.project, "audio_path", v)
        )
        self.select_audio_btn.clicked.connect(self._on_select_audio)

        self.match_btn.clicked.connect(self._on_match)

        def _on_curve(v):
            setattr(self._s.display, "curve_show", v == Qt.CheckState.Checked)
        self.cb_curve.checkStateChanged.connect(_on_curve)

        self.cb_show_lyric.checkStateChanged.connect(
            lambda v: setattr(self._s.display, "show_lyric", v == Qt.CheckState.Checked)
        )

        self.cb_autohide.checkStateChanged.connect(
            lambda v: setattr(self._s.display, "show_lyric_autohide", v == Qt.CheckState.Checked)
        )
        self.autohide_threshold_edit.textChanged.connect(self._on_threshold_changed)

        self.lyric_edit.textChanged.connect(
            lambda v: setattr(self._s.player, "lrc_path", v)
        )
        self.select_lyric_btn.clicked.connect(self._on_select_lyric)

        # 监听设置变化同步到 UI
        self._s.project.ustx_path_changed.connect(self._on_settings_ustx_changed)
        self._s.ustx_notes_changed.connect(self._refresh_ustx_display)

    def _on_settings_ustx_changed(self, path: str):
        """Settings 端路径变化时同步到 UI。"""
        self._refresh_ustx_display()

    def _on_threshold_changed(self, text: str):
        """自动隐藏阈值：仅允许非负整数，非法输入自动取整。"""
        if not text or text == ".":
            return
        try:
            val = float(text)
            ival = round(val)
            if ival < 0:
                ival = 0
            self._s.display.lyric_autohide_threshold = float(ival)
            # 去除小数点显示
            if str(ival) != text:
                self.autohide_threshold_edit.blockSignals(True)
                self.autohide_threshold_edit.setText(str(ival))
                self.autohide_threshold_edit.blockSignals(False)
        except ValueError:
            pass

    def sync_all_from_settings(self):
        """从 settings 同步所有 UI 控件（含 USTX 三态显示）。"""
        s = self._s
        self._refresh_ustx_display()
        # 缓存存在时补渲染解析报告（覆盖对话框导入等不走 _on_parse_done 的路径）
        cached = s.cached_ustx_info or {}
        info = cached.get("info")
        if info:
            source = os.path.basename(s.project.ustx_path) if s.project.ustx_path.strip() else "工程内嵌"
            self._render_report(info, source)
        self.audio_edit.blockSignals(True)
        self.audio_edit.setText(s.project.audio_path)
        self.audio_edit.blockSignals(False)
        self.lyric_edit.blockSignals(True)
        self.lyric_edit.setText(s.player.lrc_path)
        self.lyric_edit.blockSignals(False)
        self.cb_show_lyric.setChecked(s.display.show_lyric)
        self.cb_curve.setChecked(s.display.curve_show)
        self.cb_autohide.setChecked(s.display.show_lyric_autohide)
        self.autohide_threshold_edit.blockSignals(True)
        self.autohide_threshold_edit.setText(str(int(s.display.lyric_autohide_threshold)))
        self.autohide_threshold_edit.blockSignals(False)

    def _refresh_ustx_display(self):
        """统一 USTX 栏三态：真实路径 / 工程内嵌数据 / 空。"""
        s = self._s
        path = s.project.ustx_path.strip()
        self.ustx_edit.blockSignals(True)
        if path:
            self.ustx_edit.setEnabled(True)
            self.ustx_edit.setText(path)
        elif s.cached_ustx_info and s.cached_ustx_info.get("info"):
            # 自包含工程：解析数据内嵌于 .uprj，不关联任何 USTX 文件
            self.ustx_edit.setEnabled(False)
            self.ustx_edit.setText("（工程文件已内嵌 USTX 数据）")
        else:
            self.ustx_edit.setEnabled(True)
            self.ustx_edit.setText("")
        self.ustx_edit.blockSignals(False)
        self._check_match_ready()

    def _on_select_ustx(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择USTX文件",
            os.path.dirname(self._s.project.ustx_path) if self._s.project.ustx_path else "",
            "USTX文件 (*.ustx);;所有文件 (*.*)",
        )
        if file_path:
            self.ustx_edit.setText(file_path)
            # 自动解析
            self._on_match()

    def _on_ustx_path_changed(self, path: str):
        """USTX 路径变化时更新 settings 和解析按钮状态。"""
        self._s.project.ustx_path = path
        self._check_match_ready()

    def _on_select_audio(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择音频文件",
            os.path.dirname(self._s.project.audio_path) if self._s.project.audio_path else "",
            "音频文件 (*.mp3 *.wav *.flac);;所有文件 (*.*)",
        )
        if file_path:
            self.audio_edit.setText(file_path)

    def _on_select_lyric(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择歌词文件",
            os.path.dirname(self._s.player.lrc_path) if self._s.player.lrc_path else "",
            "歌词文件 (*.lrc);;所有文件 (*.*)",
        )
        if file_path:
            self.lyric_edit.setText(file_path)

    def _check_match_ready(self):
        """检测是否选择了 USTX 文件，启用解析按钮。"""
        ustx_ok = bool(self._s.project.ustx_path.strip() and os.path.exists(self._s.project.ustx_path.strip()))
        self.match_btn.setEnabled(ustx_ok)

    def _on_match(self):
        """解析 USTX 文件（后台线程，不阻塞 UI）。"""
        if self._parsing:
            return
        # 工程名为空时自动使用 ustx 文件名（不含扩展名）
        if self._s.maybe_fill_project_name_from_ustx():
            InfoBar.success("提示", f"工程名为空，已自动填充为：{self._s.project.project_name}",
                            orient=Qt.Orientation.Vertical, duration=2000, parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
        ustx_path = self._s.project.ustx_path.strip()

        if not ustx_path or not os.path.exists(ustx_path):
            InfoBar.warning("提示", "USTX 文件无效", orient=Qt.Orientation.Vertical, duration=2000,
                           parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
            return

        self._parsing = True
        self.match_btn.setEnabled(False)
        self.match_btn.setText("解析中…")

        try:
            self._parse_thread = QThread(self)
            self._parse_worker = _ParseWorker(ustx_path)
            self._parse_worker.moveToThread(self._parse_thread)

            self._parse_thread.started.connect(self._parse_worker.run)
            self._parse_worker.finished.connect(self._on_parse_done)
            self._parse_worker.failed.connect(self._on_parse_failed)
            self._parse_thread.finished.connect(self._on_parse_thread_finished)

            self._parse_thread.start()
        except Exception:
            logger.exception("启动解析线程失败")
            self._parsing = False
            self.match_btn.setEnabled(True)
            self.match_btn.setText("解析 USTX")
            InfoBar.error("ERcode004", "解析未启动，请重试", orient=Qt.Orientation.Vertical, duration=2000,
                          parent=self.window(), position=InfoBarPosition.TOP_RIGHT)

    def _on_parse_thread_finished(self):
        """后台解析线程结束时清理引用。"""
        self._parse_thread = None
        self._parse_worker = None

    def _on_parse_done(self, ustx_info: dict):
        """后台解析完成回调（主线程）。"""
        self._parsing = False
        self.match_btn.setEnabled(True)
        self.match_btn.setText("解析 USTX")

        notes = ustx_info.get("notes", [])
        ustx_path = self._s.project.ustx_path.strip()
        # 缓存完整解析结果，供 _on_play 复用，避免重复解析同一文件
        self._s.cached_ustx_info = {"path": ustx_path, "info": ustx_info}

        if not notes:
            InfoBar.warning("提示", "文件中没有音符", orient=Qt.Orientation.Vertical, duration=2000,
                           parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
            return

        self._render_report(ustx_info, os.path.basename(ustx_path))

        # 延迟存储音符数据，避免表格重建阻塞当前帧
        self._pending_notes = notes
        QTimer.singleShot(0, self._apply_notes)

        InfoBar.success("解析完成", f"成功解析 {len(notes)} 个音符",
                       orient=Qt.Orientation.Vertical, duration=2000, parent=self.window(), position=InfoBarPosition.TOP_RIGHT)

    def _render_report(self, ustx_info: dict, source_label: str):
        """将解析数据渲染为文件页报告文本（.ustx 解析与工程内嵌共用）。"""
        notes = ustx_info.get("notes", [])
        tempos = ustx_info.get("tempos") or []
        bpm_seq = " → ".join(
            f"{t.get('bpm', 120):.1f}" for t in tempos if isinstance(t, dict)
        )
        tracks_info = ustx_info.get("tracks_info") or []
        empty_tracks = ustx_info.get("empty_tracks") or []
        info_lines = [
            "═══════════════════════════════════════",
            "     USTX 解析报告",
            "═══════════════════════════════════════",
            f"  文件:         {source_label}",
            f"  版本:         {ustx_info.get('version', 'unknown')}",
            (f"  BPM:         {bpm_seq}"
             if ustx_info.get('tempo_count', 0) > 1
             else f"  BPM:         {ustx_info.get('tempo', 120):.1f}"),
            f"  轨道:         {ustx_info.get('tracks', 1)} 条",
        ]
        # 人声轨（含空轨）按轨道号合并，全部缩进放在"轨道"之后
        all_tracks = {t.get("track_no"): t for t in tracks_info if isinstance(t, dict)}
        for t in empty_tracks:
            if isinstance(t, dict) and t.get("track_no") not in all_tracks:
                all_tracks[t.get("track_no")] = t
        for t in sorted(all_tracks.values(), key=lambda x: x.get("track_no", 0)):
            name = t.get("track_name") or f"轨道 {t.get('track_no', 0) + 1}"
            count = t.get("note_count", 0)
            if count:
                info_lines.append(f"    {name}:  {count} 音符")
            else:
                info_lines.append(f"    {name}:  空轨道，已忽略")
        if not all_tracks:
            info_lines.append("    （无音符数据）")
        if ustx_info.get("wave_part_count", 0):
            info_lines.append(f"    音频轨:  已忽略 {ustx_info['wave_part_count']} 条")
        info_lines.extend([
            f"  音符数:      {len(notes)}",
            "",
            "  解析完成",
            "═══════════════════════════════════════",
        ])
        self.result_edit.setPlainText("\n".join(line for line in info_lines if line is not None))

    def apply_embedded_ustx_data(self):
        """应用 .uprj 内嵌解析数据（拖拽/命令行加载路径，主线程调用）。

        同步生成解析报告；音符数据延迟到下一帧写入，与 .ustx 解析共用
        _apply_notes 恢复 note_styles，避免歌词表重建阻塞当前帧。
        """
        cached = self._s.cached_ustx_info or {}
        ustx_info = cached.get("info")
        if not ustx_info:
            return
        notes = ustx_info.get("notes", [])
        if not isinstance(notes, list):
            notes = []
        if not notes:
            InfoBar.warning("提示", "工程内没有音符", orient=Qt.Orientation.Vertical, duration=2000,
                           parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
            return
        self._render_report(ustx_info, "工程内嵌")
        self._pending_notes = notes
        QTimer.singleShot(0, self._apply_notes)
        InfoBar.success("加载完成", f"已加载 {len(notes)} 个音符",
                       orient=Qt.Orientation.Vertical, duration=2000, parent=self.window(), position=InfoBarPosition.TOP_RIGHT)

    def _apply_notes(self):
        """延迟应用解析结果到 Settings（表格重建在独立帧执行）。"""
        if self._pending_notes is not None:
            try:
                self._s.ustx_notes = self._pending_notes
                # 如果是 UPRJ 导入的延迟解析，恢复 note_styles
                self._s._apply_deferred_uprj_styles()
            finally:
                self._pending_notes = None

    def _on_parse_failed(self, err_msg: str):
        """后台解析失败回调（主线程）。"""
        self._parsing = False
        self.match_btn.setEnabled(True)
        self.match_btn.setText("解析 USTX")
        InfoBar.error("ERcode004", f"USTX 解析失败: {err_msg}", orient=Qt.Orientation.Vertical, duration=3000,
                     parent=self.window(), position=InfoBarPosition.TOP_RIGHT)

    def cleanup_parse_thread(self):
        """退出前等待后台解析线程结束，避免 QThread 仍在运行时被回收崩溃。"""
        if self._parse_thread is not None:
            try:
                self._parse_thread.quit()
                self._parse_thread.wait(3000)
            except Exception:
                logger.exception("等待解析线程结束失败")
            self._parse_thread = None
            self._parse_worker = None
