<div align="center">

<img src="icon.svg" height="90" width="90"/>

# ustxPlayer

`v1.1.0` · 基于 [ustPlayer](https://github.com/SYEternalR/ustPlayer) 二次开发的 USTX 工程可视化工具。

![GitHub Release](https://img.shields.io/github/v/release/lyrinXD/ustxPlayer?style=for-the-badge)
![GitHub All Releases](https://img.shields.io/github/downloads/lyrinXD/ustxPlayer/total?style=for-the-badge)
![GitHub Stars](https://img.shields.io/github/stars/lyrinXD/ustxPlayer?style=for-the-badge)

[配布视频](https://www.bilibili.com/video/BV1puMk61EgT "bilibili弹幕网") | [更新日志](UPDATELOG.md)

![软件截图](https://github.com/user-attachments/assets/0983abb3-b66c-47cf-a558-1afc6caf04cb)

</div>

> [!NOTE]
> 本项目是 ustPlayer 的二次开发版本，核心定位从 UST 转向 **USTX**，并围绕播放体验、样式系统、歌词支持等方面进行了大量改进。

## 主要特性

### USTX 工程支持
- 原生支持 OpenUtau 的 `.ustx` 工程文件（基于 YAML 解析），**自动识别编码，无需手动指定**。
- 兼容 OpenUTAU `.ustx` 格式版本 **0.3 ~ 0.9**（最新版本），核心字段结构稳定，新旧工程均可正常读取。
- 支持**多轨工程**：按轨道名解析各人声轨，播放/导出可切换所选轨道。
- 支持**BPM不恒定**：变速工程的时间轴与显示 BPM 实时跟随。
- 自动剥离 `en/`、`ja/` 等歌词语言前缀，不参与渲染与编辑。
- 旧版 `.ust` 用户可通过 [UtaFormatix](https://utaformatix.tk/) 等工具转换后使用。

### 工程文件系统
- 工程文件（`.uprj`）**直接存储解析后的内容**，打开即用、无需携带 `.ustx`，加载更快更稳。
- 工程内各文件路径**均可为空**，故可当模板使用。

### 逐字样式系统
- 在项目中为**每一个字**精确定义样式（颜色、背景色等）。
- 配套直观的样式编辑界面，支持单字/批量编辑、自定义预设配色。

### 增强播放体验
- 支持**导入音频与 ustx 文件同步播放**，更直观的同时方便在剪辑软件中精确对轨。
- 播放控制：暂停 / 快进 / 快退 / 音量调节 / 倍速播放（快捷键详见软件内说明）。
- 画面元素（歌词、音高、信息等）随屏幕分辨率自动缩放适配。
- 更准确的音高曲线渲染。

### 视频导出
- 自动按 **NVENC（NVIDIA）→ AMF（AMD）→ QSV（Intel）→ CPU（libx264）** 的顺序选择编码器；有可用硬件时硬件加速，**可以相当快地导出视频**（实测 QSV 噪点偏多，故较不推荐使用 Intel 显卡编码）；无可用硬件时回退 CPU 软件编码。
- 与实时播放共用同一渲染核心，**所见即所得**，同时内置 16:9 实时预览，增强使用体验。
- 优化色彩转换，生成的视频不偏色不发灰。
- 支持合并音频、自定义分辨率，帧率可选 30/60 帧。
- **导出的视频不包含播放时间**：视频中只呈现画面与音频，不会显示播放进度时间。

> **设备运行要求**：显卡加速编码需要对应硬件与驱动支持，未达到要求会自动回退为 CPU 软件编码，详细要求如下：
> - **NVENC**（NVIDIA）：GTX 750 及以上（2014 起）+ 驱动 ≥ 531.61
> - **AMF**（AMD）：GCN 架构 HD 7000 及以上（2012 起）+ 驱动 2016+
> - **QSV**（Intel）：第 5 代酷睿 Broadwell 及以上（2015 起）+ **较新驱动**（建议 2024+）
> - **CPU**（libx264）：任意 x86_64 CPU 作为兜底

### 多语言 LRC 歌词
- 支持 `.lrc` 文件的**交错**与**独立**多语言格式。
- 理论支持任意行数，推荐 1~3 行以获得最佳显示效果。

### 更多自定义
- 全新应用图标。
- 卡片式界面，支持**卡片阴影开关**。
- 支持自定义界面**强调色**，适配深色模式。
- 可修改歌词/信息字体、信息颜色等，可隐藏软件版权信息。
- 内置**检查更新**（手动/每 7 天自动）。


## 安装与运行

### 环境要求
- Windows 10/11
- Python 3.12

### 从源码运行

```bash
# 1. 克隆仓库
git clone https://github.com/lyrinXD/ustxPlayer.git
cd ustxPlayer

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行
python main.py
```

### 可选：FFmpeg（视频导出需要）

视频导出功能依赖 FFmpeg。仅使用播放功能时无需安装。项目使用**定制版 FFmpeg**：为 ustxPlayer 精简编译，**体积仅约 10 MB（原版约 97 MB）**，只打包 NVENC / QSV / AMF 硬件编码器等必要组件，**推荐直接使用定制版**：

```bash
# 1. 从定制版 FFmpeg 附属仓库获取（推荐）：
#    https://github.com/rinflow05/FFmpeg-for-ustxPlayer
# 2. 将 ffmpeg.exe 放到项目根目录的 tools\ffmpeg\ffmpeg.exe
# 3. 未提供时 build.bat 会跳过打包并给出 WARNING，播放器仍可正常运行但无法导出视频
```

> 若无法使用定制版，也可从 https://www.gyan.dev/ffmpeg/builds/ 下载 `ffmpeg-release-essentials.zip` 作为备选。

### 打包为可执行文件

```bash
# 确保已安装 Nuitka
pip install -r requirements.txt

# 方式一：使用 build.bat（推荐，Nuitka 会自动处理编译器）
build.bat

# 方式二：手动执行 Nuitka（需要自行准备 C 编译器）
pip install "Nuitka[all]"
python -m nuitka --standalone --enable-plugin=pyside6 main.py
```

> 打包完成后可执行文件位于 `dist\ustxPlayer.dist\ustxPlayer.exe`，首次编译预计耗时 10-20 分钟，后续编译会被缓存加速。

## 使用提示

- 歌词推荐使用 **交错** 或 **独立** 格式；合并格式可能显示异常。
- 工程文件（`.uprj`）为**自包含 v3 格式**：直接内嵌解析后的 USTX 数据，可独立分发，无需额外携带 `.ustx` 文件。
- 工程文件（.uprj）中的 ustx 等文件路径**均可以为空**，故工程文件可做模板使用。
- **时间对齐提示**：播放与渲染的对齐依赖磁盘读取速度，请勿将工程/音频放在机械硬盘或慢速网络共享盘，否则可能出现音画错位。


## 相关项目

ustxPlayer 有以下附属项目：

- **[FFmpeg-for-ustxPlayer](https://github.com/rinflow05/FFmpeg-for-ustxPlayer)** — 为本项目精简定制的 FFmpeg 构建（内置 NVENC / QSV / AMF 硬件编码器等必要组件），体积仅约 **10 MB**、约为原版（约 97 MB）的 **1/10**。视频导出功能依赖该构建；发布时会被打包进软件。
- **[uPl-project-switch](https://github.com/rinflow05/uPl-project-switch)** — 工程转换工具，用于把旧版工程文件（v2）升级到新版自包含格式（v3），将在本版本 Release 中一并提供。

> 本项目另有实验性仓库 **[ustxPlayer-preview](https://github.com/rinflow05/ustxPlayer-preview)**，用于预览新特性原型，如需尝鲜可前往查看。


## 致谢

本项目基于 **[ustPlayer](https://github.com/SYEternalR/ustPlayer)** 二次开发，原项目由 **[SYEternal_R](https://github.com/SYEternalR)** 与 **[灰棱HiRenG](https://github.com/HiRenG1145)** 创建。
上游 ustPlayer 仓库现已迁移至 **[ustPlayerDevelop-OperateTeam/ustPlayer](https://github.com/ustPlayerDevelop-OperateTeam/ustPlayer)**，后续可前往新地址获取最新版本。

### 使用的资源与库

- [PySide6](https://www.qt.io/) — Qt for Python UI 框架
- [PySide6-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/tree/PySide6) — Fluent Design 组件库
- [loguru](https://github.com/Delgan/loguru) — 日志库
- [PyYAML](https://github.com/yaml/pyyaml) — USTX 工程文件解析
- [PyAV](https://github.com/PyAV-Org/PyAV) — 视频导出时的 RGBA→YUV420P 转换 + 音频时长探测
- [pywin32](https://github.com/mhammond/pywin32) — Windows API 绑定（无边框窗口）
- [FFmpeg](https://ffmpeg.org/) — 视频导出编码（独立二进制，非 Python 包）

## 协议与许可

本项目基于 [ustPlayer](https://github.com/SYEternalR/ustPlayer) 二次开发，与上游项目现均遵循 **GNU General Public License v3** 协议开源。使用前请务必阅读并同意协议内容：

- 程序目录下 [`LICENSE`](LICENSE)
- 或软件内入口：`其他 > 关于项目`

本工具在开发过程中使用了 AI 工具进行辅助开发。

---

感谢使用，玩得开心！
