# main.py — ustxPlayer 主入口
"""提供侧边导航的现代化界面。"""

import os
import sys
import winreg

from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QIcon, QColor, QGuiApplication

from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon,
    InfoBar, InfoBarPosition, MessageBox, setTheme, Theme, setThemeColor,
)

from core.log import logger
from core.settings_manager import SettingsManager, ProjectFileMissingError
from core.ustxplayer import display, detect_lrc_max_languages
import core.ustxreader as ur

from ui.basic_page import BasicPage
from ui.file_page import FilePage
from ui.player_style_page import PlayerStylePage
from ui.lyric_edit_page import LyricEditPage
from ui.other_page import OtherPage


class MainWindow(FluentWindow):
    """主窗口 — 侧边导航 + 堆叠页面。"""

    def __init__(self):
        super().__init__()
        self._settings = SettingsManager(self)
        self._player_window = None
        self.setWindowTitle("ustxPlayer")
        self.resize(900, 620)
        self.setMinimumSize(640, 480)

        # 主题必须在 _build_pages 之前设置
        self._setup_theme()
        self._setup_accent_color()

        icon_path = os.path.join(self._settings.program_root, "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._build_pages()
        self._init_navigation()
        self.basic_page.set_play_callback(self._on_play)

        # 启用拖拽
        self.setAcceptDrops(True)

        # 修复全屏时侧边栏展开导致显示不全的问题
        self.navigationInterface.setExpandWidth(220)

        # 启动后同步所有页面
        QTimer.singleShot(0, self._sync_all_pages)
        QTimer.singleShot(100, self._load_dropped_uplr)

    # ===================== 主题管理 =====================

    def _setup_theme(self):
        """初始化主题：应用保存的设置，并连接系统/用户主题变化信号。"""
        self._apply_theme()

        app = QApplication.instance()
        # isinstance 收窄到 QGuiApplication 才能访问 styleHints()
        if isinstance(app, QGuiApplication):
            app.styleHints().colorSchemeChanged.connect(
                self._on_system_theme_changed
            )

        self._settings.theme_mode_changed.connect(
            self._on_theme_mode_changed
        )

    def _apply_theme(self):
        """根据 theme_mode 设置 qfluentwidgets 主题（亮/暗/自动）。"""
        mode = self._settings.theme_mode
        if mode == "auto":
            setTheme(Theme.AUTO)
        elif mode == "light":
            setTheme(Theme.LIGHT)
        elif mode == "dark":
            setTheme(Theme.DARK)
        logger.info(f"主题已应用: {mode}")
        self._refresh_theme()

    def _refresh_theme(self):
        """切换主题后更新页面背景色。"""
        self._apply_area_background()

    def _on_system_theme_changed(self):
        """系统主题变化 — 仅在'跟随系统'模式下刷新。"""
        if self._settings.theme_mode == "auto":
            setTheme(Theme.AUTO)
            self._refresh_theme()
            logger.info("系统主题已变化，自动刷新主题")

    def _on_theme_mode_changed(self, mode: str):
        """用户手动切换主题 → 应用并持久化。"""
        logger.info(f"用户切换主题模式: {mode}")
        self._apply_theme()
        self._settings.write_settings()

    # ===================== 强调色管理 =====================

    def _setup_accent_color(self):
        """初始化强调色：从注册表读取 Windows 强调色或使用自定义颜色。"""
        self._last_windows_accent = None
        self._apply_accent_color()

        self._settings.accent_color_mode_changed.connect(
            self._on_accent_color_mode_changed
        )
        self._settings.custom_accent_color_changed.connect(
            self._on_custom_accent_color_changed
        )

    @staticmethod
    def _get_windows_accent_color() -> str | None:
        """从注册表读取 Windows 强调色，返回 hex 字符串如 '#0078d7'。"""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\DWM",
                0, winreg.KEY_READ,
            )
            value, _ = winreg.QueryValueEx(key, "AccentColor")
            winreg.CloseKey(key)
            r = value & 0xFF
            g = (value >> 8) & 0xFF
            b = (value >> 16) & 0xFF
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return None

    def _apply_accent_color(self):
        """根据 accent_color_mode 应用强调色。"""
        if self._settings.accent_color_mode == "auto":
            color = self._get_windows_accent_color()
            if color:
                self._last_windows_accent = color
                setThemeColor(QColor(color))
                logger.info(f"强调色已应用(系统): {color}")
            elif self._last_windows_accent:
                setThemeColor(QColor(self._last_windows_accent))
            else:
                setThemeColor(QColor(self._settings.custom_accent_color))
                logger.info("无法获取系统强调色，使用默认值")
        else:
            setThemeColor(QColor(self._settings.custom_accent_color))
            logger.info(f"强调色已应用(自定义): {self._settings.custom_accent_color}")

    def _on_accent_color_mode_changed(self, mode: str):
        """用户切换强调色模式 → 重新应用并持久化。"""
        logger.info(f"强调色模式切换: {mode}")
        self._apply_accent_color()
        self._settings.write_settings()

    def _on_custom_accent_color_changed(self, color: str):
        """用户更改自定义强调色 → 仅在 custom 模式下生效并持久化。"""
        if self._settings.accent_color_mode == "custom":
            setThemeColor(QColor(color))
            logger.info(f"自定义强调色已更新: {color}")
        self._settings.write_settings()

    # ===================== 页面构建 =====================

    def _build_pages(self):
        self.basic_page = BasicPage(self._settings)
        self.file_page = FilePage(self._settings)
        self.player_style_page = PlayerStylePage(self._settings)
        self.lyric_edit_page = LyricEditPage(self._settings)
        self.other_page = OtherPage(self._settings)

        # 以下 scroll_* 属性在循环中通过 setattr 动态创建，此处显式声明类型供静态分析识别
        self.scroll_basic_page: QScrollArea
        self.scroll_file_page: QScrollArea
        self.scroll_player_style_page: QScrollArea
        self.scroll_lyric_edit_page: QScrollArea
        self.scroll_other_page: QScrollArea

        # 用 QScrollArea 包裹防止窗口缩小时重叠
        for name in ("basic_page", "file_page", "player_style_page",
                     "lyric_edit_page", "other_page"):
            page = getattr(self, name)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setObjectName(f"scroll_{name}")
            setattr(self, f"scroll_{name}", scroll)

        self._apply_area_background()

    def _apply_area_background(self):
        """根据当前主题设置页面背景色，解决暗色模式泛白问题。"""
        from qfluentwidgets import qconfig
        is_dark = qconfig.theme == Theme.DARK
        bg = "#1a1a1a" if is_dark else "#f5f5f5"
        for name in ("basic_page", "file_page", "player_style_page",
                     "lyric_edit_page", "other_page"):
            scroll = getattr(self, f"scroll_{name}", None)
            if scroll:
                scroll.setStyleSheet(
                    f"QScrollArea {{ background: {bg}; }}"
                    f"QScrollArea > QWidget > QWidget {{ background: {bg}; }}"
                    f"QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}"
                    f"QScrollBar::handle:vertical {{ background: #88888880; border-radius: 4px; min-height: 20px; }}"
                    f"QScrollBar::handle:vertical:hover {{ background: #aaaaaa80; }}"
                    f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
                    f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}"
                )

    def _init_navigation(self):
        self.addSubInterface(
            self.scroll_basic_page, FluentIcon.HOME, "基础",
            position=NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.scroll_file_page, FluentIcon.DOCUMENT, "文件",
            position=NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.scroll_player_style_page, FluentIcon.PALETTE, "播放器",
            position=NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.scroll_lyric_edit_page, FluentIcon.EDIT, "歌词编辑",
            position=NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.scroll_other_page, FluentIcon.MORE, "其他",
            position=NavigationItemPosition.BOTTOM,
        )

    # ===================== 播放逻辑 =====================

    def _on_play(self):
        ustx_path = self._settings.ustx_path.strip()
        logger.info(f"Play 按钮点击，USTX路径: {ustx_path}")

        if not ustx_path or not os.path.exists(ustx_path):
            logger.warning(f"文件无效: {ustx_path}")
            InfoBar.error(
                "ERcode001", "请选择有效的USTX文件！",
                orient=Qt.Orientation.Vertical, duration=3000, parent=self, position=InfoBarPosition.TOP_RIGHT,
            )
            return

        try:
            # 优先复用解析缓存（path 一致时），否则同步解析并刷新缓存
            cached = self._settings.cached_ust_info
            if cached and cached.get("path") == ustx_path and cached.get("info"):
                core_ust_info = cached["info"]
                logger.info("复用 file_page 解析缓存")
            else:
                core_ust_info = ur.get_ustx_info(ustx_path)
                self._settings.cached_ust_info = {"path": ustx_path, "info": core_ust_info}
            # get_ustx_info 返回联合类型，用 isinstance 收窄到 list 后再取 len
            _notes = core_ust_info.get('notes', [])
            logger.info(
                f"解析完成 - 版本={core_ust_info.get('version')}, "
                f"BPM={core_ust_info.get('tempo')}, "
                f"音符数={len(_notes) if isinstance(_notes, list) else 0}"
            )

            ust_info = self._settings.build_ust_info(core_ust_info)

            msg = MessageBox("启动播放器",
                             "按下确认后将启动播放器，鼠标单击后按ESC键退出全屏", self)
            if msg.exec():
                self._launch_player(ust_info)

        except Exception as e:
            logger.exception("播放准备失败")
            InfoBar.error(
                "ERcode008", f"播放准备失败：{e}",
                orient=Qt.Orientation.Vertical, duration=3000, parent=self, position=InfoBarPosition.TOP_RIGHT,
            )

    def _sync_all_pages(self):
        """同步所有页面数据。"""
        for page in [self.basic_page, self.file_page, self.player_style_page,
                     self.lyric_edit_page, self.other_page]:
            if hasattr(page, "sync_all_from_settings"):
                page.sync_all_from_settings()

    def _launch_player(self, ust_info: dict):
        """启动播放器并保持引用。如有旧窗口则先关闭。"""
        # 关闭旧播放器窗口
        if self._player_window is not None and self._player_window.isVisible():
            logger.info("关闭旧播放器窗口")
            self._player_window.close()
            self._player_window = None

        sc = ust_info["show_config"]
        logger.info(
            f"正在启动播放器 — curve_show={sc['curve_show']}, "
            f"bpm={sc['bpm']}, lyric={sc['lyric']}, "
            f"fullscreen={ust_info['player_style']['fullscreen']}"
        )
        try:
            self._player_window = display(ust_info)
            logger.info("播放器窗口已显示")
        except Exception:
            logger.exception("播放器启动失败")
            raise

    # ===================== 拖拽支持 =====================

    _VALID_EXTENSIONS = {'.ustx', '.uplr', '.mp3', '.wav', '.flac', '.lrc'}

    def dragEnterEvent(self, event):
        """仅接受合法的文件拖入。"""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                ext = os.path.splitext(urls[0].toLocalFile())[1].lower()
                if ext in self._VALID_EXTENSIONS:
                    event.acceptProposedAction()

    def dropEvent(self, event):
        """处理文件拖入（支持 .ustx/.uplr 文件）。"""
        urls = event.mimeData().urls()
        if not urls:
            return
        file_path = urls[0].toLocalFile()
        if not os.path.exists(file_path):
            return

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self._VALID_EXTENSIONS:
            InfoBar.error("ERcode002", f"不支持的文件格式：{ext}", orient=Qt.Orientation.Vertical, duration=3000,
                          parent=self, position=InfoBarPosition.TOP_RIGHT)
            return
        self._handle_dropped_file(file_path)

    def _handle_dropped_file(self, file_path: str):
        """统一处理拖入/命令行传入的文件（.ustx/.uplr/.mp3/.wav/.flac/.lrc）。

        .uplr 加载后同步所有页面，其余仅同步 file_page。
        """
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.uplr':
            # 先弹提示（动画流畅），重活儿延迟执行避免阻塞 UI 动画
            InfoBar.success("成功", f"已加载工程：{file_path}", orient=Qt.Orientation.Vertical, duration=2000,
                            parent=self, position=InfoBarPosition.TOP_RIGHT)
            QTimer.singleShot(400, lambda: self._do_uplr_drop(file_path))
        elif ext in ('.mp3', '.wav', '.flac'):
            self._settings.audio_path = file_path
            self._settings.write_settings()
            self.file_page.sync_all_from_settings()
            InfoBar.success("成功", "已选择音频文件", orient=Qt.Orientation.Vertical, duration=1500,
                            parent=self, position=InfoBarPosition.TOP_RIGHT)
        elif ext == '.lrc':
            self._settings.lrc_path = file_path
            self._settings.write_settings()
            self.file_page.sync_all_from_settings()
            max_langs = detect_lrc_max_languages(file_path)
            if max_langs > 1:
                msg = f"已选择歌词文件（检测到 {max_langs} 种语言）"
            else:
                msg = "已选择歌词文件"
            InfoBar.success("成功", msg, orient=Qt.Orientation.Vertical, duration=1500,
                            parent=self, position=InfoBarPosition.TOP_RIGHT)
        else:  # .ustx
            self._settings.ustx_path = file_path
            self._settings.last_open_dir = os.path.dirname(file_path)
            InfoBar.success("成功", f"已选择 USTX 文件：{file_path}", orient=Qt.Orientation.Vertical, duration=2000,
                            parent=self, position=InfoBarPosition.TOP_RIGHT)
            QTimer.singleShot(600, self._do_ustx_post_drop)

    def _load_dropped_uplr(self):
        """处理拖拽到 exe 上的文件（从命令行参数获取）。"""
        if len(sys.argv) <= 1:
            return

        dropped = sys.argv[1].strip()
        if not dropped or not os.path.exists(dropped):
            return

        ext = os.path.splitext(dropped)[1].lower()
        if ext not in self._VALID_EXTENSIONS:
            return
        self._handle_dropped_file(dropped)

    def _do_ustx_post_drop(self):
        """Toast 动画结束后执行：写配置 → 同步页面 → 启动后台解析。"""
        # 项目名为空时自动使用 ustx 文件名（不含扩展名），在同步页面之前填充
        if self._settings.maybe_fill_project_name_from_ustx():
            InfoBar.success("提示", f"工程名为空，已自动填充为：{self._settings.project_name}",
                            orient=Qt.Orientation.Vertical, duration=2000, parent=self, position=InfoBarPosition.TOP_RIGHT)
        self._settings.write_settings()
        self.file_page.sync_all_from_settings()
        self.basic_page.sync_all_from_settings()
        self.file_page._on_match()

    def _do_uplr_drop(self, file_path: str):
        """UPLR 拖入延迟执行：导入 → 写配置 → 同步页面 → 后台解析 USTX。

        在 InfoBar 动画播放完毕后执行，避免 import_uplr 的 JSON 反序列化、
        缓存写入等操作阻塞 UI 动画。
        """
        try:
            self._settings.import_uplr(file_path, parse_ustx=False)
            self._settings.last_open_dir = os.path.dirname(file_path)
            self._settings.write_settings()
            self._sync_all_pages()
            self.file_page._on_match()
        except ProjectFileMissingError as e:
            # 配置已加载到内存，仅文件路径无效：同步 UI 供用户重新选择文件
            self._settings.last_open_dir = os.path.dirname(file_path)
            self._settings.write_settings()
            self._sync_all_pages()
            self.file_page._on_match()
            InfoBar.error("ERcode006", f"工程已加载，但以下文件路径无效：\n{e}",
                          orient=Qt.Orientation.Vertical, duration=5000, parent=self, position=InfoBarPosition.TOP_RIGHT)
        except Exception as e:
            InfoBar.error("ERcode006", f"加载工程文件失败：{e}", orient=Qt.Orientation.Vertical, duration=3000,
                          parent=self, position=InfoBarPosition.TOP_RIGHT)

    # ===================== 导航切换时同步页面 =====================

    def switchTo(self, interface):
        """覆写父类方法，切换后同步页面数据。"""
        # 切换前清除歌词编辑页的选中
        self.lyric_edit_page.table.clearSelection()
        self.lyric_edit_page.table.setCurrentCell(-1, -1)
        super().switchTo(interface)
        # 隐藏导航栏可能残留的浮动 tooltip
        self._hide_orphan_tooltips()
        target = interface.widget() if isinstance(interface, QScrollArea) else interface
        # target 可能为 None，用 getattr + 默认值避免静态告警
        sync = getattr(target, "sync_all_from_settings", None)
        if sync is not None:
            sync()

    def changeEvent(self, event: QEvent):
        """窗口激活状态变化时清理残留 tooltip。"""
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowDeactivate:
            # 窗口失活时 qfluentwidgets 的导航 tooltip 不会自动隐藏
            self._hide_orphan_tooltips()

    def _hide_orphan_tooltips(self):
        """隐藏可能残留的 qfluentwidgets 导航 tooltip。

        折叠导航栏的悬停提示由 ToolTipFilter 管理，仅在 Leave/Hide/MouseButtonPress
        时隐藏；窗口失活不触发这些事件，导致 tooltip 残留飘在窗口上。
        """
        for child in self.findChildren(QWidget):
            if type(child).__name__ == "ToolTip" and "qfluentwidgets" in type(child).__module__:
                child.hide()


