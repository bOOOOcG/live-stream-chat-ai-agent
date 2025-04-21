# Live Stream Chat AI Agent - Tutorial

This guide provides detailed instructions on how to set up and use the Live Stream Chat AI Agent.

## Table of Contents

*   [Prerequisites](#prerequisites)
*   [Backend Server Setup](#backend-server-setup)
    *   [1. Get the Code](#1-get-the-code)
    *   [2. Navigate to Backend Directory](#2-navigate-to-backend-directory)
    *   [3. Create Virtual Environment (Recommended)](#3-create-virtual-environment-recommended)
    *   [4. Install Dependencies](#4-install-dependencies)
    *   [5. Configure Environment Variables (.env)](#5-configure-environment-variables-env)
    *   [6. Verify FFmpeg](#6-verify-ffmpeg)
    *   [7. Run the Server](#7-run-the-server)
*   [Frontend Userscript Setup](#frontend-userscript-setup)
    *   [1. Install Userscript Manager](#1-install-userscript-manager)
    *   [2. Install the Userscript](#2-install-the-userscript)
    *   [3. Verify Installation & API Endpoint](#3-verify-installation--api-endpoint)
*   [Usage](#usage)
    *   [Finding the Control Panel](#finding-the-control-panel)
    *   [Understanding the Controls](#understanding-the-controls)
    *   [Starting and Stopping the Agent](#starting-and-stopping-the-agent)
    *   [Monitoring](#monitoring)
*   [Troubleshooting](#troubleshooting)

## Prerequisites

Before you begin, ensure you have the following installed and configured:

1.  **Web Browser:** A modern browser like Google Chrome, Mozilla Firefox, or Microsoft Edge.
2.  **Userscript Manager:** Install either [Tampermonkey](https://www.tampermonkey.net/) or [Violentmonkey](https://violentmonkey.github.io/) extension for your browser.
3.  **Python:** Python version 3.8 or higher. Download from [python.org](https://www.python.org/). Verify installation by running `python --version` or `python3 --version` in your terminal/command prompt.
4.  **pip:** Python's package installer. Usually comes with Python. Verify with `pip --version` or `pip3 --version`.
5.  **FFmpeg:** A command-line tool for handling multimedia data. Required for converting audio for Youdao STT (if used).
    *   Download from [ffmpeg.org](https://ffmpeg.org/download.html).
    *   Ensure the `ffmpeg` executable is in your system's PATH environmental variable, or provide the full path in the `.env` file later. Verify by running `ffmpeg -version` in your terminal.
6.  **Git (Optional):** Useful for cloning the repository. Alternatively, you can download the code as a ZIP file.
7.  **API Keys & Credentials:**
    *   **LLM API:** You need an API key and the base URL for an OpenAI-compatible service (e.g., OpenAI, Azure OpenAI, LM Studio, Ollama with API serving). **This is required.**
    *   **Youdao AI Cloud (Optional):** If you plan to use Youdao for STT (`STT_PROVIDER=youdao` or `both`), get your Application Key and Secret from the [Youdao AI Cloud website](https://ai.youdao.com/).
    *   **Cloudinary (Optional):** If you plan to enable Vision support with Cloudinary uploads (`VISION_ENABLE=true`, `VISION_UPLOAD_PROVIDER=cloudinary`), get your Cloud Name, API Key, and API Secret from [Cloudinary](https://cloudinary.com/).

## Backend Server Setup

The backend server processes the data and interacts with the AI models.

### 1. Get the Code

Clone the repository using Git:

```bash
git clone https://github.com/your-username/live-stream-chat-ai-agent.git
```

Or download the project ZIP file from GitHub and extract it.

### 2. Navigate to Backend Directory

Open your terminal or command prompt and navigate into the `backend` directory within the cloned/extracted project folder:

```bash
cd path/to/live-stream-chat-ai-agent/backend
```

### 3. Create Virtual Environment (Recommended)

It's highly recommended to use a virtual environment to isolate project dependencies:

```bash
# Create the virtual environment (use python3 if python maps to python2)
python -m venv venv

# Activate the virtual environment
# On Windows (cmd.exe):
venv\Scripts\activate.bat
# On Windows (PowerShell):
venv\Scripts\Activate.ps1
# On macOS/Linux (bash/zsh):
source venv/bin/activate
```

You should see `(venv)` prefixing your command prompt line.

### 4. Install Dependencies

Install the required Python packages listed in `requirements.txt`:

```bash
# Ensure your virtual environment is active
pip install -r requirements.txt
```

### 5. Configure Environment Variables (.env)

This is a crucial step for the backend.

1.  **Copy the Example File:** Make a copy of `.env.example` and rename it to `.env` in the `backend` directory.
    ```bash
    # On macOS/Linux
    cp .env.example .env
    # On Windows
    copy .env.example .env
    ```
2.  **Edit `.env`:** Open the `.env` file with a text editor and fill in the values based on your API keys and preferences. **Carefully review each setting.** Pay close attention to:
    *   `LLM_API_KEY`, `LLM_API_URL` (**Required**)
    *   `LLM_API_MODEL`
    *   `STT_PROVIDER` and corresponding keys (`YOUDAO_...`) if needed.
    *   `VISION_ENABLE`, `VISION_UPLOAD_PROVIDER`, and corresponding keys (`CLOUDINARY_...`) if needed.
    *   `FFMPEG_PATH` (if `ffmpeg` is not in your system PATH).
    *   `SERVER_ENABLE_SSL` (ensure frontend `API_ENDPOINT` protocol matches).

### 6. Verify FFmpeg

Make sure FFmpeg is correctly installed and accessible. Run `ffmpeg -version` in your terminal (with the virtual environment active if it affects PATH). If you get an error, double-check your installation and the `FFMPEG_PATH` in `.env`.

### 7. Run the Server

Ensure your virtual environment is still active (`(venv)` prefix). Start the Flask server:

```bash
python server.py
```

You should see output indicating the server is running, including the address (e.g., `http://0.0.0.0:8181/` or `https://...`). Keep this terminal window open. Press `Ctrl+C` to stop.

**Note:** The backend server address **must** match the `API_ENDPOINT` constant in the frontend userscript.

## Frontend Userscript Setup

The userscript runs in your browser to interact with the live stream page and the backend.

### 1. Install Userscript Manager

Install [Tampermonkey](https://www.tampermonkey.net/) or [Violentmonkey](https://violentmonkey.github.io/) for your browser if you haven't already.

### 2. Install the Userscript

*   **From URL (if hosted):** Navigate to the raw `.user.js` file link on GitHub (e.g., `https://github.com/your-username/live-stream-chat-ai-agent/raw/main/frontend/live-stream-chat-ai-agent.user.js`). Your userscript manager should detect and prompt for installation.
*   **Manual Installation:**
    1.  Open Tampermonkey/Violentmonkey dashboard.
    2.  Go to the "Utilities" / "+" / "Create a new script" tab.
    3.  Copy the entire content of `frontend/live-stream-chat-ai-agent.user.js`.
    4.  Paste the code into the editor in the dashboard.
    5.  Save the script.

### 3. Verify Installation & API Endpoint

1.  Go to the Tampermonkey/Violentmonkey dashboard. Find "Live Stream Chat AI Agent" and ensure it's enabled.
2.  **VERY IMPORTANT:** Edit the script. Locate the `API_ENDPOINT` constant near the top.
    ```javascript
    // Example:
    const API_ENDPOINT = 'http://127.0.0.1:8181/upload'; // Ensure this matches your backend
    ```
    Verify the URL (including `http://` or `https://` and the port) exactly matches where your backend server is listening. Change it if necessary and save the script.

## Usage

With the backend running and the userscript installed and configured:

![Control Panel](docs/panel_example.png)

### Finding the Control Panel

1.  Navigate to a supported live stream page (e.g., `live.bilibili.com/12345`).
2.  The control panel should appear (usually top-right, but draggable).

### Understanding the Controls

*   **Panel Header:** Drag to move the panel.
*   **Control Switch (Main):** Enables the Start/Stop button. Must be ON to start. Stops agent if turned OFF while running.
*   **Chat Permission Switch:** Authorizes the agent to send messages to the chat. Keep OFF for testing.
*   **Mute Switch:** Mutes *local* audio playback (doesn't affect AI).
*   **Volume Slider:** Adjusts *local* audio volume (doesn't affect AI).
*   **Start/Stop Button:** Click to start/stop the agent (recording, processing, potential chatting). Button text/color indicates status.

### Starting and Stopping the Agent

1.  Ensure the backend server is running.
2.  Go to the live stream page.
3.  Turn the **Control Switch** ON.
4.  Decide if **Chat Permission** should be ON or OFF.
5.  Click the **Start** button (changes to "Stop").
6.  Click **Stop** or turn **Control Switch** OFF to deactivate.

### Monitoring

*   **Browser Console (F12):** Look for `AI Agent:` logs for frontend status/errors.
*   **Backend Terminal:** Check detailed logs from `server.py` for request processing, STT, LLM interaction, and errors.

## Troubleshooting

*   **Panel Doesn't Appear:** Check userscript manager (enabled?), correct page URL, browser console (F12) for errors.
*   **"Start" Button Disabled:** Turn ON "Control Switch". Wait for video element detection (check console logs).
*   **Agent Errors on Start/Run:** Check backend terminal *first* for API key errors, connection issues. Check browser console for frontend errors (audio init, network send failure). Verify `API_ENDPOINT` match (HTTP/HTTPS too!).
*   **Audio Issues:** Ensure stream has audio. Check browser console for audio errors.
*   **Chat Messages Not Sending:** Is "Chat Permission" ON? Check backend logs (did AI generate `{msg}`?). Check browser console (DOM element selectors might need update if site changed). Chat cooldown?
*   **Backend Errors:** Read backend terminal carefully. Check `.env` values. Check network connectivity from server. Increase API timeouts if needed.
*   **FFmpeg Errors:** Verify installation and `FFMPEG_PATH` in `.env`.
