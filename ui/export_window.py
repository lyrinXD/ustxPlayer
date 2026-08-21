# export_window.py — 视频导出页面（覆盖主窗口内容区，隐藏导航栏）
"""导出参数 + 可播放预览 + 固定底部进度区的 Fluent 风格页面。"""

import os
import time
import threading

from PySide6.QtCore import Qt, QThread, QTimer, QEvent, Signal
from PySide6.QtGui import (
    QPixmap, QImage, QPainter, QColor, QGuiApplication, QIntValidator, QFontMetrics,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QLabel, QFrame,
    QSizePolicy,
)

from qfluentwidgets import (
    ComboBox, PushButton, PrimaryPushButton, SwitchButton, BodyLabel,
    InfoBar, InfoBarPosition,
    LineEdit, ToolButton, FluentIcon, ProgressBar, Slider,
    ScrollArea, CaptionLabel, themeColor, SmoothScrollArea, qconfig,
)
from qfluentwidgets.common.style_sheet import FluentStyleSheet

from qfluentwidgets.window.stacked_widget import StackedWidget

from core.log import logger
from core.renderer_core import RendererCore
from core.taskbar_progress import TaskbarProgress
from ui.accent_card import AccentHeaderCardWidget


# 编码设备显示名，以及“自动”括号里用的简称
_DEVICE_LABELS = {
    "nvenc": "NVIDIA NVENC",
    "qsv": "Intel Quick Sync (QSV)",
    "amf": "AMD AMF",
    "cpu": "CPU (libx264)",
}
_AUTO_DEVICE_LABELS = {
    "nvenc": "NVIDIA NVENC",
    "qsv": "Intel QSV",
    "amf": "AMD AMF",
    "cpu": "CPU",
}

# 自定义分辨率限制：宽高像素范围与长宽比范围（长/宽）
_CUSTOM_MIN_DIM = 360
_CUSTOM_MAX_DIM = 7680
_CUSTOM_MIN_RATIO = 0.5  # 1:2 竖屏
_CUSTOM_MAX_RATIO = 2.5  # 5:2 超宽

# 中部左右列最小总宽上限：默认窗口（900px）下内容区约 826px，留余量避免横向滚动条
_MIDDLE_MIN_WIDTH = 760