# ===================== 程序入口 =====================

def main():
    logger.info("=" * 50)
    logger.info("ustxPlayer 启动")
    logger.info(f"Python: {sys.version}")
    logger.info(f"工作目录: {os.getcwd()}")
    try:
        from PySide6.QtCore import qVersion
        logger.info(f"Qt 版本: {qVersion()}")
    except Exception:
        pass

    # 修复任务栏图标 - 设置 AppUserModelID
    try:
        import ctypes
        app_id = "ustxPlayer.ustxPlayer.1"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("ustxPlayer")
    app.setApplicationDisplayName("ustxPlayer")

    # 安装中文翻译器，汉化 qfluentwidgets 内部英文文案
    # 用局部变量持有引用：main() 阻塞在 app.exec() 直到退出，translator 存活整个应用生命周期
    from core.i18n import ChineseTranslator
    translator = ChineseTranslator()
    app.installTranslator(translator)

    # 加载 Qt 自带的中文翻译，汉化 QFileDialog/QMessageBox 等标准对话框
    from PySide6.QtCore import QLibraryInfo, QTranslator
    translations_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)

    qtbase_translator = QTranslator()
    if qtbase_translator.load("qtbase_zh_CN", translations_dir):
        app.installTranslator(qtbase_translator)
        logger.info("已加载 Qt 中文翻译: qtbase_zh_CN.qm")
    else:
        logger.warning(f"Qt 中文翻译 qtbase_zh_CN 加载失败，目录: {translations_dir}")

    qt_translator = QTranslator()
    if qt_translator.load("qt_zh_CN", translations_dir):
        app.installTranslator(qt_translator)
        logger.info("已加载 Qt 中文翻译: qt_zh_CN.qm")
    else:
        logger.warning(f"Qt 中文翻译 qt_zh_CN 加载失败，目录: {translations_dir}")

    # 设置应用图标（确保任务栏图标正确）
    # 与 SettingsManager.program_root 一致：基于 sys.argv[0]
    program_root = os.path.dirname(os.path.abspath(sys.argv[0]))
    icon_path = os.path.join(program_root, "icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    logger.info("正在创建主窗口...")
    window = MainWindow()
    window.show()
    logger.info("主窗口已显示")

    # 退出时清理：先停止 file_page 后台解析线程，再清空缓存目录
    app.aboutToQuit.connect(window.file_page.cleanup_parse_thread)
    app.aboutToQuit.connect(window._settings.clear_cache)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()