# Live Stream Chat AI Agent

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](./LICENSE)

| **ENGLISH** | [ 中文 ](README.zh-CN.md) | [ Official Website ](https://lsca.enou.org/) |

An AI-powered agent designed to watch live streams, understand the content (audio, chat, video), and participate in the chat automatically using a Large Language Model (LLM).

![Control Panel](docs/panel_example.png)

## Overview

This project enables an AI to act as a viewer in live streams. It captures stream data, sends it to a backend for processing by an LLM (like GPT models), and uses the AI's response to interact with the chat.

It consists of two main parts:

1.  **Frontend Userscript:** Runs in your browser (via Tampermonkey/Violentmonkey) on live stream pages. It captures audio, chat messages, and screenshots, displays a control panel, and communicates with the backend.
2.  **Backend Server:** A modular Python Flask server with independent service layers: State Management Service, External APIs Service, and LLM Service. It receives data, performs Speech-to-Text (STT), optionally uploads screenshots, interacts with an LLM, manages conversation memory, and sends back generated chat messages.

## Key Features

*   **Automated Chat Interaction:** Sends AI-generated messages based on stream content.
*   **Multimodal Context:** Processes live audio, chat history, and screenshots (optional).
*   **LLM Integration:** Leverages powerful LLMs (OpenAI-compatible APIs).
*   **Customizable AI Persona:** Define the agent's behavior via a system prompt.
*   **Persistent Memory:** Maintains per-stream conversation history and a notepad.
*   **Multiple STT Options:** Supports Whisper (via LLM API) and Youdao ASR.
*   **Vision Support (Optional):** Uploads screenshots to Cloudinary for analysis by vision LLMs.
*   **User Control Panel:** In-page UI to Start/Stop, manage chat permissions, and adjust local volume/mute.

## Platform Support

*   **Currently Supported:**
    *   YouTube Live (`youtube.com`)
    *   Twitch (`twitch.tv`)
    *   Bilibili Live (`live.bilibili.com`)
*   **Planned Future Support:**
    *   Huya.com ([huya.com](https://www.huya.com/))
    *   Douyu.com ([douyu.com](https://douyu.com/))
    *   Other popular platforms (contributions welcome!)

## Technologies

*   **Frontend:** JavaScript (ES6+), Web Audio API, MediaRecorder API, Canvas API, DOM Manipulation
*   **Backend:** Python 3, Flask, Flask-CORS, Requests, OpenAI Python Library, Pillow, Cloudinary Python SDK (optional), python-dotenv, Tiktoken
*   **AI Services:** OpenAI-compatible LLM API, Youdao ASR API (optional), Whisper (optional)
*   **Userscript Manager:** Tampermonkey or Violentmonkey

## Requirements

*   Modern Web Browser (Chrome, Firefox, Edge)
*   Tampermonkey or Violentmonkey browser extension
*   Python 3.8+
*   `pip` package installer
*   `ffmpeg` installed and in system PATH (or path specified in `.env`)
*   API Keys:
    *   LLM API Key & URL (**Required**)
    *   Youdao App Key & Secret (If using Youdao STT)
    *   Cloudinary Credentials (If using Cloudinary vision uploads)

## Quick Start

1.  **Backend Setup:** Clone repo, install Python dependencies (`pip install -r requirements.txt`), configure API keys in `.env` (copy from `.env.example`), run `python src/app.py`. (See [**Backend Setup**](docs/TUTORIAL.md#backend-server-setup))
2.  **Frontend Setup:** Install Tampermonkey/Violentmonkey, install the `.user.js` script, ensure `INFERENCE_SERVICE_URL` and `INFERENCE_SERVICE_API_KEY` in the script match your backend configuration. (See [**Frontend Setup**](docs/TUTORIAL.md#frontend-userscript-setup))
3.  **Usage:** Go to a supported live stream, use the control panel to start the agent. (See [**Usage Guide**](docs/TUTORIAL.md#usage))

**➡️ For detailed steps, please read the [Full Tutorial (TUTORIAL.md)](docs/TUTORIAL.md)**

## Project Structure
```
.
├── backend/                # Server code and related files
│   ├── src/               # Source code directory
│   │   ├── app.py         # Flask application main entry
│   │   ├── services/      # Service layer
│   │   │   ├── external_apis.py  # External API integration service
│   │   │   ├── llm_service.py    # LLM processing service
│   │   │   └── state_service.py  # State management service
│   │   └── utils/         # Utility modules
│   │       └── config.py  # Configuration management
│   ├── memory/            # Persistent memory storage
│   ├── prompts/           # System prompt files
│   ├── requirements.txt   # Python dependencies
│   └── .env.example       # Environment configuration example
├── frontend/              # Userscript code
│   └── live-stream-chat-ai-agent.user.js
├── docs/                  # Documentation and images
├── tools/                 # Helper tools
├── README.md              # This file (English)
├── README.zh-CN.md        # Chinese Readme
├── LICENSE                # AGPL-3.0 License file
└── .gitignore             # Git ignore rules
```

## Contributing

Contributions are welcome! Please refer to the [Contributing Guide](CONTRIBUTING.md) (to be created) for more details.

## License

This project is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). See the [LICENSE](./LICENSE) file for the full text.

## Disclaimer

*   **Use Responsibly:** Automating chat requires ethical considerations. Respect platform ToS and streamer rules. Avoid spamming.
*   **API Costs:** LLM, STT, and Cloudinary usage may incur costs. Monitor your usage.
*   **Terms of Service:** Using automated scripts may violate platform ToS. Use at your own risk.
*   **AI Limitations:** AI understanding depends on input quality (STT errors) and LLM capabilities. Misinterpretations or inappropriate responses are possible.

