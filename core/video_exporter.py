# video_exporter.py — 视频导出引擎
"""组合 RendererCore + ffmpeg 管道，逐帧渲染并编码输出 MKV。

运行在 QThread 中；帧跳过放导出层（场景未变时复用上一帧字节）。
"""

import os
import ctypes
import functools
import json
import math
import shutil
import subprocess
import tempfile
import threading
import time
import winreg

import av
from av.video.reformatter import VideoReformatter, ColorRange

from PySide6.QtCore import QObject, Signal, QThread
from PySide6.QtGui import QImage, QPainter

from core.log import logger
from core.renderer_core import RendererCore, calc_total_tick
from core.time_axis import TimeAxis


# Windows: keep subprocesses from popping up a console window
_NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW


# 分辨率预设：显示名（长×宽）→ (宽, 高)
RESOLUTION_PRESETS = {
    "1280×720": (1280, 720),
    "1920×1080": (1920, 1080),
    "3840×2160": (3840, 2160),
}

FPS_OPTIONS = [30, 60]


def find_ffmpeg() -> str:
    """按优先级查找 ffmpeg.exe：exe 同目录 → 项目 tools\\ffmpeg → PATH。"""
    candidates = []
    # 打包后 exe 同目录
    import sys
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.abspath(sys.argv[0]))
        candidates.append(os.path.join(base, "ffmpeg.exe"))
    # 开发环境项目 tools\ffmpeg
    module_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(module_dir)
    candidates.append(os.path.join(project_root, "tools", "ffmpeg", "ffmpeg.exe"))
    for c in candidates:
        if os.path.isfile(c):
            return c
    found = shutil.which("ffmpeg")
    if found:
        return found
    return ""


def probe_audio_duration(audio_path: str) -> float:
    """用 PyAV 探测音频时长（秒），失败返回 0。"""
    if not audio_path or not os.path.isfile(audio_path):
        return 0.0
    try:
        with av.open(audio_path) as container:
            duration = container.duration
            if not duration:
                return 0.0
            return duration / av.time_base
    except Exception:
        logger.exception("PyAV 探测音频时长失败")
    return 0.0


def _tight_plane_bytes(plane, row_bytes: int, rows: int) -> bytes:
    """取一个 YUV 平面按行去掉填充后的紧凑字节。"""
    data = ctypes.string_at(plane.buffer_ptr, plane.buffer_size)
    line_size = plane.line_size
    if line_size == row_bytes:
        return data[: row_bytes * rows]
    out = bytearray(row_bytes * rows)
    src = memoryview(data)
    for r in range(rows):
        start = r * row_bytes
        out[start:start + row_bytes] = src[r * line_size:r * line_size + row_bytes]
    return bytes(out)


# libswscale 全范围（JPEG range）BT.601 转换会把中性灰的 U/V 算成 127 而不是 128
# （系统性 -1 色度偏移，8bit 解码回来灰会偏 2~3），用查表整体 +1 补偿（255 封顶）。
# 该补偿仅对"全范围 + BT.601 + 8bit"成立，与 ffmpeg 侧 smpte170m 标签配套。
_UV_PLUS_ONE_TABLE = bytes(range(1, 256)) + b"\xff"


