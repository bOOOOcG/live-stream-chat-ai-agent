# Live Stream Chat AI Agent - 教程 (中文)

本指南提供设置和使用 Live Stream Chat AI Agent 的详细说明。

## 目录

*   [准备工作](#准备工作)
*   [后端服务器设置](#后端服务器设置)
    *   [1. 获取代码](#1-获取代码)
    *   [2. 进入后端目录](#2-进入后端目录)
    *   [3. 创建虚拟环境 (推荐)](#3-创建虚拟环境-推荐)
    *   [4. 安装依赖](#4-安装依赖)
    *   [5. 配置环境变量 (.env)](#5-配置环境变量-env)
    *   [6. 验证 FFmpeg](#6-验证-ffmpeg)
    *   [7. 运行服务器](#7-运行服务器)
*   [前端用户脚本设置](#前端用户脚本设置)
    *   [1. 安装用户脚本管理器](#1-安装用户脚本管理器)
    *   [2. 安装用户脚本](#2-安装用户脚本)
    *   [3. 验证安装与 API 端点](#3-验证安装与-api-端点)
*   [使用方法](#使用方法)
    *   [找到控制面板](#找到控制面板)
    *   [理解控件](#理解控件)
    *   [启动和停止代理](#启动和停止代理)
    *   [监控运行状态](#监控运行状态)
*   [问题排查](#问题排查)

## 准备工作

在开始之前，请确保您已安装并配置好以下各项：

1.  **网页浏览器:** 一个现代浏览器，如 Google Chrome, Mozilla Firefox, 或 Microsoft Edge。
2.  **用户脚本管理器:** 为您的浏览器安装 [Tampermonkey (油猴)](https://www.tampermonkey.net/) 或 [Violentmonkey (暴力猴)](https://violentmonkey.github.io/) 扩展。
3.  **Python:** Python 3.8 或更高版本。从 [python.org](https://www.python.org/) 下载。在您的终端或命令提示符中运行 `python --version` 或 `python3 --version` 来验证安装。
4.  **pip:** Python 的包安装器。通常随 Python 一起安装。通过 `pip --version` 或 `pip3 --version` 验证。
5.  **FFmpeg:** 一个用于处理多媒体数据的命令行工具。如果使用有道 STT，转换音频时需要。
    *   从 [ffmpeg.org](https://ffmpeg.org/download.html) 下载。
    *   确保 `ffmpeg` 可执行文件位于您系统的 PATH 环境变量中，或者稍后在 `.env` 文件中提供完整路径。在终端运行 `ffmpeg -version` 进行验证。
6.  **Git (可选):** 用于克隆仓库。或者，您可以 以 ZIP 文件形式下载代码。
7.  **API 密钥和凭证:**
    *   **LLM API:** 您需要一个 OpenAI 兼容服务的 API 密钥和基础 URL（例如 OpenAI, Azure OpenAI, LM Studio, 带 API 服务的 Ollama）。**这是必需的。**
    *   **有道智云 (可选):** 如果您计划使用有道进行 STT（`STT_PROVIDER=youdao` 或 `both`），请从[有道智云官网](https://ai.youdao.com/)获取您的应用 ID 和应用密钥。
    *   **Cloudinary (可选):** 如果您计划启用视觉支持并使用 Cloudinary 上传（`VISION_ENABLE=true`, `VISION_UPLOAD_PROVIDER=cloudinary`），请从 [Cloudinary](https://cloudinary.com/) 获取您的 Cloud Name, API Key, 和 API Secret。

## 后端服务器设置

后端服务器处理数据并与 AI 模型交互。

### 1. 获取代码

使用 Git 克隆仓库：

```bash
git clone https://github.com/your-username/live-stream-chat-ai-agent.git
```

或者从 GitHub 下载项目 ZIP 文件并解压。

### 2. 进入后端目录

打开您的终端或命令提示符，并导航到克隆/解压的项目文件夹中的 `backend` 目录：

```bash
cd path/to/live-stream-chat-ai-agent/backend
```

### 3. 创建虚拟环境 (推荐)

强烈建议使用虚拟环境来隔离项目依赖：

```bash
# 创建虚拟环境 (如果 python 指向 python2，请使用 python3)
python -m venv venv

# 激活虚拟环境
# Windows (cmd.exe):
venv\Scripts\activate.bat
# Windows (PowerShell):
venv\Scripts\Activate.ps1
# macOS/Linux (bash/zsh):
source venv/bin/activate
```

您应该看到命令提示符行前面带有 `(venv)` 前缀。

### 4. 安装依赖

安装 `requirements.txt` 文件中列出的必需 Python 包：

```bash
# 确保虚拟环境已激活
pip install -r requirements.txt
```

### 5. 配置环境变量 (.env)

这是后端至关重要的步骤。

1.  **复制示例文件:** 在 `backend` 目录下，复制 `.env.example` 并将其重命名为 `.env`。
    ```bash
    # macOS/Linux
    cp .env.example .env
    # Windows
    copy .env.example .env
    ```
2.  **编辑 `.env`:** 使用文本编辑器打开 `.env` 文件，并根据您的 API 密钥和偏好填入值。**请仔细检查每个设置。** 特别注意：
    *   `LLM_API_KEY`, `LLM_API_URL` (**必需**)
    *   `LLM_API_MODEL`
    *   `STT_PROVIDER` 及对应的密钥 (`YOUDAO_...`) (如果需要)
    *   `VISION_ENABLE`, `VISION_UPLOAD_PROVIDER` 及对应的密钥 (`CLOUDINARY_...`) (如果需要)
    *   `FFMPEG_PATH` (如果 `ffmpeg` 不在系统 PATH 中)
    *   `SERVER_ENABLE_SSL` (确保前端 `API_ENDPOINT` 的协议头匹配)

### 6. 验证 FFmpeg

确保 FFmpeg 已正确安装且可访问。在终端运行 `ffmpeg -version` (如果 PATH 受影响，请确保虚拟环境已激活)。如果出现错误，请仔细检查您的安装和 `.env` 文件中的 `FFMPEG_PATH`。

### 7. 运行服务器

确保您的虚拟环境仍然处于激活状态（`(venv)` 前缀）。启动 Flask 服务器：

```bash
python server.py
```

您应该看到指示服务器正在运行的输出，包括地址（例如 `http://0.0.0.0:8181/`，如果启用了 SSL，则为 `https://...`）。在使用代理期间，请保持此终端窗口打开。按 `Ctrl+C` 停止服务器。

**注意:** 后端服务器地址 **必须**与前端用户脚本中的 `API_ENDPOINT` 常量匹配。

## 前端用户脚本设置

用户脚本在您的浏览器中运行，以与直播页面和后端交互。

### 1. 安装用户脚本管理器

如果尚未安装，请为您的浏览器安装 [Tampermonkey (油猴)](https://www.tampermonkey.net/) 或 [Violentmonkey (暴力猴)](https://violentmonkey.github.io/)。

### 2. 安装用户脚本

*   **从 URL 安装 (如果已托管):** 访问 GitHub 上的原始 `.user.js` 文件链接（例如 `https://github.com/your-username/live-stream-chat-ai-agent/raw/main/frontend/live-stream-chat-ai-agent.user.js`）。您的用户脚本管理器应会检测到并提示安装。
*   **手动安装:**
    1.  打开 Tampermonkey/Violentmonkey 仪表盘。
    2.  转到“实用工具” / “+” / “创建新脚本”选项卡。
    3.  复制 `frontend/live-stream-chat-ai-agent.user.js` 的全部内容。
    4.  将代码粘贴到仪表盘的编辑器中。
    5.  保存脚本。

### 3. 验证安装与 API 端点

1.  转到 Tampermonkey/Violentmonkey 仪表盘。找到 "Live Stream Chat AI Agent" 并确保它已启用。
2.  **非常重要:** 编辑该脚本。找到脚本顶部附近的 `API_ENDPOINT` 常量。
    ```javascript
    // 示例:
    const API_ENDPOINT = 'http://127.0.0.1:8181/upload'; // 确保这里与你的后端匹配
    ```
    验证该 URL（包括 `http://` 或 `https://` 及端口号）与您的后端服务器监听的地址完全匹配。如有必要，请修改并保存脚本。

## 使用方法

在后端运行、用户脚本安装并配置好的情况下：

![控制面板](docs/panel_example.png)

### 找到控制面板

1.  导航到支持的直播页面（例如 `live.bilibili.com/12345`）。
2.  控制面板应该会出现（通常在右上角，但可以拖动）。

### 理解控件

*   **面板标题:** 拖动以移动面板。
*   **控制开关 (主开关):** 启用“运行/停止”按钮。必须打开才能启动。运行时关闭此开关会停止代理。
*   **弹幕权限开关:** 授权代理向聊天区发送消息。测试时建议关闭。
*   **静音开关:** 静音*本地*音频播放（不影响 AI）。
*   **音量滑块:** 调整*本地*音频音量（不影响 AI）。
*   **运行/停止按钮:** 点击以启动/停止代理（录音、处理、可能发送弹幕）。按钮文本/颜色指示状态。

### 启动和停止代理

1.  确保后端服务器正在运行。
2.  前往直播页面。
3.  打开 **控制开关**。
4.  决定是否打开 **弹幕权限** 开关。
5.  单击 **开始运行** 按钮（按钮文本变为“停止运行”）。
6.  单击 **停止运行** 或关闭 **控制开关** 以停用代理。

### 监控运行状态

*   **浏览器控制台 (F12):** 查看 `AI Agent:` 开头的日志，了解前端状态/错误。
*   **后端终端:** 查看 `server.py` 输出的详细日志，了解请求处理、STT、LLM 交互和错误。

## 问题排查

*   **面板未出现:** 检查用户脚本管理器（是否启用？）、页面 URL 是否正确、浏览器控制台 (F12) 是否有错误。
*   **“开始运行”按钮被禁用:** 打开“控制开关”。等待视频元素被检测到（查看控制台日志）。
*   **代理启动/运行时出错:** *首先*检查后端终端是否有 API 密钥错误、连接问题。检查浏览器控制台是否有前端错误（音频初始化、网络发送失败）。验证 `API_ENDPOINT` 是否匹配（包括 HTTP/HTTPS！）。
*   **音频问题:** 确保直播流有声音。检查浏览器控制台是否有音频错误。
*   **弹幕消息未发送:** “弹幕权限”是否打开？检查后端日志（AI 是否生成了 `{msg}`？）。检查浏览器控制台（如果网站更改，DOM 元素选择器可能需要更新）。是否是弹幕冷却？
*   **后端错误:** 仔细阅读后端终端信息。检查 `.env` 中的值。检查服务器的网络连接。如果需要，增加 API 超时时间。
*   **FFmpeg 错误:** 验证安装路径和 `.env` 中的 `FFMPEG_PATH` 是否正确。
