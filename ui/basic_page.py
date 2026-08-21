# basic_page.py — "基础" 导航页
"""工程信息、显示选项和播放控制。"""

import os
from typing import Optional, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
)

from qfluentwidgets import (
    LineEdit, PushButton, PrimaryPushButton, SwitchButton,
    BodyLabel,
    InfoBar, InfoBarPosition,
)

from core.log import logger
from core.settings_manager import SettingsManager
from core.uprj_io import ProjectFileMissingError
from ui.accent_card import AccentHeaderCardWidget, PAGE_MARGIN, PAGE_SPACING


class BasicPage(QWidget):
    """基础页 — 工程信息 + 显示选项 + Play。"""

    def __init__(self, settings: SettingsManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._s = settings
        self._play_callback: Optional[Callable] = None
        self._export_callback: Optional[Callable] = None
        # 以下属性在 _setup_ui 中通过 setattr 动态创建，此处显式声明类型供静态分析识别
        self.edit_project_name: LineEdit
        self.edit_song_name: LineEdit
        self.edit_song_author: LineEdit
        self.edit_ustx_author: LineEdit
        self.sw_show_bpm: SwitchButton
        self.sw_show_play_time: SwitchButton
        self.sw_show_song_name: SwitchButton
        self.sw_show_song_author: SwitchButton
        self.sw_show_ustx_author: SwitchButton
        self.sw_show_copyright: SwitchButton
        self._setup_ui()
        self._connect_signals()

    def set_play_callback(self, callback: Callable):
        self._play_callback = callback

    # ===================== UI 构建 =====================

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*PAGE_MARGIN)
        layout.setSpacing(PAGE_SPACING)

        # ---- 顶部按钮（无标题卡片包裹） ----
        btn_card = AccentHeaderCardWidget()
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self.import_btn = PushButton("导入工程")
        self.export_btn = PushButton("保存工程")
        self.video_export_btn = PrimaryPushButton("视频导出")
        btn_row.addWidget(self.import_btn)
        btn_row.addWidget(self.export_btn)
        btn_row.addWidget(self.video_export_btn)
        btn_row.addStretch()
        btn_card.viewLayout.addLayout(btn_row)
        layout.addWidget(btn_card)

        # ---- 工程信息卡片 ----
        info_card = AccentHeaderCardWidget("工程信息")
        info_vbox = QVBoxLayout()
        info_vbox.setSpacing(8)
        self._add_field(info_vbox, "工程名：", "project_name")
        self._add_field(info_vbox, "曲名&曲师：", "song_name")
        self._add_field(info_vbox, "MIDI作者：", "song_author")
        self._add_field(info_vbox, "调音师：", "ustx_author")
        info_card.viewLayout.addLayout(info_vbox)
        layout.addWidget(info_card)

        # ---- 显示选项卡片（Switch 双列网格） ----
        display_card = AccentHeaderCardWidget("显示选项")
        display_vbox = QVBoxLayout()
        display_vbox.setSpacing(8)
        switches = [
            ("显示BPM",     "show_bpm"),
            ("显示播放时间", "show_play_time"),
            ("曲名&曲师", "show_song_name"),
            ("显示MIDI作者", "show_song_author"),
            ("显示调音师",   "show_ustx_author"),
            ("显示软件版权信息", "show_copyright"),
        ]
        cols = 2
        for i in range(0, len(switches), cols):
            row = QHBoxLayout()
            row.setSpacing(0)
            batch = switches[i:i + cols]
            for label, attr in batch:
                cell = QHBoxLayout()
                cell.setContentsMargins(0, 2, 0, 2)
                sw = SwitchButton()
                cell.addWidget(sw)
                cell.addWidget(BodyLabel(label))
                cell.addStretch()
                row.addLayout(cell)
                setattr(self, f"sw_{attr}", sw)
            # 补空列保持对齐
            for _ in range(cols - len(batch)):
                row.addStretch(1)
            display_vbox.addLayout(row)
        display_card.viewLayout.addLayout(display_vbox)
        layout.addWidget(display_card)

        layout.addStretch()

        # ---- Play 按钮 ----
        self.play_btn = PrimaryPushButton("播放 Play")
        self.play_btn.setMinimumHeight(40)
        layout.addWidget(self.play_btn)

    def _add_field(self, parent_layout: QVBoxLayout, label: str, attr: str):
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = BodyLabel(label)
        lbl.setMinimumWidth(90)
        row.addWidget(lbl)
        edit = LineEdit()
        edit.setPlaceholderText(f"请输入{label.removesuffix('：')}")
        row.addWidget(edit, 1)
        setattr(self, f"edit_{attr}", edit)
        parent_layout.addLayout(row)

    # ===================== 信号绑定 =====================

    def _connect_signals(self):
        s = self._s

        # 初始值 → UI
        self.edit_project_name.setText(s.project.project_name)
        self.edit_song_name.setText(s.project.song_name)
        self.edit_song_author.setText(s.project.song_author)
        self.edit_ustx_author.setText(s.project.ustx_author)
        self.sw_show_bpm.setChecked(s.display.show_bpm)
        self.sw_show_play_time.setChecked(s.display.show_play_time)
        self.sw_show_song_name.setChecked(s.display.show_song_name)
        self.sw_show_song_author.setChecked(s.display.show_song_author)
        self.sw_show_ustx_author.setChecked(s.display.show_ustx_author)
        self.sw_show_copyright.setChecked(s.display.show_copyright)

        # UI → settings
        self.edit_project_name.textChanged.connect(lambda v: setattr(s.project, "project_name", v))
        self.edit_song_name.textChanged.connect(lambda v: setattr(s.project, "song_name", v))
        self.edit_song_author.textChanged.connect(lambda v: setattr(s.project, "song_author", v))
        self.edit_ustx_author.textChanged.connect(lambda v: setattr(s.project, "ustx_author", v))
        self.sw_show_bpm.checkedChanged.connect(lambda v: setattr(s.display, "show_bpm", v))
        self.sw_show_play_time.checkedChanged.connect(lambda v: setattr(s.display, "show_play_time", v))
        self.sw_show_song_name.checkedChanged.connect(lambda v: setattr(s.display, "show_song_name", v))
        self.sw_show_song_author.checkedChanged.connect(lambda v: setattr(s.display, "show_song_author", v))
        self.sw_show_ustx_author.checkedChanged.connect(lambda v: setattr(s.display, "show_ustx_author", v))
        self.sw_show_copyright.checkedChanged.connect(lambda v: setattr(s.display, "show_copyright", v))

        # 按钮
        self.import_btn.clicked.connect(self._on_import)
        self.export_btn.clicked.connect(self._on_export)
        self.video_export_btn.clicked.connect(self._on_video_export)
        self.play_btn.clicked.connect(self._on_play)

    # ===================== 业务逻辑 =====================

    def _on_import(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开工程文件", self._s.last_open_dir,
            "ustxPlayer工程文件 (*.uprj);;所有文件 (*.*)",
        )
        if not file_path:
            return
        try:
            self._s.import_uprj(file_path)
            self._s.last_open_dir = os.path.dirname(file_path)
            self._s.write_settings()
            InfoBar.success("成功", f"已加载工程：{file_path}", orient=Qt.Orientation.Vertical, duration=2000,
                            parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
        except ProjectFileMissingError as e:
            # 配置已加载到内存，仅文件路径无效：同步 UI 供用户重新选择文件
            self._s.last_open_dir = os.path.dirname(file_path)
            self._s.write_settings()
            InfoBar.error("ERcode007", f"工程已加载，但以下文件路径无效：\n{e}",
                          orient=Qt.Orientation.Vertical, duration=5000, parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
        except Exception as e:
            logger.exception("加载文件失败")
            InfoBar.error("ERcode007", f"加载文件失败：{e}", orient=Qt.Orientation.Vertical, duration=3000,
                          parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
        finally:
            # 无论成功还是文件缺失，均需同步 UI（配置已重置+加载）
            self._sync_ui_from_settings()

    def _on_export(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出你的工程文件",
            os.path.join(self._s.last_export_dir, self._s.project.project_name or "未命名"),
            "ustxPlayer工程文件 (*.uprj);;所有文件 (*.*)",
        )
        if not file_path:
            return
        try:
            self._s.export_uprj(file_path)
            self._s.last_export_dir = os.path.dirname(file_path)
            self._s.write_settings()
            InfoBar.success("成功", f"工程已导出到：{file_path}", orient=Qt.Orientation.Vertical, duration=2000,
                            parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
        except Exception as e:
            logger.exception("导出失败")
            InfoBar.error("ERcode005", f"导出失败：{e}", orient=Qt.Orientation.Vertical, duration=3000,
                          parent=self.window(), position=InfoBarPosition.TOP_RIGHT)

    def _on_play(self):
        if self._play_callback:
            self._play_callback()

    def _on_video_export(self):
        if self._export_callback:
            self._export_callback()

    def set_export_callback(self, callback: Callable):
        self._export_callback = callback

    def _sync_ui_from_settings(self):
        s = self._s
        self.edit_project_name.setText(s.project.project_name)
        self.edit_song_name.setText(s.project.song_name)
        self.edit_song_author.setText(s.project.song_author)
        self.edit_ustx_author.setText(s.project.ustx_author)
        self.sw_show_bpm.setChecked(s.display.show_bpm)
        self.sw_show_play_time.setChecked(s.display.show_play_time)
        self.sw_show_song_name.setChecked(s.display.show_song_name)
        self.sw_show_song_author.setChecked(s.display.show_song_author)
        self.sw_show_ustx_author.setChecked(s.display.show_ustx_author)
        self.sw_show_copyright.setChecked(s.display.show_copyright)

    def sync_all_from_settings(self):
        self._sync_ui_from_settings()