class _CircleInfoSymbol(QWidget):
    """自绘 ⓘ 信息符号：颜色实时读 themeColor()，主题切换经 update() 重绘。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        fm = QFontMetrics(self.font())
        self.setFixedSize(fm.height() + 4, fm.height() + 4)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        qconfig.themeChanged.connect(self.update)
        qconfig.themeColorChanged.connect(lambda _: self.update())

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)
        font = self.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(themeColor())
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "ⓘ")


class ExportPage(QWidget):
    """视频导出页面：覆盖主窗口内容区，隐藏导航栏，左上角返回按钮。"""

    export_busy_changed = Signal(bool)  # 导出开始/结束时通知主窗口冻结/恢复返回键
    _devices_ready = Signal(list, str, dict)  # 后台设备探测完成，跨线程投递到主线程

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._ustx_info = None
        self._preview_core = None
        self._preview_time = 0.0
        self._preview_total = 0.0
        self._playing = False
        self._seeking = False
        self._thread = None
        self._exporter = None
        self._exporting = False
        self._taskbar_progress = None
        self._last_preview_update = 0.0
        self._preview_refresh_interval = 1.5  # 导出中预览画面刷新间隔（秒）
        self._preview_image = None
        self._audio_dur = 0.0
        self._loading_params = False
        self._device_cache = None
        self._hw_info_cache = None
        self._device_probe_started = False
        self._device_values = ["auto"]
        self._preferred_device = "cpu"
        self._export_total = 0  # 本次导出总帧数，用于进度条按帧粒度平滑递增

        self._setup_ui()
        self._connect_signals()
        # 设备探测完成前冻结导出按钮，探测结果经 _apply_devices 启用
        self.btn_export.setEnabled(False)

    # ===================== UI 构建 =====================

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 可滚动内容区（返回按钮 / 输出路径 / 参数+预览）----
        # 命名避开 QWidget.scroll() 方法，否则 PyCharm 静态分析会把属性当绑定方法
        self.scroll_area = SmoothScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(SmoothScrollArea.Shape.NoFrame)
        self._content_widget = QWidget()
        self._content_widget.setObjectName("export_content")
        content = QVBoxLayout(self._content_widget)
        content.setContentsMargins(24, 12, 24, 12)
        content.setSpacing(10)

        # ---- 输出路径卡片 ----
        path_card = AccentHeaderCardWidget("输出路径")
        self.path_card = path_card
        path_vbox = QVBoxLayout()
        path_vbox.setSpacing(8)
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.edit_path = LineEdit()
        self.edit_path.setPlaceholderText("选择或输入输出文件路径 (*.mkv)")
        self.btn_browse = PushButton("浏览")
        path_row.addWidget(self.edit_path, 1)
        path_row.addWidget(self.btn_browse)
        path_vbox.addLayout(path_row)
        path_card.viewLayout.addLayout(path_vbox)
        content.addWidget(path_card)

        # ---- 中部：左参数列（5 份）+ 右预览列（9 份），预览约占总宽 64% ----
        # 用嵌套 layout 而非中间 QWidget，避免裁剪卡片阴影
        middle = QHBoxLayout()
        middle.setSpacing(8)
        left_col = QVBoxLayout()  # 左列：导出参数 + 运行环境
        left_col.setSpacing(10)

        # 导出参数卡片
        param_card = AccentHeaderCardWidget("导出参数")
        self.param_card = param_card
        param_vbox = QVBoxLayout()
        param_vbox.setSpacing(8)
        self.cmb_resolution = self._add_param_row(param_vbox, "分辨率")
        # 自定义分辨率行：选中“自定义”后显示，默认隐藏
        self.custom_row_widget = QWidget()
        custom_row = QHBoxLayout(self.custom_row_widget)
        custom_row.setContentsMargins(0, 0, 0, 0)
        custom_row.setSpacing(8)
        custom_row.addWidget(BodyLabel("自定义"))
        self.edit_custom_w = LineEdit()
        self.edit_custom_h = LineEdit()
        for edit in (self.edit_custom_w, self.edit_custom_h):
            edit.setValidator(QIntValidator(1, 99999, self))
            edit.setClearButtonEnabled(True)
        self.edit_custom_w.setPlaceholderText("长")
        self.edit_custom_h.setPlaceholderText("宽")
        custom_row.addWidget(self.edit_custom_w, 1)
        custom_row.addWidget(QLabel("×"))
        custom_row.addWidget(self.edit_custom_h, 1)
        param_vbox.addWidget(self.custom_row_widget)
        self.custom_row_widget.hide()
        self.cmb_fps = self._add_param_row(param_vbox, "帧率")
        self.cmb_device = self._add_param_row(param_vbox, "编码设备")
        row_audio = QHBoxLayout()
        row_audio.addWidget(BodyLabel("合并音频"))
        self.sw_audio = SwitchButton()
        row_audio.addWidget(self.sw_audio)
        row_audio.addStretch()
        param_vbox.addLayout(row_audio)
        # 播放时间由播放器实时叠加，导出画面不含
        tip_row = QHBoxLayout()
        tip_row.setSpacing(6)
        tip_row.addWidget(_CircleInfoSymbol())
        tip_row.addWidget(BodyLabel("播放时间不参与视频导出"))
        tip_row.addStretch()
        param_vbox.addLayout(tip_row)
        param_card.viewLayout.addLayout(param_vbox)
        left_col.addWidget(param_card)

        # 运行环境卡片
        env_card = AccentHeaderCardWidget("运行环境")
        self.env_card = env_card
        env_vbox = QVBoxLayout()
        env_vbox.setSpacing(2)
        self.hw_info_widget = QWidget()
        self.hw_info_box = QVBoxLayout(self.hw_info_widget)
        self.hw_info_box.setContentsMargins(0, 0, 0, 0)
        self.hw_info_box.setSpacing(2)
        self.hw_info_box.addWidget(CaptionLabel("检测中…"))
        env_vbox.addWidget(self.hw_info_widget)
        env_card.viewLayout.addLayout(env_vbox)
        left_col.addWidget(env_card)

        # 画面预览卡片
        preview_card = AccentHeaderCardWidget("画面预览")
        self.preview_card = preview_card
        preview_vbox = QVBoxLayout()
        preview_vbox.setSpacing(8)

        self.preview = ScrollArea()
        self.preview.setWidgetResizable(True)
        self.preview.setFrameShape(QFrame.Shape.NoFrame)
        self.preview.setStyleSheet(
            "QScrollArea { background: #101010; border: 1px solid #444444; "
            "border-radius: 4px; }"
            "QScrollArea > QWidget > QWidget { background: #101010; }"
        )
        self.preview_image = QLabel()
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWidget(self.preview_image)
        # 忽略 QScrollArea 的最小尺寸提示，宽度完全由 5:9 伸展比决定；
        # 高度由 resizeEvent 固定为 宽度×9/16，不随窗口高度拉伸
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        # 视口尺寸变化时重排画面
        self.preview.viewport().installEventFilter(self)
        preview_vbox.addWidget(self.preview)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)
        self.btn_play = ToolButton(FluentIcon.PLAY)
        self.btn_play.setFixedSize(32, 32)
        ctrl_row.addWidget(self.btn_play)
        self.slider_time = Slider(Qt.Orientation.Horizontal)
        self.slider_time.setRange(0, 1000)
        ctrl_row.addWidget(self.slider_time, 1)
        self.lbl_time = BodyLabel("0:00 / 0:00")
        ctrl_row.addWidget(self.lbl_time)
        hint = BodyLabel("点击或拖动时间条，或滚动滚轮查看任意帧")

        # 预览列与参数列一样顶对齐：标题 → 画面（固定 16:9）→ 控制条 → 提示
        preview_vbox.addLayout(ctrl_row)
        preview_vbox.addWidget(hint)
        preview_card.viewLayout.addLayout(preview_vbox)

        # 预览卡顶对齐不拉伸；左列底部 stretch 吸收余高
        left_col.addStretch(1)
        middle.addLayout(left_col, 5)
        middle.addWidget(preview_card, 9, Qt.AlignmentFlag.AlignTop)
        content.addLayout(middle)
        self._sync_ratio_minimums()

        self.scroll_area.setWidget(self._content_widget)
        # 内容区背景层：库 StackedWidget 作悬浮面板，四周内缩留云母区
        self.content_stack = StackedWidget(self)
        self.content_stack.addWidget(self.scroll_area)
        FluentStyleSheet.FLUENT_WINDOW.apply(self.content_stack)
        # 覆盖库样式：四周圆角 + 完整四边描边（沿用库的边框色）
        self.content_stack.setObjectName("export_content_stack")
        self.content_stack.setProperty(
            "lightCustomQss",
            "#export_content_stack { border: 1px solid rgba(0, 0, 0, 0.068); "
            "border-radius: 10px; }",
        )
        self.content_stack.setProperty(
            "darkCustomQss",
            "#export_content_stack { border: 1px solid rgba(0, 0, 0, 0.18); "
            "border-radius: 10px; }",
        )
        content_stack_wrap = QVBoxLayout()
        content_stack_wrap.setContentsMargins(12, 12, 12, 0)
        content_stack_wrap.addWidget(self.content_stack)
        root.addLayout(content_stack_wrap, 1)

        # ---- 固定底部区（不参与滚动）：与其他卡片同基础，无标题保持紧凑 ----
        self.bottom_card = AccentHeaderCardWidget(parent=self)
        bottom = self.bottom_card.viewLayout
        bottom.setContentsMargins(16, 10, 16, 12)
        bottom.setSpacing(6)

        # 第一行：工程信息（左）+ 导出按钮（右）
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        self.lbl_info = BodyLabel("")
        row1.addWidget(self.lbl_info)
        row1.addStretch()
        self.btn_export = PrimaryPushButton("开始导出")
        self.btn_export.setMinimumHeight(34)
        row1.addWidget(self.btn_export)
        bottom.addLayout(row1)

        # 第二行：进度文字独占一行（避免挤压进度条宽度）
        self.lbl_progress = BodyLabel("")
        self.lbl_progress.hide()
        bottom.addWidget(self.lbl_progress)

        # 第三行：进度条独占整行，总长度不受左侧文字影响
        self.progress_bar = ProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setUseAni(False)  # 导出中高频 setValue，动画堆积会卡死主线程
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setCustomBackgroundColor(
            QColor(0, 0, 0, 45), QColor(255, 255, 255, 50),
        )
        bottom.addWidget(self.progress_bar)
        card_wrap = QVBoxLayout()
        card_wrap.setContentsMargins(12, 12, 12, 12)
        card_wrap.addWidget(self.bottom_card)
        root.addLayout(card_wrap)

    def _sync_ratio_minimums(self):
        """预览列最小宽度与参数列按 5:9 成比例，压缩时两列同步触底，再小出滚动条。"""
        left_min = max(
            self.param_card.minimumSizeHint().width(),
            self.env_card.minimumSizeHint().width(),
        )
        self.preview_card.setMinimumWidth(min(round(left_min * 9 / 5), _MIDDLE_MIN_WIDTH - left_min))

    def _add_param_row(self, parent: QVBoxLayout, label: str) -> ComboBox:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(BodyLabel(label))
        cmb = ComboBox()
        # 显式最小宽覆盖文本驱动的 minimumSizeHint，否则长选项文本会把
        # 左列地板顶高，压缩时左列提前冻结、只剩预览列单边压缩
        cmb.setMinimumWidth(150)
        row.addWidget(cmb, 1)
        parent.addLayout(row)
        return cmb

    def _connect_signals(self):
        self.btn_browse.clicked.connect(self._on_browse)
        self.btn_export.clicked.connect(self._on_export_clicked)
        self.btn_play.clicked.connect(self._toggle_play)
        self.slider_time.valueChanged.connect(self._on_slider_changed)
        self._devices_ready.connect(self._apply_devices)
        self.sw_audio.checkedChanged.connect(self._on_param_changed)
        self.cmb_resolution.currentIndexChanged.connect(self._on_resolution_changed)
        self.edit_custom_w.editingFinished.connect(self._on_custom_editing_finished)
        self.edit_custom_h.editingFinished.connect(self._on_custom_editing_finished)
        self.cmb_fps.currentIndexChanged.connect(self._on_param_changed)

        self._play_timer = QTimer(self)
        self._play_timer.setInterval(100)
        self._play_timer.timeout.connect(self._on_play_tick)

    # ===================== 数据刷新 =====================

    def refresh(self, ustx_info: dict):
        """进入页面时用最新工程数据重建渲染核心与参数。

        每次点击"导出视频"都会走到这里：除硬件探测缓存（_device_cache/_device_probe_started）外
        全量重置，避免切换工程后残留上一工程的预览画面/进度/播放状态。
        """
        from core.video_exporter import RESOLUTION_PRESETS, FPS_OPTIONS, probe_audio_duration
        self._stop_preview_play()
        self._ustx_info = ustx_info
        self._preview_core = None
        self._preview_image = None
        self._preview_time = 0.0
        self._preview_total = 0.0
        self._last_preview_update = 0.0
        self.preview_image.clear()
        if self._taskbar_progress is not None:
            self._taskbar_progress.clear()
            self._taskbar_progress = None
        self.progress_bar.setValue(0)
        self.lbl_progress.setText("")
        self.lbl_progress.hide()

        self._loading_params = True
        self.cmb_resolution.blockSignals(True)
        self.cmb_fps.blockSignals(True)
        try:
            self.cmb_resolution.clear()
            self.cmb_fps.clear()
            # 第一项固定为当前分辨率，预设去重后按 720p→1080p→4K 排列，末尾是自定义
            self._screen_w, self._screen_h = self._current_screen_resolution()
            self.cmb_resolution.addItem(f"当前分辨率（{self._screen_w}×{self._screen_h}）")
            for label, size in RESOLUTION_PRESETS.items():
                if size != (self._screen_w, self._screen_h):
                    self.cmb_resolution.addItem(label)
            self.cmb_resolution.addItem("自定义")
            self.cmb_resolution.setCurrentIndex(0)
            self.edit_custom_w.setText(str(self._screen_w))
            self.edit_custom_h.setText(str(self._screen_h))
            self.custom_row_widget.hide()
            self.cmb_fps.addItems([str(f) for f in FPS_OPTIONS])
            self.cmb_fps.setCurrentIndex(0)
        finally:
            self.cmb_resolution.blockSignals(False)
            self.cmb_fps.blockSignals(False)
            self._loading_params = False

        self._device_values = ["auto"]
        self._preferred_device = "cpu"
        self.cmb_device.blockSignals(True)
        self.cmb_device.clear()
        if self._device_cache is None:
            # 设备列表未就绪：先用占位项，后台探测完成后自动填充
            self._start_device_probe()
            self.cmb_device.addItem("自动（检测中…）")
        else:
            devices, preferred = self._device_cache
            self._populate_device_combo(devices, preferred)
        self.cmb_device.setCurrentIndex(0)
        self.cmb_device.blockSignals(False)
        if self._hw_info_cache is not None:
            self._render_hw_info(self._hw_info_cache)

        audio = self._settings.project.audio_path
        self._has_audio = bool(audio) and os.path.isfile(audio)
        # 先探测再 setChecked，避免 toggled 触发刷新时读到旧时长
        self._audio_dur = probe_audio_duration(audio) if self._has_audio else 0.0
        self.sw_audio.setChecked(self._has_audio)
        self.sw_audio.setEnabled(self._has_audio)

        export_dir = self._settings.last_export_dir
        if not export_dir or not os.path.isdir(export_dir):
            export_dir = os.path.join(os.path.expanduser("~"), "Desktop")
        name = self._settings.project.project_name or "未命名"
        self.edit_path.setText(os.path.join(export_dir, f"{name}.mkv"))

        self._refresh_preview()
        self._refresh_info()
        self._sync_ratio_minimums()
        for card in (self.path_card, self.param_card, self.env_card,
                     self.preview_card, self.bottom_card):
            card.refresh_shadow()

    # ===================== 编码设备（后台探测） =====================

    def _start_device_probe(self):
        """后台线程枚举编码设备，避免进入导出页时启动 ffmpeg 卡住界面。"""
        if self._device_probe_started:
            return
        self._device_probe_started = True
        threading.Thread(target=self._probe_devices_worker, daemon=True).start()

    def _probe_devices_worker(self):
        from core.video_exporter import probe_hardware_info
        try:
            info = probe_hardware_info()
            devices, preferred = info["devices"], info["preferred"]
        except Exception:
            logger.exception("编码设备枚举失败")
            devices, preferred, info = [], "cpu", {}
        self._devices_ready.emit(devices, preferred, info)

    def _apply_devices(self, devices, preferred, info):
        """应用后台探测结果；刷新期间到达则留待下次刷新使用。"""
        self._device_cache = (devices, preferred)
        self._hw_info_cache = info
        self.btn_export.setEnabled(True)
        if self._loading_params:
            return
        self.cmb_device.blockSignals(True)
        try:
            self._populate_device_combo(devices, preferred)
        finally:
            self.cmb_device.blockSignals(False)
        self.param_card.refresh_shadow()
        self._render_hw_info(info)

    def _populate_device_combo(self, devices, preferred):
        """把设备列表写入下拉框，并维护"自动"首选设备与选中索引。"""
        self._device_values = ["auto"] + devices
        self._preferred_device = preferred
        self.cmb_device.clear()
        self.cmb_device.addItem(
            f"自动（{_AUTO_DEVICE_LABELS.get(preferred, preferred)}）"
        )
        for dev in devices:
            self.cmb_device.addItem(_DEVICE_LABELS.get(dev, dev))
        self.cmb_device.setCurrentIndex(0)

    def _render_hw_info(self, info: dict):
        """数据驱动渲染运行环境；值得注意的根因行用强调色。

        显卡每行一条只列名称；编码器规则：有对应显卡且可用则不显示，
        无对应显卡导致不可用则正常写出“不可用”，有对应显卡但编码器
        不可用时强调显示；整机无显卡时写“编码器不可用”；ffmpeg 缺失强调显示。
        """
        while self.hw_info_box.count():
            item = self.hw_info_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        accent = themeColor()
        rows = []

        if not info:
            rows.append(("运行环境读取失败", True))
        else:
            gpus = info.get("gpus") or []
            if not gpus:
                rows.append(("显卡：无法读取显卡信息", True))
            else:
                for g in gpus:
                    name = g.get("name") or "未知显卡"
                    rows.append((f"显卡：{name}", False))
            encoders = info.get("encoders") or {}
            vendor_ok = info.get("vendor_ok") or {}
            available = set(info.get("devices") or [])
            if not gpus:
                rows.append(("编码器不可用（仅 CPU 软件编码）", False))
            else:
                for enc in ("nvenc", "qsv", "amf"):
                    if enc in available:
                        continue  # 有对应显卡且可用：不显示
                    if vendor_ok.get(enc):
                        # 有对应厂商显卡但编码器不可用：强调
                        rows.append((f"{_DEVICE_LABELS[enc]}：不可用（ffmpeg 未编译）", True))
                    else:
                        # 无对应显卡导致不可用：正常写出来
                        rows.append((f"{_DEVICE_LABELS[enc]}：不可用（无对应显卡）", False))
            ffmpeg = info.get("ffmpeg")
            if ffmpeg:
                version = ffmpeg.get("version")
                if version:
                    rows.append((f"ffmpeg：{version}", False))
                else:
                    rows.append(("ffmpeg：可用", False))
            else:
                rows.append(("ffmpeg：未找到（无法导出）", True))

        for text, warn in rows:
            lbl = CaptionLabel(text)
            lbl.setWordWrap(True)
            if warn:
                lbl.setTextColor(accent, accent)
            self.hw_info_box.addWidget(lbl)
        self.env_card.refresh_shadow()
        self._sync_ratio_minimums()

    # ===================== 预览 =====================

    def _refresh_preview(self):
        if self._ustx_info is None:
            return
        resolution = self._selected_resolution()
        if resolution is None:
            return
        w, h = resolution
        try:
            if self._preview_core is None:
                self._preview_core = RendererCore(self._ustx_info, w, h)
            else:
                self._preview_core.set_resolution(w, h)
            ustx_dur = self._preview_core.duration_seconds
            # 预览进度上限 = max(USTX 内容时长, 有效音频时长)，与导出总时长一致；
            # 有效音频时长受"合并音频"开关控制（关闭时导出也不带音频尾）
            self._preview_total = max(ustx_dur, self._effective_audio_dur())
            self._preview_time = min(self._preview_time, self._preview_total)
            logger.info(
                f"预览时长 — USTX={ustx_dur:.2f}s, 音频={self._audio_dur:.2f}s, "
                f"合并音频={self.sw_audio.isChecked()}, 上限={self._preview_total:.2f}s"
            )
            self._render_preview_frame()
            self._update_slider()
        except Exception:
            logger.exception("预览渲染失败")

    def _render_preview_frame(self):
        if self._preview_core is None:
            return
        w, h = self._preview_core.w, self._preview_core.h
        self._preview_core.set_time(self._preview_time)
        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        p = QPainter(img)
        try:
            self._preview_core.paint(p, w, h, 1.0)
        finally:
            p.end()
        self._preview_image = img
        self._update_preview_pixmap()

    def _update_preview_pixmap(self):
        """把当前帧完整等比缩放到视口内（居中，四周露黑边）。

        16:9 由 _fit_preview_size 固定 ScrollArea 高度保证；这里只保证
        画面 ≤ 视口，因此完整可见、绝无滚动条。
        """
        if self._preview_image is None:
            return
        vp = self.preview.viewport().size()
        if vp.width() <= 0 or vp.height() <= 0:
            return
        scaled = self._preview_image.scaled(
            vp, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_image.setPixmap(QPixmap.fromImage(scaled))
        self.preview_card.refresh_shadow()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 等布局完成后按当前宽度固定预览高度为 16:9
        QTimer.singleShot(0, self._fit_preview_size)

    def _fit_preview_size(self):
        if getattr(self, "preview", None) is None:
            return
        w = self.preview.width()
        if w > 0:
            self.preview.setFixedHeight(max(180, int(w * 9 / 16)))
        self._update_preview_pixmap()

    def _update_slider(self):
        self._seeking = True
        try:
            total = self._preview_total if self._preview_total > 0 else 1.0
            self.slider_time.setValue(int(min(1.0, self._preview_time / total) * 1000))
            self._update_time_label()
        finally:
            self._seeking = False

    def _update_time_label(self):
        def fmt(s):
            m = int(s) // 60
            sec = int(s) % 60
            return f"{m}:{sec:02d}"
        self.lbl_time.setText(f"{fmt(self._preview_time)} / {fmt(self._preview_total)}")

    def _toggle_play(self):
        if self._playing:
            self._stop_preview_play()
        else:
            if self._preview_time >= self._preview_total and self._preview_total > 0:
                self._preview_time = 0.0
            self._playing = True
            self.btn_play.setIcon(FluentIcon.PAUSE)
            self._play_timer.start()

    def _stop_preview_play(self):
        self._playing = False
        self._play_timer.stop()
        self.btn_play.setIcon(FluentIcon.PLAY)

    def _on_play_tick(self):
        if self._preview_core is None or self._exporting:
            return
        self._preview_time += 0.1
        if self._preview_total > 0 and self._preview_time >= self._preview_total:
            self._preview_time = self._preview_total
            self._stop_preview_play()
        self._render_preview_frame()
        self._update_slider()

    def _on_slider_changed(self, value: int):
        if self._seeking or self._preview_total <= 0:
            return
        self._preview_time = value / 1000.0 * self._preview_total
        self._render_preview_frame()
        self._update_time_label()

    def eventFilter(self, obj, event):
        """视口尺寸变化时重排画面。"""
        if obj is self.preview.viewport():
            if event.type() == QEvent.Type.Resize:
                self._update_preview_pixmap()
        return super().eventFilter(obj, event)

    def _on_param_changed(self):
        if self._loading_params or self._ustx_info is None:
            return
        self._refresh_preview()
        self._refresh_info()

    def _on_resolution_changed(self):
        is_custom = self.cmb_resolution.currentText() == "自定义"
        self.custom_row_widget.setVisible(is_custom)
        if is_custom and self._custom_resolution() is None:
            self.edit_custom_w.blockSignals(True)
            self.edit_custom_h.blockSignals(True)
            self.edit_custom_w.setText(str(self._screen_w))
            self.edit_custom_h.setText(str(self._screen_h))
            self.edit_custom_w.blockSignals(False)
            self.edit_custom_h.blockSignals(False)
        self._sync_ratio_minimums()
        self._on_param_changed()

    def _on_custom_editing_finished(self):
        """自定义分辨率失焦/回车时校验：非法立即报错并打回当前分辨率。"""
        if self._loading_params or self._ustx_info is None:
            return
        if self._custom_resolution() is None:
            InfoBar.error(
                "ERcode207", self._custom_resolution_error(),
                orient=Qt.Orientation.Vertical, duration=4000,
                parent=self.window(), position=InfoBarPosition.TOP_RIGHT,
            )
            self._reset_custom_resolution()
        self._on_param_changed()

    def _reset_custom_resolution(self):
        """把自定义分辨率输入打回当前屏幕分辨率。"""
        self.edit_custom_w.setText(str(self._screen_w))
        self.edit_custom_h.setText(str(self._screen_h))

    @staticmethod
    def _current_screen_resolution():
        """读取主屏幕物理分辨率，读取失败时退回 1080p。"""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return 1920, 1080
        size = screen.size()
        dpr = screen.devicePixelRatio()
        return int(round(size.width() * dpr)), int(round(size.height() * dpr))

    # ===================== 信息与设备 =====================

    def _selected_resolution(self):
        """返回当前选中的 (宽, 高)；自定义输入非法时返回 None。"""
        from core.video_exporter import RESOLUTION_PRESETS
        text = self.cmb_resolution.currentText()
        if text == "自定义":
            return self._custom_resolution()
        if text.startswith("当前分辨率"):
            return self._screen_w, self._screen_h
        return RESOLUTION_PRESETS.get(text)

    def _custom_resolution(self):
        """解析自定义分辨率输入，非法时返回 None。"""
        try:
            w = int(self.edit_custom_w.text().strip())
            h = int(self.edit_custom_h.text().strip())
        except ValueError:
            return None
        if not self._valid_custom_resolution(w, h):
            return None
        return w, h

    @staticmethod
    def _valid_custom_resolution(w: int, h: int) -> bool:
        return (
            w % 2 == 0
            and h % 2 == 0
            and _CUSTOM_MIN_DIM <= w <= _CUSTOM_MAX_DIM
            and _CUSTOM_MIN_DIM <= h <= _CUSTOM_MAX_DIM
            and _CUSTOM_MIN_RATIO <= w / h <= _CUSTOM_MAX_RATIO
        )

    @staticmethod
    def _custom_resolution_error() -> str:
        return (
            f"自定义分辨率无效：宽高需为 {_CUSTOM_MIN_DIM}–{_CUSTOM_MAX_DIM} 的偶数整数，"
            "且长宽比需在 1:2 到 5:2 之间"
        )

    def _selected_device(self):
        idx = self.cmb_device.currentIndex()
        if 0 <= idx < len(self._device_values):
            dev = self._device_values[idx]
            if dev == "auto":
                return self._preferred_device or "cpu"
            return dev
        return "cpu"

    def _refresh_info(self):
        from core.video_exporter import compute_total_duration
        fps = int(self.cmb_fps.currentText())
        total = compute_total_duration(
            self._ustx_info, self._effective_audio_dur()
        ) if self._ustx_info else 0.0
        total_frames = int(total * fps)
        project = self._settings.project.project_name or "未命名"
        self.lbl_info.setText(f"{project} · 时长 {total:.1f}s · 总帧数 {total_frames}")

    def _effective_audio_dur(self) -> float:
        """实际参与导出的音频时长：合并音频关闭时音频不参与，时长归零。"""
        return self._audio_dur if (self.sw_audio.isChecked() and self._has_audio) else 0.0

    # ===================== 导出流程 =====================

    @staticmethod
    def _unique_path(path: str) -> str:
        """同名文件自动加编号：file.mkv → file (1).mkv，避免覆盖。"""
        if not os.path.exists(path):
            return path
        stem, ext = os.path.splitext(path)
        i = 1
        while os.path.exists(f"{stem} ({i}){ext}"):
            i += 1
        return f"{stem} ({i}){ext}"

    def _on_browse(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "选择导出位置",
            self.edit_path.text(),
            "Matroska 视频 (*.mkv);;所有文件 (*.*)",
        )
        if path:
            if not path.lower().endswith(".mkv"):
                path += ".mkv"
            self.edit_path.setText(self._unique_path(path))

    def _on_export_clicked(self):
        if self._exporting:
            self._cancel_export()
            return
        self._start_export()

    def _freeze_controls(self):
        """导出开始：除终止键外全部冻结，预览停播并显示准备进度。"""
        self.btn_export.setText("终止导出")
        for w in (
            self.cmb_resolution, self.cmb_fps, self.cmb_device, self.sw_audio,
            self.custom_row_widget, self.btn_play, self.slider_time,
            self.edit_path, self.btn_browse,
        ):
            w.setEnabled(False)
        self._stop_preview_play()
        self._export_total = 0  # 让首次进度信号重新 setRange(0,total)
        self.progress_bar.setRange(0, 100)  # 导出前恢复为占位 0-100，等待首次进度重置
        self.progress_bar.setValue(0)
        self.lbl_progress.setText("正在准备导出…")
        self.lbl_progress.show()

    def _restore_controls(self):
        """导出结束：恢复全部控件并刷新预览。"""
        self.btn_export.setEnabled(True)
        self.btn_export.setText("开始导出")
        for w in (
            self.cmb_resolution, self.cmb_fps, self.cmb_device,
            self.custom_row_widget, self.edit_path, self.btn_browse,
        ):
            w.setEnabled(True)
        self.btn_play.setEnabled(True)
        self.slider_time.setEnabled(True)
        self.sw_audio.setEnabled(self._has_audio)
        self._refresh_preview()

    def _start_export(self):
        out_path = self.edit_path.text().strip()
        if not out_path:
            InfoBar.error(
                "ERcode202", "请先选择输出路径", orient=Qt.Orientation.Vertical,
                duration=3000, parent=self.window(), position=InfoBarPosition.TOP_RIGHT,
            )
            return
        if not out_path.lower().endswith(".mkv"):
            out_path += ".mkv"
        out_path = self._unique_path(out_path)
        self.edit_path.setText(out_path)

        resolution = self._selected_resolution()
        if resolution is None:
            self._reset_custom_resolution()
            InfoBar.error(
                "ERcode207", self._custom_resolution_error(),
                orient=Qt.Orientation.Vertical, duration=4000,
                parent=self.window(), position=InfoBarPosition.TOP_RIGHT,
            )
            self._refresh_preview()
            return
        w, h = resolution
        fps = int(self.cmb_fps.currentText())
        if self._device_cache is None:
            # 兜底（正常被冻结的导出按钮挡住）：交给导出线程单飞行复用同一探测结果
            device = "auto"
        else:
            device = self._selected_device()
        merge_audio = self.sw_audio.isChecked() and self._has_audio
        audio_path = self._settings.project.audio_path if merge_audio else ""

        audio_dur = self._effective_audio_dur()
        logger.info(
            f"导出参数 — {w}×{h}@{fps}fps, 设备={device}, 合并音频={merge_audio}, "
            f"音频时长={audio_dur:.2f}s"
        )

        # 记住导出目录（与 UPRJ 保存共用 last_export_dir，写入 Settings.json）
        export_dir = os.path.dirname(out_path)
        if export_dir != self._settings.last_export_dir:
            self._settings.last_export_dir = export_dir
            self._settings.write_settings()

        self._exporting = True
        self.export_busy_changed.emit(True)
        self._freeze_controls()
        # 导出期间关闭预览/底部卡阴影，避免滑块等高频子控件更新触发整卡离屏渲染+模糊
        # 与 NVENC 抢资源；结束时 _on_thread_finished 恢复。
        self._set_shadow_enabled(False)

        # 任务栏进度：准备阶段先转圈，帧进度到达后进入正常进度
        self._taskbar_progress = TaskbarProgress(self.window().winId())
        self._taskbar_progress.set_progress(None)

        from core.video_exporter import VideoExporter
        self._thread = QThread(self)
        self._exporter = VideoExporter()
        self._exporter.moveToThread(self._thread)
        self._exporter.set_export_args(
            self._ustx_info, out_path, w, h, fps, device,
            audio_path, audio_dur, False,
        )
        self._thread.started.connect(self._exporter.run_pending)
        self._exporter.progress.connect(self._on_progress)
        self._exporter.finished_ok.connect(self._on_finished)
        self._exporter.failed.connect(self._on_failed)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _cancel_export(self):
        if self._exporter:
            self._exporter.cancel()
        self.btn_export.setEnabled(False)
        self.btn_export.setText("正在终止…")

    def _on_progress(self, done: int, total: int, elapsed: float):
        # 进度条按帧设 range(0, total)：每帧信号都在位移，比固定 0-100 整除百分比
        # 平滑很多（长导出下 1% 要等很久，bar 会长时间停滞再跳一格）。
        # 保持关闭动画（setUseAni(False)），避免高频 setValue 的自带动画堆积卡死主线程。
        if total > 0 and total != self._export_total:
            self._export_total = total
            self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        percent = done / total if total else 0
        if self._taskbar_progress is not None:
            self._taskbar_progress.set_progress(percent)
        fps_now = done / elapsed if elapsed > 0 else 0
        remain = (total - done) / fps_now if fps_now > 0 else 0
        self.lbl_progress.setText(
            f"已完成 {done}/{total} 帧 · 剩余约 {remain:.0f} 秒 · 编码中"
        )
        # 预览跟随：滑块/时间标签随进度平滑推进（10Hz），画面按节流间隔刷新。
        # 导出期间卡片阴影已临时关闭（_set_shadow_enabled(False)）：否则阴影会让
        # 滑块/标签这类高频子控件更新触发整卡离屏渲染+模糊，与 NVENC 抢资源拖慢编码。
        if self._preview_core is not None:
            try:
                t = (done - 1) / int(self.cmb_fps.currentText())
                self._preview_core.set_time(t)
                self._preview_time = t
                self._update_slider()
                now = time.monotonic()
                if now - self._last_preview_update >= self._preview_refresh_interval:
                    self._last_preview_update = now
                    self._render_preview_frame()
            except Exception:
                pass

    def _on_finished(self, out_path: str):
        # 进度条 range 已按本帧 total 设置，直接填满到 maximum
        self.progress_bar.setValue(self.progress_bar.maximum())
        if self._taskbar_progress is not None:
            self._taskbar_progress.set_progress(1.0)
        self.lbl_progress.setText("导出完成")
        InfoBar.success(
            "导出完成", f"视频已导出到：{out_path}", orient=Qt.Orientation.Vertical,
            duration=4000, parent=self.window(), position=InfoBarPosition.TOP_RIGHT,
        )

    def _on_failed(self, message: str):
        if self._taskbar_progress is not None:
            self._taskbar_progress.clear()
        if message.startswith("导出已取消"):
            # 进度卡片只显示状态，错误/取消正文一律走顶部 InfoBar
            self.lbl_progress.setText("导出已取消")
            InfoBar.info(
                "导出已取消", "已停止导出并清理未完成的视频文件",
                orient=Qt.Orientation.Vertical, duration=3000,
                parent=self.window(), position=InfoBarPosition.TOP_RIGHT,
            )
        else:
            self.lbl_progress.setText("导出失败")
            InfoBar.error(
                "ERcode203", message, orient=Qt.Orientation.Vertical,
                duration=5000, parent=self.window(), position=InfoBarPosition.TOP_RIGHT,
            )

    def _on_thread_finished(self):
        self._exporting = False
        self.export_busy_changed.emit(False)
        if self._taskbar_progress is not None:
            self._taskbar_progress.clear()
        self._restore_controls()
        # 导出结束恢复卡片阴影（_start_export 中 _set_shadow_enabled(False) 临时关闭）
        self._restore_shadow()

    def _set_shadow_enabled(self, enabled: bool):
        """开关导出页高频更新卡的阴影特效。

        阴影会让子控件更新触发整卡离屏渲染+高斯模糊，导出期间滑块/进度条/标签
        以 10Hz 更新时会造成持续 GPU 负载、拖慢 NVENC 编码，故导出时临时关闭。
        """
        for card in (self.preview_card, self.bottom_card):
            card.set_shadow_enabled(enabled)

    def _restore_shadow(self):
        """导出结束恢复阴影到全局状态（用户全局关闭的卡片保持关闭）。"""
        for card in (self.preview_card, self.bottom_card):
            card.restore_global_shadow()

    def closeEvent(self, event):
        if self._exporting:
            if self._exporter:
                self._exporter.cancel()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
        super().closeEvent(event)
