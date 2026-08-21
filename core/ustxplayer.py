# ustxplayer.py — 全屏播放器
"""USTX 音符可视化播放器，使用 QPainter 渲染全屏动画。

渲染（状态推进 + 绘制）由 RendererCore 承担，本文件只负责
播放控制：系统时钟、音频同步、倍速、seek、键盘事件与计时器叠加。
"""

import os
import time
import ctypes

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QPainter, QColor
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from core.log import logger
from core.renderer_core import (
    RendererCore, format_play_time,
)


# ===================== 工具常量 =====================

# Windows 媒体键虚拟键码
_VK_VOLUME_UP = 0xAF
_VK_VOLUME_DOWN = 0xAE
_KEYEVENTF_KEYUP = 0x0002


def step_system_volume(up: bool):
    """模拟按下音量增/减媒体键，调节 Windows 系统音量（无需第三方依赖）。

    每次调用触发一次按键（按下+抬起），约改变 2~3% 系统音量。
    仅适用于 Windows（本程序已依赖 winreg，限定 Windows 平台）。
    """
    vk = _VK_VOLUME_UP if up else _VK_VOLUME_DOWN
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)


# ===================== 播放器窗口 =====================

class NoteLyricDisplay(QWidget):
    """全屏播放器 — QPainter 渲染所有内容。"""

    def __init__(self, ustx_info: dict):
        super().__init__()

        # ---- 窗口配置 ----
        self.setWindowTitle("ustxPlayer - Player")
        self._fullscreen = ustx_info["player_style"].get("fullscreen", True)
        # 窗口标志由 display() 在 show 前统一设置

        # ---- 屏幕尺寸 ----
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            self.w, self.h = geo.width(), geo.height()
        else:
            self.w, self.h = 1920, 1080
        logger.debug(f"屏幕尺寸: {self.w}x{self.h}")

        # ---- 共享渲染核心（状态推进 + 绘制） ----
        self._core = RendererCore(ustx_info, self.w, self.h)

        # ---- 播放倍率 ----
        self._playback_speed = 1.0

        # ---- 音频播放 ----
        self.audio_path = ustx_info["player_style"].get("audio_path", "")
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

        # ---- 播放状态 ----
        self.start_real_time = 0.0  # 在 showEvent 中与音乐同步设置
        self._play_elapsed = 0.0
        self._finished = False
        self._final_elapsed = 0.0
        self._resync_active = False  # 启动/恢复/seek 后的等待音频起播窗口
        self._resync_target = 0.0
        self._resync_deadline = 0.0

        # ---- 定时器（10ms ≈ 100fps，PreciseTimer 保证平滑） ----
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

        # 播放结束后的自动关闭定时器（单次触发，允许 closeEvent 提前停止）
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.timeout.connect(self.close)

        # 漂移校准定时器：音频时钟与系统时钟独立，长时间播放会累积偏差
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(1000)
        self._sync_timer.timeout.connect(self._periodic_resync)

        # 等待音频起播的轮询定时器：启动/恢复/seek 后画面保持，音频真正起播再锚定
        self._resync_poll_timer = QTimer(self)
        self._resync_poll_timer.timeout.connect(self._poll_audio_start)

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
            self.start_real_time = time.monotonic()
            # play() 异步起播：进入等待窗口，音频真正起播时再锚定，避免启动延迟的恒定偏移
            self._begin_resync_poll()
            self._sync_timer.start()
            logger.info("音频开始播放")
        else:
            self.start_real_time = time.monotonic()
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
        """用实际 widget 尺寸更新渲染核心的分辨率与字体。"""
        new_w, new_h = self.width(), self.height()
        if new_w > 0 and new_h > 0 and (new_w != self.w or new_h != self.h):
            self.w, self.h = new_w, new_h
            self._core.set_resolution(new_w, new_h)

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

    # ===================== 主循环 =====================

    def _tick(self):
        """定时器回调：统一使用系统时钟计算当前位置 → 更新渲染状态。"""
        try:
            # 等待音频起播窗口内画面保持不动，由轮询在音频起播瞬间锚定
            if self._resync_active:
                return
            # 统一使用系统时钟，不读取 _media_player.position()，避免系统时钟与音频位置两个时钟源不一致导致的边界问题。
            # 注意：USTX 走完（_finished）后若音频仍在播放，必须继续推进 _play_elapsed，
            # 否则左下角时间会提前冻结，与音频实际进度脱节。
            if not self._finished or self._audio_playing:
                self._play_elapsed = (time.monotonic() - self.start_real_time) * self._playback_speed

            if self._finished:
                self._core.set_time(self._play_elapsed)
                if not self._audio_playing:
                    self._timer.stop()
                    logger.info("播放完成，1秒后关闭窗口")
                    self._close_timer.start(1000)
                self.update()
                return

            current_tick = self._core.time_axis.seconds_to_tick(self._play_elapsed)

            # 播放结束（音符走完）
            if current_tick >= self._core.total_tick:
                self._finished = True
                self._final_elapsed = self._core.duration_seconds
                self._core.set_finished(True)
                self.update()
                if self._audio_playing:
                    logger.info("音符播放完成，等待音频结束")
                else:
                    self._play_elapsed = self._final_elapsed
                    self._timer.stop()
                    logger.info("播放完成，1秒后关闭窗口")
                    self._close_timer.start(1000)
                return

            # 推进渲染核心状态（当前音符、歌词、LRC、背景色）
            self._core.set_time(self._play_elapsed)

            self.update()  # 触发 paintEvent

        except Exception:
            logger.exception("_tick 异常")

    # ===================== 绘制 =====================

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            self._core.paint(painter, self.width(), self.height(), self._playback_speed)
            # 播放时间（左下角）：唯一每帧变化的计时器元素，由播放器叠加
            if self._core.show_play_time:
                painter.setPen(QColor(self._core.small_font_color_hex))
                painter.setFont(self._core.timer_font)
                fm_timer = self._core._fm_timer
                margin_x = max(12, int(self.width() * 0.01))
                margin_y = max(12, int(self.height() * 0.018))
                painter.drawText(
                    margin_x, self.height() - margin_y - fm_timer.descent(),
                    format_play_time(self._play_elapsed),
                )
        except Exception:
            logger.exception("paintEvent 异常")
        finally:
            painter.end()

    # ===================== 键盘/关闭事件 =====================

    def _get_max_play_time(self) -> float:
        """返回当前可达到的最大播放时间（秒）。

        当音频时长超过 USTX 时长时，允许快进到音频结尾；
        否则以 USTX 结尾为上限。无音频时仅以 USTX 结尾为准。
        """
        ustx_end = self._core.duration_seconds
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
        self.start_real_time = time.monotonic() - self._play_elapsed / new_speed
        self._playback_speed = new_speed
        logger.info(f"播放倍率: {self._playback_speed:.1f}")
        # 音频变速不变调
        if self._audio_playing:
            self._media_player.setPlaybackRate(self._playback_speed)
        # setPlaybackRate 是异步的，音频管线需要约 100-200ms 才能真正切换到新倍率。
        # 过渡期间解码器仍按旧倍率前进，而系统时钟已按新倍率前进，产生偏差。
        # 过渡稳定后触发一次校准，消除切换偏移；另有 1s 周期漂移检查兜底。
        # 校准只是重锚系统时钟，不引入持续的双时钟同步。
        QTimer.singleShot(200, self._recalibrate_from_audio)
        self.update()  # 暂停时也刷新倍率显示

    def _periodic_resync(self):
        """周期漂移检查：长时间播放时音频与系统时钟会累积偏差。"""
        self._recalibrate_from_audio(0.08)

    def _begin_resync_poll(self):
        """启动/恢复/seek 后进入等待音频起播窗口。

        画面保持不动，音频位置真正越过目标时立即锚定，
        把固定延时校准的回跳压缩到一个轮询周期内。
        """
        self._resync_poll_timer.stop()
        self._resync_target = self._play_elapsed
        self._resync_deadline = time.monotonic() + 0.6
        self._resync_active = True
        self._resync_poll_timer.start(25)

    def _poll_audio_start(self):
        """轮询音频是否已从目标位置起播，起播后立即锚定并结束轮询。"""
        if not self._audio_playing or self._closing:
            self._stop_resync_poll()
            return
        try:
            audio_pos = self._media_player.position() / 1000.0
            if audio_pos >= self._resync_target + 0.01:
                self._play_elapsed = audio_pos
                self._stop_resync_poll()
                logger.debug(f"音频起播锚定: elapsed={self._play_elapsed:.3f}s")
                self.update()
                return
        except Exception:
            logger.debug("音频起播轮询失败（忽略）")
        # 超时兜底：放行画面，交回常规校准
        if time.monotonic() >= self._resync_deadline:
            self._stop_resync_poll()
            self._recalibrate_from_audio()

    def _stop_resync_poll(self):
        """结束等待窗口，并把系统时钟重锚到当前 _play_elapsed，避免放开后时间跳变。"""
        self.start_real_time = time.monotonic() - self._play_elapsed / self._playback_speed
        self._resync_active = False
        self._resync_poll_timer.stop()

    def _recalibrate_from_audio(self, threshold: float = 0.05):
        """读取音频实际位置，偏差超过阈值时重锚系统时钟。

        用于倍速切换后、周期漂移检查以及等待窗口超时兜底。
        """
        if not self._audio_playing or self._finished or self._closing:
            return
        if self._resync_active:
            return
        try:
            audio_pos = self._media_player.position() / 1000.0
            # 音频尚未真正起播时 position 仍为 0，不校准，避免时间轴被重置
            if audio_pos <= 0 and self._play_elapsed > 0.2:
                return
            drift = audio_pos - self._play_elapsed
            if abs(drift) > threshold:
                self._play_elapsed = audio_pos
                self.start_real_time = time.monotonic() - self._play_elapsed / self._playback_speed
                logger.debug(
                    f"音频位置校准: drift={drift * 1000:.0f}ms, "
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
        if self._audio_playing:
            self._begin_resync_poll()
        self.start_real_time = time.monotonic() - self._play_elapsed / self._playback_speed
        self._core.set_time(self._play_elapsed)

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
                self.start_real_time = time.monotonic() - self._play_elapsed / self._playback_speed
                if self._has_audio():
                    pos_ms = int(self._play_elapsed * 1000)
                    # 仅当音频未结束或目标位置在音频时长内才操作播放器
                    if self._audio_duration_ms == 0 or pos_ms < self._audio_duration_ms:
                        self._media_player.setPosition(pos_ms)
                        self._media_player.setPlaybackRate(self._playback_speed)
                        self._media_player.play()
                        self._audio_playing = True
                        self._begin_resync_poll()
        # 左方向键 - 快退10秒
        elif key == Qt.Key.Key_Left:
            self._finished = False
            self._core.set_finished(False)
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
        self._sync_timer.stop()
        self._resync_poll_timer.stop()
        self._close_timer.stop()
        self._cleanup_audio()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().closeEvent(event)


# ===================== 对外接口 =====================

def display(ustx_info: dict) -> NoteLyricDisplay:
    """启动播放器窗口，返回窗口引用（调用方需保持引用防止 GC）。

    窗口标志必须在 show 之前统一设置，避免全屏与置顶标志冲突导致边角漏出。
    """
    logger.info("创建播放器窗口...")
    window = NoteLyricDisplay(ustx_info)

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
