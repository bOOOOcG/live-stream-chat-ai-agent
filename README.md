# Live Stream Chat AI Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE) <!-- Optional Badge -->

An AI-powered agent designed to watch live streams, understand the content (audio, chat, video), and participate in the chat automatically using a Large Language Model (LLM).

![Control Panel](docs/panel_example.png)

## Overview

This project consists of two main parts:

1.  **Frontend Userscript:** Runs in your browser (via Tampermonkey/Violentmonkey) on live stream pages. It captures audio, chat messages, and screenshots, displays a control panel, and sends/receives data from the backend.
2.  **Backend Server:** A Python Flask server that receives data from the userscript, performs Speech-to-Text (STT), optionally uploads screenshots, interacts with an LLM (like GPT models via an OpenAI-compatible API), manages conversation memory, and sends back generated chat messages or actions.

## Key Features

*   **Automated Chatting:** Sends AI-generated messages to the live stream chat.
*   **Multimodal Understanding:** Processes live audio, chat history, and screenshots (optional) for context.
*   **LLM Integration:** Leverages powerful LLMs for intelligent interaction and response generation.
*   **Configurable AI Personality:** Define the agent's behavior and personality through a system prompt.
*   **Per-Room Memory:** Maintains a "notepad" and conversation history specific to each stream room ID.
*   **Multiple STT Options:** Supports Whisper (via OpenAI API) and Youdao ASR.
*   **Vision Support (Optional):** Can upload screenshots to Cloudinary for analysis by vision-capable LLMs.
*   **User Control:** Provides an in-page panel to start/stop the agent, manage permissions, and control volume/mute (for user convenience, doesn't affect AI).

## Current & Future Platform Support

*   **Currently Supported:**
    *   Bilibili Live (`live.bilibili.com`)
*   **Planned Future Support:**
    *   YouTube Live
    *   Twitch
    *   Facebook Live
    *   Other popular platforms (contributions welcome!)

## Technologies Used

*   **Frontend:** JavaScript (ES6+), Web Audio API, MediaRecorder API, Canvas API, DOM Manipulation, Tampermonkey/Violentmonkey
*   **Backend:** Python 3, Flask, Requests, OpenAI Python Library, Pillow, Cloudinary Python SDK (optional), python-dotenv, Tiktoken
*   **AI:** Any OpenAI-compatible LLM API (e.g., GPT-4, GPT-4o, Claude via compatible endpoints, local models via LM Studio/Ollama), Youdao ASR API (optional), Whisper (optional)

## Requirements

*   **Browser:** A modern web browser like Chrome, Firefox, or Edge.
*   **Userscript Manager:** Tampermonkey or Violentmonkey browser extension.
*   **Backend Environment:**
    *   Python 3.8+
    *   `pip` (Python package installer)
    *   `ffmpeg` installed and accessible in your system's PATH (required for Youdao STT audio conversion).
    *   API Keys (depending on your configuration):
        *   LLM API Key & URL (OpenAI or compatible service) - **Required**
        *   Youdao App Key & Secret (if using Youdao STT)
        *   Cloudinary Credentials (if using Vision with Cloudinary upload)

## Quick Start

1.  **Setup Backend:** Clone the repository, install Python dependencies, configure your API keys in a `.env` file, and run the server. See the [**Backend Setup Guide**](docs/TUTORIAL.md#backend-server-setup).
2.  **Install Userscript:** Install Tampermonkey/Violentmonkey and then install the `live-stream-chat-ai-agent.user.js` script. See the [**Frontend Setup Guide**](docs/TUTORIAL.md#frontend-userscript-setup).
3.  **Usage:** Navigate to a supported live stream page, use the control panel to start the agent. See the [**Usage Guide**](docs/TUTORIAL.md#usage).

**➡️ For detailed instructions, please read the [Full Tutorial (TUTORIAL.md)](docs/TUTORIAL.md)**

## Project Structure

*   `/frontend`: Contains the Userscript code.
*   `/backend`: Contains the Python Flask server code and configuration examples.
*   `/docs`: Contains documentation files and images.

## Contributing

Contributions are welcome! Please read the [**Contributing Guide (CONTRIBUTING.md)**](docs/CONTRIBUTING.md) (to be created) for details on bug reports, feature requests, and pull requests.

## License

This project is licensed under the [MIT License](./LICENSE).

## Disclaimer

*   **Use Responsibly:** This tool automates chat interaction. Use it ethically and respect the terms of service of the streaming platforms and the rules of individual streamers. Avoid spamming or disruptive behavior.
*   **API Costs:** Using LLM APIs and potentially STT/Cloudinary services can incur costs. Monitor your usage and set limits if necessary.
*   **Terms of Service:** Using automated scripts might violate the Terms of Service of some platforms. Use at your own risk. The developers are not responsible for any consequences of using this script.
*   **AI Limitations:** The AI's understanding and responses are based on the data it receives (which can be imperfect due to STT errors, etc.) and the capabilities of the LLM. It might misunderstand context or generate inappropriate responses sometimes.