class Yuv420pConverter:
    """RGBA8888 QImage → 紧凑全范围 YUV420P 字节（Y+U+V 连续，BT.601 矩阵），供 rawvideo 管道输入。

    用持久化 VideoReformatter 复用 sws 上下文，避免每帧重建（约 7ms/次）；
    输出全范围（dst_color_range=JPEG）：纯黑 RGB(0,0,0) 映射为 Y=0，
    避免默认有限范围（黑=Y=16）在部分播放器按全范围解读时显示偏灰；
    矩阵是 sws 默认 BT.601，ffmpeg 侧必须按 BT.601 打标签；
    输出后对 U/V 平面做 +1 查表补偿（见 _UV_PLUS_ONE_TABLE），否则灰阶会偏 2~3。
    """

    def __init__(self, width: int, height: int):
        self._width = width
        self._height = height
        self._src = av.VideoFrame(width, height, format="rgba")
        self._src_linesize = self._src.planes[0].line_size
        self._reformatter = VideoReformatter()

    def convert(self, img: QImage) -> bytes:
        bpl = img.bytesPerLine()
        if self._src_linesize == bpl:
            self._src.planes[0].update(img.constBits())
        else:
            raw = memoryview(img.constBits())
            padded = bytearray(self._src_linesize * self._height)
            for r in range(self._height):
                src_off = r * bpl
                dst_off = r * self._src_linesize
                padded[dst_off:dst_off + bpl] = raw[src_off:src_off + bpl]
            self._src.planes[0].update(padded)
        yuv = self._reformatter.reformat(
            self._src, width=self._width, height=self._height,
            format="yuv420p", dst_color_range=ColorRange.JPEG,
        )
        y_plane, u_plane, v_plane = yuv.planes
        return (
            _tight_plane_bytes(y_plane, self._width, self._height)
            + _tight_plane_bytes(u_plane, self._width // 2, self._height // 2).translate(_UV_PLUS_ONE_TABLE)
            + _tight_plane_bytes(v_plane, self._width // 2, self._height // 2).translate(_UV_PLUS_ONE_TABLE)
        )


def _gpu_details_from_registry() -> list:
    """从显卡驱动注册表键读取显卡详情；读不到时返回空列表。"""
    details = []
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as key:
            for i in range(32):
                try:
                    sub = winreg.EnumKey(key, i)
                except OSError:
                    break
                try:
                    with winreg.OpenKey(key, sub) as sub_key:
                        desc = winreg.QueryValueEx(sub_key, "DriverDesc")[0]
                        driver = None
                        try:
                            driver = winreg.QueryValueEx(sub_key, "DriverVersion")[0]
                        except OSError:
                            pass
                        vram = None
                        try:
                            with winreg.OpenKey(sub_key, "HardwareInformation") as hw_key:
                                vram = winreg.QueryValueEx(hw_key, "qwMemorySize")[0]
                        except OSError:
                            pass
                except OSError:
                    continue
                if isinstance(desc, str) and desc.strip():
                    details.append({
                        "name": desc.strip(),
                        "driver": driver if isinstance(driver, str) and driver.strip() else None,
                        "vram_bytes": int(vram) if isinstance(vram, int) and vram > 0 else None,
                    })
    except OSError:
        return []
    return details


def _gpu_details_from_cim() -> list:
    """用 PowerShell CIM 枚举显卡详情；被权限拦截时返回空列表。"""
    try:
        cmd = [
            "powershell.exe", "-NoProfile", "-Command",
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name, DriverVersion, AdapterRAM | ConvertTo-Json -Compress",
        ]
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW_FLAGS,
        ).stdout
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        details = []
        for item in data:
            name = (item.get("Name") or "").strip()
            if not name:
                continue
            driver = item.get("DriverVersion")
            vram = item.get("AdapterRAM")
            details.append({
                "name": name,
                "driver": driver if isinstance(driver, str) and driver.strip() else None,
                "vram_bytes": int(vram) if isinstance(vram, int) and vram > 0 else None,
            })
        return details
    except Exception:
        logger.exception("枚举显卡信息失败")
        return []


@functools.lru_cache(maxsize=1)
def list_gpu_details() -> list:
    """枚举本机显卡详情 [{name, driver, vram_bytes}]；注册表优先，退回 CIM。"""
    details = _gpu_details_from_registry()
    if not details:
        details = _gpu_details_from_cim()
    return details


@functools.lru_cache(maxsize=1)
def list_gpu_names() -> list:
    """枚举本机显卡名称（Windows）：注册表优先，读不到再退回 PowerShell CIM。"""
    return [g["name"] for g in list_gpu_details()]


def list_gpu_vendors() -> set:
    """按显卡名称判断厂商，返回 {'nvidia', 'amd', 'intel'} 的子集。"""
    vendors = set()
    for name in list_gpu_names():
        low = name.lower()
        if "nvidia" in low:
            vendors.add("nvidia")
        elif "amd" in low or "radeon" in low or "ati" in low:
            vendors.add("amd")
        elif "intel" in low:
            vendors.add("intel")
    return vendors


# 单飞行：进程内只探测一次硬件/编码设备，合并导出页后台探测与导出线程兜底，
# 避免两者并发时重复跑 ffmpeg。
_probe_lock = threading.Lock()
_probe_result = None  # 富字典，仅成功时写入
_probe_done = threading.Event()


def probe_hardware_info() -> dict:
    """返回本机硬件探测结果（单飞行，复用 enumerate_devices 的探测）。

    富字典：gpus（名称/驱动/显存）、encoders（nvenc/qsv/amf 是否编译进 ffmpeg）、
    vendor_ok（各硬件编码器对应厂商显卡是否存在）、devices（可用设备，含 cpu）、
    preferred（自动首选）、ffmpeg（路径+版本，缺失为 None）。
    """
    global _probe_result
    if _probe_done.is_set():
        return _probe_result
    with _probe_lock:
        if not _probe_done.is_set():
            _probe_result = _run_probe()
            _probe_done.set()
    return _probe_result


def enumerate_devices() -> tuple:
    """枚举可用编码设备（单飞行：首个调用真正探测，其余调用等待并复用结果）。

    返回 (可用设备列表, 自动模式首选设备)；设备字符串：nvenc / qsv / amf / cpu。
    按本机显卡厂商过滤：AMD 机器不出现 Intel QSV、NVIDIA 机器不出现 AMD AMF；
    显卡信息读取失败时退回 ffmpeg 支持的全部设备。
    """
    info = probe_hardware_info()
    return info["devices"], info["preferred"]


def _ffmpeg_version(path: str):
    """取 ffmpeg 版本号（-version 第一行解析）；失败返回 None。"""
    try:
        out = subprocess.run(
            [path, "-version"], capture_output=True, timeout=5,
            creationflags=_NO_WINDOW_FLAGS,
        ).stdout
        # 精简版 ffmpeg 的 banner 是 UTF-8 字节，text=True 会按 GBK 解码失败；
        # 统一按字节取回再解码，任何构建都能读。
        text = out.decode("utf-8", errors="replace")
        parts = text.splitlines()[0].split() if text.splitlines() else []
        if len(parts) >= 3 and parts[0] == "ffmpeg" and parts[1] == "version":
            return parts[2]
        return None
    except Exception:
        logger.exception("ffmpeg -version 查询失败")
        return None


def _run_probe() -> dict:
    """实际执行探测；异常不缓存结果，下次调用可重试。"""
    gpus = list_gpu_details()
    ffmpeg = find_ffmpeg()
    encoders = {"nvenc": False, "amf": False, "qsv": False}
    ffmpeg_info = None
    if ffmpeg:
        try:
            out = subprocess.run(
                [ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                timeout=15, creationflags=_NO_WINDOW_FLAGS,
            ).stdout
            out = out.decode("utf-8", errors="replace")
        except Exception:
            logger.exception("ffmpeg -encoders 查询失败")
            out = ""
        for enc in encoders:
            encoders[enc] = f"h264_{enc}" in out
        ffmpeg_info = {"path": ffmpeg, "version": _ffmpeg_version(ffmpeg)}

    supported = [enc for enc, ok in encoders.items() if ok] + ["cpu"]
    vendors = list_gpu_vendors()
    hw_vendor = {"nvenc": "nvidia", "qsv": "intel", "amf": "amd"}
    if vendors:
        vendor_ok = {enc: hw_vendor[enc] in vendors for enc in encoders}
        devices = [
            dev for dev in supported
            if dev == "cpu" or vendor_ok.get(dev)
        ]
    else:
        vendor_ok = {enc: False for enc in encoders}
        devices = supported
    if not ffmpeg:
        devices = []
    return {
        "gpus": gpus,
        "encoders": encoders,
        "vendor_ok": vendor_ok,
        "devices": devices,
        "preferred": devices[0] if devices else "cpu",
        "ffmpeg": ffmpeg_info,
    }


def _ustx_content_duration(ustx_info: dict) -> float:
    """USTX 内容时长（秒）。"""
    total_tick = calc_total_tick(ustx_info.get("notes", []))
    return TimeAxis(
        ustx_info.get("tempos") or [], ustx_info.get("tempo", 120.0)
    ).tick_to_seconds(total_tick)


def compute_total_duration(ustx_info: dict, audio_duration: float) -> float:
    """导出总时长 = max(USTX 内容时长, 音频时长)。"""
    return max(_ustx_content_duration(ustx_info), audio_duration)


class VideoExporter(QObject):
    """视频导出工作对象（moveToThread 使用）。"""

    progress = Signal(int, int, float)  # 已完成帧数, 总帧数, 已用秒数
    finished_ok = Signal(str)           # 输出文件路径
    failed = Signal(str)                # 错误信息

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel_requested = False
        self._pending_args = None
        self._main_thread = QThread.currentThread()

    def cancel(self):
        """请求取消导出（跨线程调用，线程安全）。"""
        self._cancel_requested = True

    def set_export_args(
        self,
        ustx_info: dict,
        output_path: str,
        width: int,
        height: int,
        fps: int,
        device: str,
        audio_path: str = "",
        audio_duration: float = 0.0,
        probe_audio: bool = True,
    ):
        """设置导出参数，随后由线程 started 信号调用 run_pending 执行。"""
        self._pending_args = (
            ustx_info, output_path, width, height, fps, device,
            audio_path, audio_duration, probe_audio,
        )

    def run_pending(self):
        """线程 started 信号入口（零参数，兼容信号直连）。"""
        if self._pending_args is None:
            return
        self.export(*self._pending_args)

    def _finish(self, ok: bool, payload: str):
        """发出结果信号并退出当前线程事件循环。"""
        if ok:
            self.finished_ok.emit(payload)
        else:
            self.failed.emit(payload)
        thread = QThread.currentThread()
        if thread is not None and thread is not self._main_thread:
            thread.quit()

    def export(
        self,
        ustx_info: dict,
        output_path: str,
        width: int,
        height: int,
        fps: int,
        device: str,
        audio_path: str = "",
        audio_duration: float = 0.0,
        probe_audio: bool = True,
    ):
        """执行导出（在工作线程中运行）。"""
        self._cancel_requested = False

        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            self._finish(False, "未找到 ffmpeg，请将 ffmpeg.exe 放到程序目录或 tools\\ffmpeg 下")
            return

        stderr_path = None
        try:
            if probe_audio and audio_path and os.path.isfile(audio_path):
                audio_duration = probe_audio_duration(audio_path)
                logger.info(f"PyAV 音频时长: {audio_duration:.2f}s")

            if device == "auto":
                # 兜底路径：单飞行复用页面后台探测的结果，不会重复跑 ffmpeg
                _, device = enumerate_devices()

            total_duration = compute_total_duration(ustx_info, audio_duration)
            total_frames = max(1, int(math.ceil(total_duration * fps)))
            logger.info(
                f"导出开始 — {width}x{height}@{fps}fps, 设备={device}, "
                f"时长={total_duration:.2f}s, 总帧数={total_frames}"
            )

            core = RendererCore(ustx_info, width, height)

            cmd = self._build_ffmpeg_command(
                ffmpeg, output_path, width, height, fps, device,
                audio_path,
            )
            logger.debug(f"ffmpeg 命令: {' '.join(cmd)}")

            # 预检输出文件是否被其他进程占用（WinError 32 常见根因）。
            # "ab" 打开即可探测可写性，又不会截断已有内容。
            try:
                probe_fd = open(output_path, "ab")
                probe_fd.close()
                logger.debug(f"输出文件可访问: {output_path}")
            except OSError as e:
                logger.error(f"输出文件被占用，无法写入: {output_path} ({e})")
                self._finish(
                    False,
                    f"输出文件被占用，无法写入：{output_path}\n"
                    "请关闭正在使用该文件的程序后重试",
                )
                return

            # ffmpeg 的 stderr 此前被丢弃，编码失败/文件被占用的真实原因全丢失；
            # 改写入临时日志文件，失败时归档到全局日志辅助排查。
            stderr_file = tempfile.NamedTemporaryFile(suffix=".log", delete=False)
            stderr_path = stderr_file.name
            try:
                proc = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=stderr_file, creationflags=_NO_WINDOW_FLAGS,
                )
            finally:
                stderr_file.close()
            if proc.stdin is None:
                self._log_ffmpeg_stderr(stderr_path)
                self._finish(False, "无法打开 ffmpeg 输入管道")
                return

            img = QImage(width, height, QImage.Format.Format_RGBA8888)
            img.fill(0)
            yuv_converter = Yuv420pConverter(width, height)
            last_signature = None
            cached_bytes = b""

            # 进度信号每 3 帧发一次：30fps 下约 10 次/秒，进度条/任务栏足够平滑，
            # 每帧都发会让主线程的 UI 更新（进度条/文本/滑块）堆积导致卡顿
            start_wall = time.monotonic()
            for frame_no in range(total_frames):
                if self._cancel_requested:
                    break

                t = frame_no / fps
                core.set_time(t)
                signature = core.frame_signature()
                if signature != last_signature:
                    # 场景变化才重绘；否则复用上一帧字节
                    painter = QPainter(img)
                    try:
                        core.paint(painter, width, height, 1.0)
                    finally:
                        painter.end()
                    cached_bytes = yuv_converter.convert(img)
                    last_signature = signature

                proc.stdin.write(cached_bytes)
                fn = frame_no + 1
                if fn % 3 == 0 or fn == total_frames:
                    elapsed = time.monotonic() - start_wall
                    self.progress.emit(fn, total_frames, elapsed)

            proc.stdin.close()
            proc.wait(timeout=30)

            stderr_text = self._read_stderr_text(stderr_path)
            self._log_ffmpeg_stderr_text(stderr_text)

            if self._cancel_requested:
                self._finish(False, "导出已取消")
                self._remove_partial_file(output_path)
                return
            if proc.returncode != 0:
                friendly = self._friendly_ffmpeg_error(stderr_text)
                self._finish(
                    False,
                    friendly or f"ffmpeg 编码失败（退出码 {proc.returncode}）",
                )
                self._remove_partial_file(output_path)
                return
            self._finish(True, output_path)
        except Exception as e:
            logger.exception("导出异常")
            # 典型场景：硬件编码器初始化失败使 ffmpeg 提前退出，
            # 本线程继续写 stdin 就抛 BrokenPipeError(errno 32)；
            # 此时 stderr 里才有真正的失败原因，必须转成用户可读信息
            stderr_text = self._read_stderr_text(stderr_path)
            self._log_ffmpeg_stderr_text(stderr_text)
            friendly = self._friendly_ffmpeg_error(stderr_text)
            self._finish(False, friendly or f"导出异常：{e}")
            self._remove_partial_file(output_path)
        finally:
            if stderr_path:
                try:
                    if os.path.isfile(stderr_path):
                        os.remove(stderr_path)
                except Exception:
                    pass

    @staticmethod
    def _build_ffmpeg_command(
        ffmpeg: str, output_path: str, width: int, height: int,
        fps: int, device: str, audio_path: str,
    ) -> list:
        """构造 ffmpeg 命令行。"""
        if device == "nvenc":
            vcodec = ["-c:v", "h264_nvenc", "-cq", "20", "-preset", "p5"]
        elif device == "qsv":
            vcodec = ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "20"]
        elif device == "amf":
            vcodec = ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "20", "-qp_p", "20"]
        else:
            vcodec = ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
        cmd = [
            ffmpeg, "-y", "-hide_banner",
            "-f", "rawvideo", "-pix_fmt", "yuv420p",
            "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
        ]
        if audio_path and os.path.isfile(audio_path):
            # 原始音频流直接封装，零重编码零损失；不加 -shortest
            cmd += ["-i", audio_path]
        cmd += [
            # 输入已是紧凑全范围 BT.601 yuv420p；setparams=range=pc 必须置于最前，
            # 否则 -color_range full 会让 ffmpeg 误把输入当有限范围二次拉伸（灰 95→92、蓝掉 15）
            "-vf", f"setparams=range=pc:colorspace=smpte170m,crop={width}:{height}:0:0",
            "-pix_fmt", "yuv420p",
        ] + vcodec + [
            # 全范围 + BT.601 标签由编码器写（-color_range/-colorspace）
            # 注：命令行 -color_trc/-color_primaries 实测对 libx264/NVENC/QSV/AMF
            # 都不写入 SPS VUI（trace_headers 验证 primaries=2=undef），如需补全
            # 颜色标签要靠 h264_metadata bsf 或 libx264 的 -x264-params
            "-color_range", "full",
            "-colorspace", "smpte170m",
        ]
        if audio_path and os.path.isfile(audio_path):
            cmd += ["-c:a", "copy"]
        cmd += ["-f", "matroska", output_path]
        return cmd

    @staticmethod
    def _remove_partial_file(output_path: str):
        """取消/失败时清理未完成的输出文件。"""
        try:
            if os.path.isfile(output_path):
                os.remove(output_path)
                logger.info(f"已清理未完成导出文件: {output_path}")
        except Exception:
            logger.exception("清理未完成导出文件失败")

    @staticmethod
    def _read_stderr_text(stderr_path: str | None) -> str:
        """读取 ffmpeg 的临时 stderr 日志文本；读不到返回空串。"""
        if not stderr_path or not os.path.isfile(stderr_path):
            return ""
        try:
            with open(stderr_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            logger.exception("读取 ffmpeg stderr 日志失败")
            return ""

    @staticmethod
    def _log_ffmpeg_stderr_text(stderr_text: str):
        """把 ffmpeg stderr 内容记入全局日志（辅助排查编码失败）。"""
        if stderr_text.strip():
            logger.info(f"ffmpeg stderr:\n{stderr_text}")
        else:
            logger.debug("ffmpeg stderr:（空）")

    @staticmethod
    def _friendly_ffmpeg_error(stderr_text: str) -> str:
        """识别硬件编码器初始化失败（驱动过旧等），返回统一提示；识别不了返回空串。"""
        low = stderr_text.lower()
        hw = ("nvenc", "qsv", "amf")
        fail = (
            "does not support the required",   # NVIDIA：驱动 API 版本不够
            "minimum required",                # NVIDIA：最低驱动提示
            "error while opening encoder",
            "error initializing",              # QSV：会话初始化失败
            "error creating",                  # QSV
            "failed to initiali",              # AMF：initialize/initialise
            "failed to create",
        )
        if any(h in low for h in hw) and any(k in low for k in fail):
            return "显卡驱动版本过旧，无法使用硬件编码。\n请将编码设备改为 CPU 后重试，或更新显卡驱动。"
        return ""
