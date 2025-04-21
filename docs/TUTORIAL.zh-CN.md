## 直播聊天 AI 代理 - 教程 (中文版)

本指南提供如何设置和使用直播聊天 AI 代理的详细说明，涵盖本地开发和服务器部署场景。

### 目录

*   [先决条件](#先决条件-1)
*   [后端服务器设置](#后端服务器设置-1)
    *   [1. 获取代码](#1-获取代码-1)
    *   [2. 导航到后端目录](#2-导航到后端目录-1)
    *   [3. 创建虚拟环境 (推荐)](#3-创建虚拟环境-推荐-1)
    *   [4. 安装依赖项](#4-安装依赖项-1)
    *   [5. 配置环境变量 (.env)](#5-配置环境变量-env-1)
    *   [6. 设置 SSL 证书 (HTTPS)](#6-设置-ssl-证书-https)
        *   [选项 A: 本地开发 (mkcert)](#选项-a-本地开发-mkcert)
        *   [选项 B: 服务器部署 (Let's Encrypt / Certbot)](#选项-b-服务器部署-lets-encrypt--certbot)
    *   [7. 验证 FFmpeg](#7-验证-ffmpeg-1)
    *   [8. 运行服务器](#8-运行服务器-1)
*   [前端用户脚本设置](#前端用户脚本设置-1)
    *   [1. 安装用户脚本管理器](#1-安装用户脚本管理器-1)
    *   [2. 安装用户脚本](#2-安装用户脚本-1)
    *   [3. 配置并验证 API 端点](#3-配置并验证-api-端点)
*   [使用方法](#使用方法-1)
    *   [找到控制面板](#找到控制面板-1)
    *   [理解控件](#理解控件-1)
    *   [启动和停止代理](#启动和停止代理-1)
    *   [监控](#监控-1)
*   [故障排除](#故障排除-1)

### 先决条件

开始之前，请确保您已具备：

1.  **网络浏览器:** 现代浏览器 (Chrome, Firefox, Edge)。
2.  **用户脚本管理器:** [Tampermonkey (油猴)](https://www.tampermonkey.net/) 或 [Violentmonkey (暴力猴)](https://violentmonkey.github.io/)。
3.  **Python:** 3.8+ 版本。通过 `python --version` 或 `python3 --version` 验证。
4.  **pip:** Python 包安装器。通过 `pip --version` 或 `pip3 --version` 验证。
5.  **FFmpeg:** 音频转换所需，尤其对于有道 STT。
    *   下载: [ffmpeg.org](https://ffmpeg.org/download.html)。
    *   确保 `ffmpeg` 在系统 PATH 中，或在 `.env` 中设置 `FFMPEG_PATH`。通过 `ffmpeg -version` 验证。
6.  **Git (可选):** 用于克隆仓库。
7.  **SSL 设置工具 (根据部署情况选择):**
    *   **本地开发用:** `mkcert`。用于创建*本地信任*的 SSL 证书。从 [mkcert GitHub](https://github.com/FiloSottile/mkcert#installation) 安装。通过 `mkcert -version` 验证。
    *   **服务器部署用:** `Certbot`。用于从 Let's Encrypt 获取免费、受信任的 SSL 证书。需要一个指向您服务器公网 IP 的**域名**，通常需要**服务器 root/sudo 权限**。端口 80 必须临时开放用于证书验证。按照您操作系统的官方指南安装 Certbot ([Certbot 指南](https://certbot.eff.org/))。
8.  **API 密钥和凭证:**
    *   **LLM API:** OpenAI 兼容的 API 密钥和基础 URL (**必需**)。
    *   **有道智云 (若使用有道 STT 则必需):** 从[有道智云网站](https://ai.youdao.com/)获取**实时语音转写 - 短语音版**的应用 ID (`YOUDAO_APP_KEY`) 和应用密钥 (`YOUDAO_APP_SECRET`)。确保您的账户有权访问此特定 API。
    *   **Cloudinary (视觉功能可选):** 从 [Cloudinary](https://cloudinary.com/) 获取 Cloud Name, API Key, API Secret。

**为何 HTTPS 至关重要:** 浏览器会阻止安全的 HTTPS 页面（如直播网站）与不安全的 HTTP 服务器通信（“混合内容阻止”）。因此，使用有效的 SSL 证书 (HTTPS) 运行后端对于代理正常工作**至关重要**。`mkcert` 用于本地测试 (`localhost`/`127.0.0.1`)，而 Let's Encrypt/Certbot 用于拥有域名的公共服务器。

### 后端服务器设置

#### 1. 获取代码

```bash
git clone https://github.com/your-username/live-stream-chat-ai-agent.git
# 或下载 ZIP 并解压
```

#### 2. 导航到后端目录

```bash
cd path/to/live-stream-chat-ai-agent/backend
```

#### 3. 创建虚拟环境 (推荐)

```bash
# 创建
python -m venv venv # 或 python3
# 激活
# Windows (cmd): venv\Scripts\activate.bat
# Windows (PS):  venv\Scripts\Activate.ps1
# macOS/Linux:   source venv/bin/activate
```
寻找 `(venv)` 前缀。

#### 4. 安装依赖项

```bash
# 确保 venv 已激活
pip install -r requirements.txt
```

#### 5. 配置环境变量 (.env)

1.  **复制示例文件:** `cp .env.example .env` (Linux/macOS) 或 `copy .env.example .env` (Windows)。
2.  **编辑 `.env`:** 使用文本编辑器打开 `.env` 并填写您的信息。请**特别注意**：
    *   `LLM_API_KEY`, `LLM_API_URL`, `LLM_API_MODEL` (**必需**)
    *   **STT 提供商设置:**
        *   `STT_PROVIDER`: 设置为 `youdao` (或 `both` 如果适用) 以使用有道短语音识别。
        *   `YOUDAO_APP_KEY`: 您的有道应用 ID。**(若 `STT_PROVIDER=youdao` 则必需)**
        *   `YOUDAO_APP_SECRET`: 您的有道应用密钥。**(若 `STT_PROVIDER=youdao` 则必需)**
        *   *(注意: 当 `STT_PROVIDER=youdao` 时，后端代码假定使用的是有道短语音识别 API)*
    *   **视觉设置 (可选):**
        *   `VISION_ENABLE`, `VISION_UPLOAD_PROVIDER`, `CLOUDINARY_...` 密钥 (如果需要)。
    *   **FFmpeg 路径:**
        *   `FFMPEG_PATH`: 仅当 `ffmpeg` 不在系统 PATH 中时设置。(例如 `C:/ffmpeg/bin/ffmpeg.exe` 或 `/usr/local/bin/ffmpeg`)。
    *   **服务器 SSL 设置 (路径在步骤 6 中配置):**
        *   `SERVER_ENABLE_SSL`: 设置为 `true` 启用 HTTPS (强烈推荐)。
        *   `SERVER_SSL_CERT_PATH`: 指向您的 SSL 证书文件 (`.pem`, `.crt`) 的路径。将在步骤 6 中设置。
        *   `SERVER_SSL_KEY_PATH`: 指向您的 SSL 私钥文件 (`.pem`, `.key`) 的路径。将在步骤 6 中设置。
        *   `SERVER_HOST`: 通常是 `0.0.0.0` 以监听所有网络接口。
        *   `SERVER_PORT`: 后端监听的端口 (例如 `8181`)。

#### 6. 设置 SSL 证书 (HTTPS)

根据您的设置（本地 vs 服务器）选择一个选项。如果 `SERVER_ENABLE_SSL=true`，您*必须*执行其中一个。

##### 选项 A: 本地开发 (mkcert)

用于在本地机器上通过 `localhost` 访问时进行测试。现代浏览器通常会在安全策略和证书验证方面对 `localhost` 进行特殊处理，这使得对于 `mkcert` 生成的证书，使用 `localhost` 比使用 `127.0.0.1` 更优选。

1.  **确保 `mkcert` 已安装** (见先决条件)。
2.  **安装本地 CA (运行一次):**
    ```bash
    mkcert -install
    ```
    (可能需要管理员/sudo 权限)。这会告知您的浏览器/操作系统信任 `mkcert` 生成的证书。
3.  **生成证书 (在 `backend` 目录中):**
    ```bash
    # 在 'backend' 目录下执行
    mkcert localhost
    ```
    这通常会在当前目录创建 `localhost.pem` (证书) 和 `localhost-key.pem` (密钥)。请核实生成的实际文件名。
4.  **更新 `.env` 路径:** 再次编辑您的 `.env` 文件。设置：
    *   `SERVER_SSL_CERT_PATH=./localhost.pem`
    *   `SERVER_SSL_KEY_PATH=./localhost-key.pem`
    *(使用确切创建的文件名。使用 `./` 这样的相对路径或提供绝对路径。确保这些与上一步生成的文件匹配)*

##### 选项 B: 服务器部署 (Let's Encrypt / Certbot)

当将后端部署到具有自己域名的公共服务器（例如 `myagent.mydomain.com`）时使用此选项。

1.  **先决条件:**
    *   一个**可公开访问的服务器** (VPS, 云主机等)。
    *   一个**域名** (例如 `myagent.mydomain.com`)，其 DNS 'A' 记录指向您服务器的公网 IP 地址。
    *   服务器上的 **Root 或 sudo 访问权限**。
    *   服务器上的**端口 80** 必须临时开放/可用，以供 Certbot 的 HTTP-01 验证方法（最常用）使用。可能需要调整防火墙。
    *   **Certbot 已安装** (见先决条件 - [Certbot 指南](https://certbot.eff.org/))。

2.  **停止现有的 Web 服务器 (如果占用 80 端口):** 如果您正在运行 Nginx、Apache 等，可能需要为 `standalone` 方法临时停止它：
    ```bash
    # Nginx 示例
    sudo systemctl stop nginx
    # Apache (Debian/Ubuntu) 示例
    sudo systemctl stop apache2
    # Apache (CentOS/Fedora) 示例
    sudo systemctl stop httpd
    ```

3.  **使用 Certbot 获取证书 (Standalone 模式):**
    将 `myagent.mydomain.com` 替换为您的实际域名/子域名。
    ```bash
    sudo certbot certonly --standalone -d myagent.mydomain.com --agree-tos --email your-email@example.com --no-eff-email
    ```
    *   `certonly`: 只获取证书，不自动配置到 web 服务器。
    *   `--standalone`: Certbot 在 80 端口上启动自己的临时 web 服务器进行验证。
    *   按照提示操作。如果成功，Certbot 会告知证书和密钥文件的保存位置。

4.  **定位证书文件:** 文件通常位于：
    *   证书: `/etc/letsencrypt/live/myagent.mydomain.com/fullchain.pem`
    *   私钥: `/etc/letsencrypt/live/myagent.mydomain.com/privkey.pem`
    *(从 Certbot 的输出中确认这些路径)*

5.  **设置文件权限 (重要!):** 运行 Python 服务器的进程需要读取这些文件的权限。`live` 目录通常权限设置严格。您可能需要：
    *   将运行 Python 脚本的用户添加到有权访问的组中（例如 Certbot 使用的组）。
    *   或者，谨慎地调整权限（安全性较低）。一种常见方法是使用 `setfacl` (如果可用)，或者通过 cron 作业定期将证书复制到可访问的位置（更复杂）。*请查阅 Certbot 文档或服务器管理最佳实践来管理权限。*

6.  **更新 `.env` 路径:** 再次编辑您的 `.env` 文件。设置：
    *   `SERVER_SSL_CERT_PATH=/etc/letsencrypt/live/myagent.mydomain.com/fullchain.pem`
    *   `SERVER_SSL_KEY_PATH=/etc/letsencrypt/live/myagent.mydomain.com/privkey.pem`
    *(使用 Certbot 提供的确切、完整的路径)*

7.  **重启原来的 Web 服务器 (如果已停止):**
    ```bash
    # Nginx 示例
    sudo systemctl start nginx
    ```

8.  **自动续订:** Certbot 通常会设置自动续订（常通过 systemd timer 或 cron job）。验证其是否正常工作：`sudo certbot renew --dry-run`。

#### 7. 验证 FFmpeg

在终端（激活 venv）运行 `ffmpeg -version`。如果出错，请仔细检查 `.env` 中的 `FFMPEG_PATH`。

#### 8. 运行服务器

确保 venv 已激活 (`(venv)` 前缀)。启动 Flask 服务器：

```bash
python server.py
```

*   如果 `SERVER_ENABLE_SSL=true`，它将在 `https://<SERVER_HOST>:<SERVER_PORT>` 上监听。
*   如果为 `false`，则在 `http://<SERVER_HOST>:<SERVER_PORT>` 上监听。

保持此终端窗口打开。按 `Ctrl+C` 停止。记下确切的 HTTPS 或 HTTP 地址，前端需要用到。

### 前端用户脚本设置

#### 1. 安装用户脚本管理器

如果尚未安装 Tampermonkey/Violentmonkey，请先安装。

#### 2. 安装用户脚本

*   **从 URL:** `https://github.com/bOOOOcG/Live_Stream_Chat_AI_Agent/raw/refs/heads/main/frontend/live-stream-chat-ai-agent.user.js`。管理器应提示安装。
*   **手动:** 从 `frontend/live-stream-chat-ai-agent.user.js` 复制代码，粘贴到管理器仪表板的新脚本中，保存。

#### 3. 配置并验证 API 端点

1.  转到 Tampermonkey/Violentmonkey 仪表板。确保 "Live Stream Chat AI Agent" 已启用。
2.  **关键步骤:** 编辑该脚本。找到靠近顶部的 `API_ENDPOINT`。
    ```javascript
    // ** 必须与您的后端服务器地址完全匹配 **
    // 示例 (本地, mkcert - 必须用 localhost!):
    // const API_ENDPOINT = 'https://localhost:8181/upload';
    // 示例 (服务器, Let's Encrypt):
    // const API_ENDPOINT = 'https://myagent.mydomain.com:8181/upload';
    // 示例 (HTTP, 不推荐):
    // const API_ENDPOINT = 'http://localhost:8181/upload'; // 或 http://特定IP:端口

    const API_ENDPOINT = '在此粘贴你的后端URL/upload'; // <-- 编辑此行
    ```
3.  **非常重要:** 将 `API_ENDPOINT` 的值设置为与您的后端服务器运行地址**完全匹配**：
    *   如果 `SERVER_ENABLE_SSL=true`，使用 `https://`。
    *   如果 `SERVER_ENABLE_SSL=false`，使用 `http://` (注意浏览器限制)。
    *   **如果在本地使用 `mkcert`，您必须使用 `https://localhost:PORT`**。不要使用 `127.0.0.1`，因为浏览器处理 `localhost` 的证书方式不同，且更可靠。
    *   如果在服务器上使用 `Certbot`/Let's Encrypt，使用 `https://yourdomain.com:PORT`。
    *   确保 `PORT` 与 `.env` 中的 `SERVER_PORT` 匹配。
    *   路径 `/upload` 通常应保持不变，除非您修改了 `server.py`。
4.  保存脚本。

### 使用方法

在后端运行且用户脚本配置好的情况下：

![Control Panel](panel_example.png)

#### 找到控制面板

1.  导航到一个支持的直播页面 (例如 `live.bilibili.com/12345`)。
2.  面板应出现 (通常在右上角，可拖动)。

#### 理解控件

*   **标题栏:** 拖动移动。
*   **总控开关:** 主开关。启用“开始/停止”。关闭时停止代理。
*   **发言许可:** 授权发送聊天消息。测试时保持关闭。
*   **静音:** 静音*本地*音频播放。
*   **音量:** 调整*本地*音频音量。
*   **开始/停止按钮:** 启动/停止代理处理。

#### 启动和停止代理

1.  确保后端服务器正在运行。
2.  转到直播页面。
3.  打开**总控开关**。
4.  按需设置**发言许可**。
5.  点击**开始**。
6.  点击**停止**或关闭**总控开关**以停用。

#### 监控

*   **浏览器控制台 (F12):** 查找 `AI Agent:` 日志 (前端)。检查网络错误 (CORS, Mixed Content - 混合内容, Failed fetch - 获取失败)。
*   **后端终端:** 来自 `server.py` 的详细日志 (请求、STT、LLM、错误)。

### 故障排除

*   **面板不出现:** 用户脚本是否启用？页面 URL 是否正确？控制台 (F12) 是否有错误？
*   **“开始”按钮禁用:** 打开“总控开关”。等待视频检测（查看控制台）。
*   **启动/运行时代理出错 (网络/连接问题):**
    *   **最常见:** 检查浏览器控制台 (F12) 的网络错误：`Failed to fetch` (获取失败), `TypeError: NetworkError` (类型错误：网络错误), `Mixed Content` (混合内容), `CORS policy` (CORS 策略)。
    *   **验证 `API_ENDPOINT`:** 再次/三次检查用户脚本中的 `API_ENDPOINT` 是否与**确切**的后端地址匹配 (`https://` vs `http://`, 域名/IP/localhost, 端口)。**关键是：如果在本地使用 `mkcert`，请确保您使用的是 `https://localhost:PORT` 而不是 `https://127.0.0.1:PORT`**。
    *   **SSL 问题 (HTTPS):**
        *   *本地 (mkcert):* `mkcert -install` 是否成功运行？`API_ENDPOINT` 是否正确设置为 `https://localhost:PORT`？如果 CA 不受信任或使用了错误的主机名，浏览器可能会显示证书警告。尝试在浏览器标签页中直接访问 `API_ENDPOINT` - 如果弹出安全例外提示，请接受（仅用于在 `localhost` 上进行本地测试）。
        *   *服务器 (Certbot):* 证书是否有效（未过期）？Python 进程是否能*读取*证书文件 (`/etc/letsencrypt/live/...`)？检查文件权限。Certbot 续订是否失败？服务器防火墙是否开放了 443 端口（或您自定义的 SSL 端口）？
    *   **后端未运行:** `python server.py` 进程是否仍在终端中活动？那里是否有错误？
    *   **防火墙:** 是否有防火墙（服务器或客户端）阻止了连接？
*   **后端错误 (检查终端):**
    *   **API 密钥:** `.env` 中 LLM 或有道的密钥无效/缺失。
    *   **有道 STT 错误:** App Key/Secret 不正确？超出配额？连接有道的网络问题？FFmpeg 转换失败？（检查 FFmpeg 错误）。
    *   **SSL 文件错误:** 后端找不到或无法读取 `.env` 中指定的证书/密钥。检查 `SERVER_SSL_CERT_PATH`、`SERVER_SSL_KEY_PATH` 和文件权限。
    *   **其他 Python 错误:** 阅读错误回溯信息 (traceback)。
*   **聊天消息未发送:** “发言许可”是否打开？后端日志是否显示生成了 `{msg}`？F12 控制台是否有错误（DOM 选择器可能需要更新）？聊天冷却？
*   **FFmpeg 错误:** 验证安装和 `FFMPEG_PATH`。尝试从终端手动运行 ffmpeg 命令。