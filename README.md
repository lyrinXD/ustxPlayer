<div align="center">

<img src="icon.png" height="90" width="90"/>

# ustxPlayer

`v26g30` · 基于 [ustPlayer](https://github.com/SYEternalR/ustPlayer) 二次开发的 USTX 工程可视化工具。

![GitHub Release](https://img.shields.io/github/v/release/lyrinXD/ustxPlayer?style=for-the-badge)
![GitHub All Releases](https://img.shields.io/github/downloads/lyrinXD/ustxPlayer/total?style=for-the-badge)
![GitHub Stars](https://img.shields.io/github/stars/lyrinXD/ustxPlayer?style=for-the-badge)

[配布视频](https://www.bilibili.com/video/BV1puMk61EgT "bilibili弹幕网") | [更新日志](UPDATELOG.md)

![软件截图](https://github.com/user-attachments/assets/81190099-3f1d-4700-ac68-9588f30c04cb)

</div>

> [!NOTE]
> 本项目是 ustPlayer 的二次开发版本，核心定位从 UST 转向 **USTX**，并围绕播放体验、样式系统、歌词支持等方面进行了大量改进。

## 主要特性

### USTX 工程支持
- 原生支持 OpenUtau 的 `.ustx` 工程文件（基于 YAML 解析），**无需手动尝试编码**。
- 旧版 `.ust` 用户可通过 [UtaFormatix](https://utaformatix.tk/) 等工具转换后使用。

### 逐字样式系统
- 在项目中为**每一个字**精确定义样式（颜色、背景色等）。
- 配套直观的样式编辑界面，支持批量编辑。

### 增强播放体验
- 支持**导入音频与ustx文件同步播放**，更直观的同时方便在剪辑软件中精确对轨。
- 播放控制：暂停 / 快进 / 快退 / 音量调节 / 倍速播放（快捷键详见软件内说明）。

### 多语言 LRC 歌词
- 支持 `.lrc` 文件的**交错**与**独立**多语言格式。
- 理论支持任意行数，推荐 1~3 行以获得最佳显示效果。

### 更多自定义
- 支持自定义界面**强调色**，适配深色模式。
- 可修改歌词/信息字体、信息颜色等。
- 可隐藏软件版权信息。


## 安装与运行

### 环境要求
- Windows 10/11
- Python 3.10+

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
- 工程文件（`.uplr`）采用全新格式，**不兼容旧版 ustPlayer 的 `.uplr` 文件**。新格式内嵌 USTX 内容，可独立分发，无需额外携带 `.ustx` 文件。
- 工程文件（.uplr）中的 ustx 等文件路径**可以为空**，故工程文件可做模板使用。
- 同时打开两个界面可能会出现异常（缓存文件被删除等）。


## 致谢

本项目基于 **[ustPlayer](https://github.com/SYEternalR/ustPlayer)** 二次开发，原项目由 **[SYEternal_R](https://github.com/SYEternalR)** 与 **[灰棱HiRenG](https://github.com/HiRenG1145)** 创建。

### 使用的资源与库

- [PySide6](https://www.qt.io/)
- [PySide6-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/tree/PySide6)
- [loguru](https://github.com/Delgan/loguru)
- [PyYAML](https://github.com/yaml/pyyaml)

## 协议与许可

本项目沿用原项目（ustPlayer）的使用协议，使用前请务必阅读并同意相关使用协议：

- 程序目录下 [`Terms.txt`](Terms.txt)
- 或软件内入口：`其他 > 关于软件 > 使用协议`

ustPlayer 原项目版权由 SYEternalR 所有。本项目（ustxPlayer）在 ustPlayer 基础上进行二次开发，授权给符合条件的用户免费使用。

本工具在开发过程中使用了 AI 工具进行辅助开发。

---

感谢使用，玩得开心！
