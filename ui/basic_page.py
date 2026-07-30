# basic_page.py — "基础" 导航页
"""项目信息、显示选项和播放控制。"""

import os
from typing import Optional, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
)

from qfluentwidgets import (
    LineEdit, PushButton, PrimaryPushButton, SwitchButton,
    BodyLabel, StrongBodyLabel, HorizontalSeparator,
    InfoBar, InfoBarPosition,
)

from core.log import logger
from core.settings_manager import SettingsManager, ProjectFileMissingError


class BasicPage(QWidget):
    """基础页 — 项目信息 + 显示选项 + Play。"""

    def __init__(self, settings: SettingsManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._s = settings
        self._play_callback: Optional[Callable] = None
        # 以下属性在 _setup_ui 中通过 setattr 动态创建，此处显式声明类型供静态分析识别
        self.edit_project_name: LineEdit
        self.edit_song_name: LineEdit
        self.edit_song_author: LineEdit
        self.edit_ust_author: LineEdit
        self.sw_show_bpm: SwitchButton
        self.sw_show_play_time: SwitchButton
        self.sw_show_song_name: SwitchButton
        self.sw_show_song_author: SwitchButton
        self.sw_show_ust_author: SwitchButton
        self.sw_show_copyright: SwitchButton
        self._setup_ui()
        self._connect_signals()

    def set_play_callback(self, callback: Callable):
        self._play_callback = callback

    # ===================== UI 构建 =====================

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        # ---- 顶部按钮 ----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self.import_btn = PushButton("导入项目")
        self.export_btn = PushButton("保存项目")
        btn_row.addWidget(self.import_btn)
        btn_row.addWidget(self.export_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addWidget(HorizontalSeparator())

        # ---- 关于项目 ----
        self._add_section_title(layout, "/ 关于项目")
        self._add_field(layout, "项目名：", "project_name")
        self._add_field(layout, "曲名&曲师：", "song_name")
        self._add_field(layout, "MIDI作者：", "song_author")
        self._add_field(layout, "调音师：", "ust_author")
        layout.addWidget(HorizontalSeparator())

        # ---- 显示选项（Switch 双列网格） ----
        self._add_section_title(layout, "/ 显示选项")
        switches = [
            ("显示BPM",     "show_bpm"),
            ("显示播放时间", "show_play_time"),
            ("显示曲目信息", "show_song_name"),
            ("显示MIDI作者", "show_song_author"),
            ("显示调音师",   "show_ust_author"),
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
            layout.addLayout(row)

        layout.addStretch()

        # ---- Play 按钮 ----
        self.play_btn = PrimaryPushButton("播放 Play")
        self.play_btn.setMinimumHeight(40)
        layout.addWidget(self.play_btn)

    def _add_section_title(self, parent: QVBoxLayout, text: str):
        lbl = StrongBodyLabel(text)
        lbl.setContentsMargins(0, 4, 0, 2)
        parent.addWidget(lbl)

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
        self.edit_project_name.setText(s.project_name)
        self.edit_song_name.setText(s.song_name)
        self.edit_song_author.setText(s.song_author)
        self.edit_ust_author.setText(s.ust_author)
        self.sw_show_bpm.setChecked(s.show_bpm)
        self.sw_show_play_time.setChecked(s.show_play_time)
        self.sw_show_song_name.setChecked(s.show_song_name)
        self.sw_show_song_author.setChecked(s.show_song_author)
        self.sw_show_ust_author.setChecked(s.show_ust_author)
        self.sw_show_copyright.setChecked(s.show_copyright)

        # UI → settings
        self.edit_project_name.textChanged.connect(lambda v: setattr(s, "project_name", v))
        self.edit_song_name.textChanged.connect(lambda v: setattr(s, "song_name", v))
        self.edit_song_author.textChanged.connect(lambda v: setattr(s, "song_author", v))
        self.edit_ust_author.textChanged.connect(lambda v: setattr(s, "ust_author", v))
        self.sw_show_bpm.checkedChanged.connect(lambda v: setattr(s, "show_bpm", v))
        self.sw_show_play_time.checkedChanged.connect(lambda v: setattr(s, "show_play_time", v))
        self.sw_show_song_name.checkedChanged.connect(lambda v: setattr(s, "show_song_name", v))
        self.sw_show_song_author.checkedChanged.connect(lambda v: setattr(s, "show_song_author", v))
        self.sw_show_ust_author.checkedChanged.connect(lambda v: setattr(s, "show_ust_author", v))
        self.sw_show_copyright.checkedChanged.connect(lambda v: setattr(s, "show_copyright", v))

        # 按钮
        self.import_btn.clicked.connect(self._on_import)
        self.export_btn.clicked.connect(self._on_export)
        self.play_btn.clicked.connect(self._on_play)

    # ===================== 业务逻辑 =====================

    def _on_import(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开工程文件", self._s.last_open_dir,
            "ustxPlayer工程文件 (*.uplr);;所有文件 (*.*)",
        )
        if not file_path:
            return
        try:
            self._s.import_uplr(file_path)
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
            os.path.join(self._s.last_export_dir, self._s.project_name or "未命名"),
            "ustxPlayer工程文件 (*.uplr);;所有文件 (*.*)",
        )
        if not file_path:
            return
        try:
            self._s.export_uplr(file_path)
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

    def _sync_ui_from_settings(self):
        s = self._s
        self.edit_project_name.setText(s.project_name)
        self.edit_song_name.setText(s.song_name)
        self.edit_song_author.setText(s.song_author)
        self.edit_ust_author.setText(s.ust_author)
        self.sw_show_bpm.setChecked(s.show_bpm)
        self.sw_show_play_time.setChecked(s.show_play_time)
        self.sw_show_song_name.setChecked(s.show_song_name)
        self.sw_show_song_author.setChecked(s.show_song_author)
        self.sw_show_ust_author.setChecked(s.show_ust_author)
        self.sw_show_copyright.setChecked(s.show_copyright)

    def sync_all_from_settings(self):
        self._sync_ui_from_settings()
