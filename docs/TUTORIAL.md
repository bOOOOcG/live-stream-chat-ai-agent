## Live Stream Chat AI Agent - Tutorial (English Version)

This guide provides detailed instructions on how to set up and use the Live Stream Chat AI Agent, covering both local development and server deployment scenarios.

### Table of Contents

*   [Prerequisites](#prerequisites)
*   [Backend Server Setup](#backend-server-setup)
    *   [1. Get the Code](#1-get-the-code)
    *   [2. Navigate to Backend Directory](#2-navigate-to-backend-directory)
    *   [3. Create Virtual Environment (Recommended)](#3-create-virtual-environment-recommended)
    *   [4. Install Dependencies](#4-install-dependencies)
    *   [5. Configure Environment Variables (.env)](#5-configure-environment-variables-env)
    *   [6. Set Up SSL Certificate (HTTPS)](#6-set-up-ssl-certificate-https)
        *   [Option A: Local Development (mkcert)](#option-a-local-development-mkcert)
        *   [Option B: Server Deployment (Let's Encrypt / Certbot)](#option-b-server-deployment-lets-encrypt--certbot)
    *   [7. Verify FFmpeg](#7-verify-ffmpeg)
    *   [8. Run the Server](#8-run-the-server)
*   [Frontend Userscript Setup](#frontend-userscript-setup)
    *   [1. Install Userscript Manager](#1-install-userscript-manager)
    *   [2. Install the Userscript](#2-install-the-userscript)
    *   [3. Configure & Verify API Endpoint](#3-configure--verify-api-endpoint)
*   [Usage](#usage)
    *   [Finding the Control Panel](#finding-the-control-panel)
    *   [Understanding the Controls](#understanding-the-controls)
    *   [Starting and Stopping the Agent](#starting-and-stopping-the-agent)
    *   [Monitoring](#monitoring)
*   [Troubleshooting](#troubleshooting)

### Prerequisites

Before you begin, ensure you have the following:

1.  **Web Browser:** A modern browser (Chrome, Firefox, Edge).
2.  **Userscript Manager:** [Tampermonkey](https://www.tampermonkey.net/) or [Violentmonkey](https://violentmonkey.github.io/).
3.  **Python:** Version 3.8+. Verify with `python --version` or `python3 --version`.
4.  **pip:** Python package installer. Verify with `pip --version` or `pip3 --version`.
5.  **FFmpeg:** Required for audio conversion, especially for Youdao STT.
    *   Download: [ffmpeg.org](https://ffmpeg.org/download.html).
    *   Ensure `ffmpeg` is in PATH or set `FFMPEG_PATH` in `.env`. Verify with `ffmpeg -version`.
6.  **Git (Optional):** For cloning the repo.
7.  **SSL Setup Tools (Choose one based on deployment):**
    *   **For Local Development:** `mkcert`. Tool for creating *locally-trusted* SSL certs. Install from [mkcert GitHub](https://github.com/FiloSottile/mkcert#installation). Verify with `mkcert -version`.
    *   **For Server Deployment:** `Certbot`. Tool for obtaining free, trusted SSL certificates from Let's Encrypt. Requires a **domain name** pointing to your server's public IP and usually **root/sudo access**. Port 80 must be open temporarily for certificate validation. Install Certbot following official instructions for your OS ([Certbot Instructions](https://certbot.eff.org/)).
8.  **API Keys & Credentials:**
    *   **LLM API:** OpenAI-compatible API Key and Base URL (**Required**).
    *   **Youdao AI Cloud (Required if using Youdao STT):** Get Application Key (`YOUDAO_APP_KEY`) and Application Secret (`YOUDAO_APP_SECRET`) from [Youdao AI Cloud website](https://ai.youdao.com/) for the **Short Audio Recognition API** (实时语音转写 - 短语音版). Ensure your account has access to this specific API.
    *   **Cloudinary (Optional for Vision):** Cloud Name, API Key, API Secret from [Cloudinary](https://cloudinary.com/).

**Why HTTPS is Crucial:** Browsers block secure HTTPS pages (like live streams) from communicating with insecure HTTP servers ("Mixed Content Blocking"). Therefore, running the backend with a valid SSL certificate (HTTPS) is **essential** for the agent to function correctly. `mkcert` is for local testing (`localhost`/`127.0.0.1`), while Let's Encrypt/Certbot is for public servers with domain names.

### Backend Server Setup

#### 1. Get the Code

```bash
git clone https://github.com/your-username/live-stream-chat-ai-agent.git
# OR download and extract ZIP
```

#### 2. Navigate to Backend Directory

```bash
cd path/to/live-stream-chat-ai-agent/backend
```

#### 3. Create Virtual Environment (Recommended)

```bash
# Create
python -m venv venv # Or python3
# Activate
# Windows (cmd): venv\Scripts\activate.bat
# Windows (PS):  venv\Scripts\Activate.ps1
# macOS/Linux:   source venv/bin/activate
```
Look for `(venv)` prefix.

#### 4. Install Dependencies

```bash
# Ensure venv active
pip install -r requirements.txt
```

#### 5. Configure Environment Variables (.env)

1.  **Copy Example:** `cp .env.example .env` (Linux/macOS) or `copy .env.example .env` (Windows).
2.  **Edit `.env`:** Open `.env` in a text editor and fill in your details. Pay **close attention** to:
    *   `LLM_API_KEY`, `LLM_API_URL`, `LLM_API_MODEL` (**Required**)
    *   **STT Provider Settings:**
        *   `STT_PROVIDER`: Set to `youdao` (or `both` if applicable) to use Youdao Short Audio Recognition.
        *   `YOUDAO_APP_KEY`: Your Youdao Application Key. **(Required if `STT_PROVIDER=youdao`)**
        *   `YOUDAO_APP_SECRET`: Your Youdao Application Secret. **(Required if `STT_PROVIDER=youdao`)**
        *   *(Note: The backend code assumes usage of the Youdao Short Audio Recognition API when `STT_PROVIDER=youdao`)*
    *   **Vision Settings (Optional):**
        *   `VISION_ENABLE`, `VISION_UPLOAD_PROVIDER`, `CLOUDINARY_...` keys if needed.
    *   **FFmpeg Path:**
        *   `FFMPEG_PATH`: Only set if `ffmpeg` is not in your system PATH. (e.g., `C:/ffmpeg/bin/ffmpeg.exe` or `/usr/local/bin/ffmpeg`).
    *   **Server SSL Settings (Configure Paths in Step 6):**
        *   `SERVER_ENABLE_SSL`: Set to `true` to enable HTTPS (Highly Recommended).
        *   `SERVER_SSL_CERT_PATH`: Path to your SSL certificate file (`.pem`, `.crt`). Will be set in Step 6.
        *   `SERVER_SSL_KEY_PATH`: Path to your SSL private key file (`.pem`, `.key`). Will be set in Step 6.
        *   `SERVER_HOST`: Typically `0.0.0.0` to listen on all interfaces.
        *   `SERVER_PORT`: The port the backend will listen on (e.g., `8181`).

#### 6. Set Up SSL Certificate (HTTPS)

Choose the option matching your setup (local vs. server). You *must* do one of these if `SERVER_ENABLE_SSL=true`.

##### Option A: Local Development (mkcert)

Use this for testing on your local machine accessing via `localhost`. Modern browsers often treat `localhost` specially regarding security policies and certificate validation, making it preferable over `127.0.0.1` for `mkcert`-generated certificates.

1.  **Ensure `mkcert` is installed** (See Prerequisites).
2.  **Install Local CA (Run Once):**
    ```bash
    mkcert -install
    ```
    (May require admin/sudo privileges). This tells your browser/OS to trust certificates generated by `mkcert`.
3.  **Generate Certificate (in `backend` directory):**
    ```bash
    # From within the 'backend' directory
    mkcert localhost
    ```
    This typically creates `localhost.pem` (certificate) and `localhost-key.pem` (key) in the current directory. Verify the exact filenames generated.
4.  **Update `.env` Paths:** Edit your `.env` file again. Set:
    *   `SSL_CERT_PATH=./localhost.pem`
    *   `SSL_KEY_PATH=./localhost-key.pem`
    *(Use the exact filenames created. Use relative paths like `./` or provide absolute paths. Ensure these match the files generated in the previous step)*

##### Option B: Server Deployment (Let's Encrypt / Certbot)

Use this when deploying the backend to a public server with its own domain name (e.g., `myagent.mydomain.com`).

1.  **Prerequisites:**
    *   A **publicly accessible server** (VPS, cloud instance, etc.).
    *   A **domain name** (e.g., `myagent.mydomain.com`) with DNS 'A' record pointing to your server's public IP address.
    *   **Root or sudo access** on the server.
    *   **Port 80** must be temporarily open/available on your server for Certbot's HTTP-01 validation method (most common). Firewalls might need adjustment.
    *   **Certbot installed** (See Prerequisites - [Certbot Instructions](https://certbot.eff.org/)).

2.  **Stop Existing Webserver (If any on Port 80):** If you have Nginx, Apache, etc., running, you might need to stop it temporarily for the `standalone` method:
    ```bash
    # Example for Nginx
    sudo systemctl stop nginx
    # Example for Apache (Debian/Ubuntu)
    sudo systemctl stop apache2
    # Example for Apache (CentOS/Fedora)
    sudo systemctl stop httpd
    ```

3.  **Obtain Certificate using Certbot (Standalone):**
    Replace `myagent.mydomain.com` with your actual domain/subdomain.
    ```bash
    sudo certbot certonly --standalone -d myagent.mydomain.com --agree-tos --email your-email@example.com --no-eff-email
    ```
    *   `certonly`: Get the cert but don't install it in a webserver config.
    *   `--standalone`: Certbot spins up its own temporary webserver on port 80 for validation.
    *   Follow the prompts. If successful, Certbot will tell you where the certificate and key files are saved.

4.  **Locate Certificate Files:** The files are typically located at:
    *   Certificate: `/etc/letsencrypt/live/myagent.mydomain.com/fullchain.pem`
    *   Private Key: `/etc/letsencrypt/live/myagent.mydomain.com/privkey.pem`
    *(Verify these paths from the Certbot output)*

5.  **Set File Permissions (Important!):** The Python server process needs permission to read these files. The `live` directory usually has restrictive permissions. You might need to:
    *   Add the user running the Python script to a group that has access (e.g., the group Certbot uses).
    *   Or, carefully adjust permissions (less recommended for security). A common approach is to use `setfacl` if available, or copy the certs periodically to an accessible location with a cron job (more complex). *Check Certbot documentation or server admin best practices for managing permissions.*

6.  **Update `.env` Paths:** Edit your `.env` file again. Set:
    *   `SERVER_SSL_CERT_PATH=/etc/letsencrypt/live/myagent.mydomain.com/fullchain.pem`
    *   `SERVER_SSL_KEY_PATH=/etc/letsencrypt/live/myagent.mydomain.com/privkey.pem`
    *(Use the exact, full paths provided by Certbot)*

7.  **Restart Original Webserver (If stopped):**
    ```bash
    # Example for Nginx
    sudo systemctl start nginx
    ```

8.  **Auto-Renewal:** Certbot usually sets up automatic renewal (often via a systemd timer or cron job). Verify this is working: `sudo certbot renew --dry-run`.

#### 7. Verify FFmpeg

Run `ffmpeg -version` in terminal (venv active). Double-check `FFMPEG_PATH` in `.env` if errors occur.

#### 8. Run the Server

Ensure venv active (`(venv)` prefix). Start the Flask server:

```bash
python server.py
```

*   If `SERVER_ENABLE_SSL=true`, it listens on `https://<SERVER_HOST>:<SERVER_PORT>`.
*   If `false`, it listens on `http://<SERVER_HOST>:<SERVER_PORT>`.

Keep this terminal open. `Ctrl+C` to stop. Note the exact HTTPS or HTTP address; you'll need it for the frontend.

### Frontend Userscript Setup

#### 1. Install Userscript Manager

Install Tampermonkey/Violentmonkey if you haven't.

#### 2. Install the Userscript

*   **From URL:** `https://github.com/bOOOOcG/Live_Stream_Chat_AI_Agent/raw/refs/heads/main/frontend/live-stream-chat-ai-agent.user.js`. Manager should prompt install.
*   **Manual:** Copy code from `frontend/live-stream-chat-ai-agent.user.js`, paste into new script in manager dashboard, save.

#### 3. Configure & Verify API Endpoint

1.  Go to Tampermonkey/Violentmonkey dashboard. Ensure "Live Stream Chat AI Agent" is enabled.
2.  **CRITICAL:** Edit the script. Find `API_ENDPOINT` near the top.
    ```javascript
    // ** MUST MATCH YOUR BACKEND SERVER ADDRESS EXACTLY **
    // Example (Local, mkcert - Use localhost!):
    // const API_ENDPOINT = 'https://localhost:8181/upload';
    // Example (Server, Let's Encrypt):
    // const API_ENDPOINT = 'https://myagent.mydomain.com:8181/upload';
    // Example (HTTP, Not Recommended):
    // const API_ENDPOINT = 'http://localhost:8181/upload'; // Or http://specific-ip:port

    const API_ENDPOINT = 'PASTE_YOUR_BACKEND_URL_HERE/upload'; // <-- EDIT THIS LINE
    ```
3.  **VERY IMPORTANT:** Set the `API_ENDPOINT` value to EXACTLY match the address where your backend server is running:
    *   Use `https://` if `SERVER_ENABLE_SSL=true`.
    *   Use `http://` if `SERVER_ENABLE_SSL=false` (Remember browser limitations).
    *   **If using `mkcert` locally, you MUST use `https://localhost:PORT`**. Do not use `127.0.0.1` as browsers handle certificates for `localhost` differently and more reliably.
    *   If using `Certbot`/Let's Encrypt on a server, use `https://yourdomain.com:PORT`.
    *   Ensure the `PORT` matches `SERVER_PORT` in `.env`.
    *   The path `/upload` should generally be kept unless you modify `server.py`.
4.  Save the script.

### Usage

With backend running and userscript configured:

![Control Panel](panel_example.png)

#### Finding the Control Panel

1.  Navigate to a supported live stream page (e.g., `live.bilibili.com/12345`).
2.  Panel appears (usually top-right, draggable).

#### Understanding the Controls

*   **Header:** Drag to move.
*   **Control Switch:** Master On/Off. Enables Start/Stop. Stops agent if turned OFF.
*   **Chat Permission:** Authorizes sending chat messages. Keep OFF for testing.
*   **Mute:** Mutes *local* audio playback.
*   **Volume:** Adjusts *local* audio volume.
*   **Start/Stop Button:** Starts/stops agent processing.

#### Starting and Stopping the Agent

1.  Ensure backend server running.
2.  Go to live stream page.
3.  Turn **Control Switch** ON.
4.  Set **Chat Permission** as needed.
5.  Click **Start**.
6.  Click **Stop** or turn **Control Switch** OFF to deactivate.

#### Monitoring

*   **Browser Console (F12):** Look for `AI Agent:` logs (frontend). Check for Network errors (CORS, Mixed Content, Failed fetch).
*   **Backend Terminal:** Detailed logs from `server.py` (requests, STT, LLM, errors).

### Troubleshooting

*   **Panel Doesn't Appear:** Userscript enabled? Correct page URL? Console (F12) errors?
*   **"Start" Disabled:** Turn "Control Switch" ON. Wait for video detection (console).
*   **Agent Errors on Start/Run (Network/Connection):**
    *   **MOST COMMON:** Check Browser Console (F12) for Network errors: `Failed to fetch`, `TypeError: NetworkError`, `Mixed Content`, `CORS policy`.
    *   **VERIFY `API_ENDPOINT`:** Double/triple-check the `API_ENDPOINT` in the userscript matches the **exact** backend address (`https://` vs `http://`, domain/IP/localhost, port). **Crucially, if using `mkcert` locally, ensure you are using `https://localhost:PORT` and NOT `https://127.0.0.1:PORT`**.
    *   **SSL Issues (HTTPS):**
        *   *Local (mkcert):* Did `mkcert -install` run successfully? Is the `API_ENDPOINT` correctly set to `https://localhost:PORT`? Browser might show certificate warnings if the CA isn't trusted or if using the wrong hostname. Try accessing the `API_ENDPOINT` directly in a browser tab - accept security exception if prompted (for local testing only on `localhost`).
        *   *Server (Certbot):* Is the certificate valid (not expired)? Can the Python process *read* the certificate files (`/etc/letsencrypt/live/...`)? Check file permissions. Did Certbot renewal fail? Is port 443 (or your custom SSL port) open on the server firewall?
    *   **Backend Not Running:** Is the `python server.py` process still active in its terminal? Any errors there?
    *   **Firewall:** Is a firewall blocking the connection (either on server or client)?
*   **Backend Errors (Check Terminal):**
    *   **API Keys:** Invalid/missing LLM or Youdao keys in `.env`.
    *   **Youdao STT Errors:** Incorrect App Key/Secret? Exceeded quota? Network issue reaching Youdao? FFmpeg conversion failed? (Check FFmpeg errors).
    *   **SSL File Errors:** Backend cannot find/read certificate/key specified in `.env`. Check `SERVER_SSL_CERT_PATH`, `SERVER_SSL_KEY_PATH` and file permissions.
    *   **Other Python Errors:** Read the traceback.
*   **Chat Messages Not Sending:** "Chat Permission" ON? Backend logs show `{msg}` generated? F12 console errors (DOM selectors may need update)? Chat cooldown?
*   **FFmpeg Errors:** Verify install & `FFMPEG_PATH`. Try running ffmpeg command manually from terminal.
