# Live Stream Chat AI Agent (直播聊天室 AI 智能代理)

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](./LICENSE)
[![Discord](https://img.shields.io/discord/1334400729031467028?color=7289da&label=Discord&logo=discord&logoColor=white)](https://discord.gg/ndWj3xnCEZ)

| [ ENGLISH ](README.md) | **中文** | [ 官方网站 ](https://lsca.enou.org/) | [ Discord 社区 ](https://discord.gg/ndWj3xnCEZ) |

一个由 AI 驱动的代理程序，设计用于观看直播、理解内容（音频、弹幕、画面），并使用大型语言模型 (LLM) 自动参与弹幕互动。

![控制面板](docs/panel_example.png)

## 项目概览

本项目让 AI 能够像观众一样参与直播互动。它会捕获直播数据，将其发送到后端供 LLM（如 GPT 模型）处理，并利用 AI 的响应来发送弹幕。

主要包含两部分：

1.  **前端用户脚本:** 通过油猴 (Tampermonkey) 或暴力猴 (Violentmonkey) 在浏览器中的直播页面运行。负责捕获音频、弹幕、截图，显示控制面板，并与后端通信。
2.  **后端服务器:** 采用模块化架构的 Python Flask 服务器，包含独立的服务层：状态管理服务、外部 API 服务、LLM 服务。负责接收数据、执行语音转文本 (STT)、可选上传截图、与 LLM 交互、管理对话记忆，并发送回 AI 生成的弹幕消息。

## 主要功能

*   **自动化弹幕互动:** 根据直播内容发送 AI 生成的消息。
*   **多模态上下文理解:** 处理实时音频、弹幕历史和截图（可选）。
*   **LLM 集成:** 利用强大的 LLM（OpenAI 兼容 API）。
*   **可定制 AI 人格:** 通过系统提示词 (System Prompt) 定义代理行为。
*   **持久化记忆:** 维护分直播间的对话历史和记事本。
*   **多种 STT 选项:** 支持 Whisper（通过 LLM API）和有道智云 ASR。
*   **视觉支持 (可选):** 上传截图到 Cloudinary 供视觉 LLM 分析。
*   **用户控制面板:** 页面内 UI，用于启动/停止、管理弹幕权限、调整本地音量/静音。

## 平台支持

*   **当前支持:**
    *   Bilibili 直播 (`live.bilibili.com`)
    *   YouTube Live (`youtube.com`)
    *   Twitch (`twitch.tv`)
*   **计划未来支持:**
    *   虎牙直播 ([huya.com](https://www.huya.com/))
    *   斗鱼直播 ([douyu.com](https://douyu.com/))
    *   其他流行平台 (欢迎贡献!)

## 技术栈

*   **前端:** JavaScript (ES6+), Web Audio API, MediaRecorder API, Canvas API, DOM 操作
*   **后端:** Python 3, Flask, Flask-CORS, Requests, OpenAI Python Library, Pillow, Cloudinary Python SDK (可选), python-dotenv, Tiktoken
*   **AI 服务:** OpenAI 兼容的 LLM API, 有道智云 ASR API (可选), Whisper (可选)
*   **用户脚本管理器:** Tampermonkey 或 Violentmonkey

## 系统需求

*   现代网页浏览器 (Chrome, Firefox, Edge)
*   Tampermonkey 或 Violentmonkey 浏览器扩展
*   Python 3.8+
*   `pip` 包安装器
*   `ffmpeg` 已安装并在系统 PATH 中 (或在 `.env` 中指定路径)
*   API 密钥:
    *   LLM API 密钥和 URL (**必需**)
    *   有道智云应用 ID 和密钥 (如果使用有道 STT)
    *   Cloudinary 凭证 (如果使用 Cloudinary 视觉上传)

## 快速开始

1.  **后端设置:** 克隆仓库, 安装 Python 依赖 (`pip install -r requirements.txt`), 在 `.env` 文件中配置 API 密钥 (从 `.env.example` 复制), 运行 `python src/app.py`。 (详见 [**后端设置**](docs/TUTORIAL.zh-CN.md#后端服务器设置))
2.  **前端设置:** 安装 Tampermonkey/Violentmonkey, 安装 `.user.js` 脚本, 确保脚本中的 `INFERENCE_SERVICE_URL` 和 `INFERENCE_SERVICE_API_KEY` 与你的后端配置匹配。 (详见 [**前端设置**](docs/TUTORIAL.zh-CN.md#前端用户脚本设置))
3.  **使用:** 访问支持的直播间，使用控制面板启动代理。 (详见 [**使用指南**](docs/TUTORIAL.zh-CN.md#使用方法))

**➡️ 获取详细步骤，请阅读 [完整教程 (TUTORIAL.zh-CN.md)](docs/TUTORIAL.zh-CN.md)**

## 项目结构
```
.
├── backend/                # 服务器代码及相关文件
│   ├── src/               # 源代码目录
│   │   ├── app.py         # Flask 应用主入口
│   │   ├── services/      # 服务层
│   │   │   ├── external_apis.py  # 外部 API 集成服务
│   │   │   ├── llm_service.py    # LLM 处理服务
│   │   │   └── state_service.py  # 状态管理服务
│   │   └── utils/         # 工具模块
│   │       └── config.py  # 配置管理
│   ├── memory/            # 持久化记忆存储
│   ├── prompts/           # 系统提示词文件
│   ├── requirements.txt   # Python 依赖
│   └── .env.example       # 环境配置示例
├── frontend/              # 用户脚本代码
│   └── live-stream-chat-ai-agent.user.js
├── docs/                  # 文档和图片
├── tools/                 # 辅助工具
├── README.md              # 英文说明
├── README.zh-CN.md        # 本文件 (中文说明)
├── LICENSE                # AGPL-3.0 许可证文件
└── .gitignore             # Git 忽略规则
```

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=bOOOOcG/live-stream-chat-ai-agent&type=Date)](https://www.star-history.com/#bOOOOcG/live-stream-chat-ai-agent&Date)

## 贡献

欢迎参与贡献！请参考[贡献指南 (CONTRIBUTING.md)](CONTRIBUTING.md) (待创建) 获取更多细节。

## 许可证

本项目基于 GNU Affero General Public License v3.0 (AGPL-3.0) 授权。请参阅 [LICENSE](./LICENSE) 文件获取完整许可证文本。

## 免责声明

*   **负责任地使用:** 自动化聊天需考虑道德因素。请遵守平台服务条款 (ToS) 和主播规定，避免刷屏。
*   **API 成本:** 使用 LLM、STT、Cloudinary 服务可能产生费用，请监控用量。
*   **服务条款:** 使用自动化脚本可能违反平台 ToS，请自行承担风险。
*   **AI 局限性:** AI 的理解能力受输入质量（如 STT 错误）和 LLM 本身能力限制，可能发生误解或生成不当响应。
