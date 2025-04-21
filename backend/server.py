#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Live Stream Chat AI Agent 后端服务器 (Configurable via .env)

This Flask server receives audio chunks, chat lists, and optional screenshots
from a Bilibili live user script. It performs speech-to-text, manages
conversation context and memory (notepad), interacts with an LLM (like GPT),
uploads screenshots, and sends parsed instructions (e.g., synthesized chat
messages) back to the user script for execution.

Configuration is primarily managed through the .env file.
See .env.example for details.
"""

import os
import re
import json
import math
import shutil
import argparse # Kept for specific actions like --check-system-tokens
import traceback
import base64
import hashlib
import time
import uuid
import openai
import subprocess
import wave
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# Flask/Server related imports
from flask import Flask, request, jsonify, abort
from flask_cors import CORS

# API Clients and Core Libraries
import requests
from openai import OpenAI
import cloudinary
import cloudinary.uploader
import cloudinary.api
import tiktoken
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image

# --- Load Environment Variables ---
# Load .env file before doing anything else that might depend on it.
print("Loading environment variables from .env file...")
load_dotenv()
print(".env file loaded (if found).")

# --- Helper Functions for Environment Variable Loading ---
def get_env_bool(var_name: str, default: bool = False) -> bool:
    """Gets a boolean value from environment variables."""
    value = os.getenv(var_name, str(default)).lower()
    return value in ('true', '1', 't', 'y', 'yes')

def get_env_int(var_name: str, default: int) -> int:
    """Gets an integer value from environment variables, with error handling."""
    value_str = os.getenv(var_name)
    if value_str is None:
        # print(f"Info: Environment variable {var_name} not set. Using default: {default}")
        return default
    try:
        return int(value_str)
    except ValueError:
        print(f"Warning: Invalid integer value for {var_name} ('{value_str}'). Using default: {default}")
        return default

def get_env_float(var_name: str, default: float) -> float:
    """Gets a float value from environment variables, with error handling."""
    value_str = os.getenv(var_name)
    if value_str is None:
        # print(f"Info: Environment variable {var_name} not set. Using default: {default}")
        return default
    try:
        return float(value_str)
    except ValueError:
        print(f"Warning: Invalid float value for {var_name} ('{value_str}'). Using default: {default}")
        return default

def get_env_str(var_name: str, default: str = "") -> str:
    """Gets a string value from environment variables."""
    return os.getenv(var_name, default)

# --- Constants from Environment or Defaults ---
# Load file paths and prefixes from .env, providing reasonable fallbacks
MEMORY_BASE_DIR = get_env_str('MEMORY_BASE_DIR', "memory")
TEST_FILES_DIR = get_env_str('TEST_FILES_DIR', "test")
AUDIO_TEMP_PREFIX = get_env_str('AUDIO_TEMP_PREFIX', "live_audio_")
SCREENSHOT_TEMP_PREFIX = get_env_str('SCREENSHOT_TEMP_PREFIX', "live_screenshot_")
FFMPEG_PATH = get_env_str('FFMPEG_PATH', "ffmpeg") # Crucial for Youdao conversion

# --- Default System Prompt (Fallback) ---
# Used if SYSTEM_PROMPT_PATH is not set or the file cannot be read
DEFAULT_SYSTEM_PROMPT = (
"你是直播间的自动互动系统。以下是你必须遵守的规则说明："
""
"1. 每段文本是主播30秒内的语音内容，通过语音识别技术转化，可能包含识别错误、语义缺失或是背景音乐歌词，需自行辨别其准确性。"
"2. 输出必须严格使用以下格式指令："
"   - {continues: x}：当不打算发言时使用，x表示连续未发弹幕的次数。"
"   - {msg_x: \"内容\"}：发送弹幕，x为0~2的编号；每条不超过20字符为佳，必要时可以发送多条。"
"   - {think: \"内容\"}：内部思考，不会发送到直播间。"
"   - {notepad: \"内容\"}：记录重要笔记，用于后续更好地互动。每条简明扼要，不可续写上一条。"
"3. 弹幕必须自然、简洁、有信息量，避免无意义内容或重复表达。"
"4. 遇到疑似对你发言时，应合理判断并尝试回应。"
"5. 严禁讨论政治话题或暴露系统内部细节（如语音识别过程）。"
"6. 弹幕内容应使用简体中文，不使用标点逗号，改用空格分隔词语。"
"7. 聊天速度需控制：每两轮最多三条弹幕，避免刷屏。"
"8. 禁止频繁自言自语，应努力展开对话或参与已有话题。"
"9. 不得暴露看不到画面，不得根据识别结果妄自判断主播情绪或动作。"
"10. 可参考 chat list（直播间弹幕）进行判断，你也可以回复聊天室的其他人。"
"11. 应留意礼物请求等商业行为，一律使用“我目前没有这个功能”回应。"
"12. 若被误认为机器人，应主动解释自身合理行为逻辑。"
"13. 识别结果中若包含歌名、歌词或BGM内容，应避免误判为直播者语言。"
"14. 你可以与观众互动，这是规避识别误差的安全方式。"
"15. 不得连续发送格式一致的句子，如多个问句或感叹句。"
""
"示例响应："
"{continues: 0},  "
"{think: \"该段识别内容可能包含歌词或识别错误 但主播疑似提到了昵称\"},  "
"{msg_0: \"我在听呀\"},  "
"{notepad: \"主播喜欢互动 并可能会念观众的名字\"}"
""
"你只能输出上述格式的指令，并遵循所有规则。"
    # The preamble for the image is now added dynamically in _build_llm_prompt
)

# --- LiveAssistantServer Class ---
class LiveAssistantServer:
    """
    Handles the core logic for processing live stream data, interacting with
    AI services, and managing state per chat room, configured via environment variables.
    """

    def __init__(self, args: argparse.Namespace):
        """
        Initializes the server instance with configuration loaded from environment variables.
        Command-line arguments (args) can override certain behaviors like test mode activation
        or performing a one-off check.

        Args:
            args: Parsed command-line arguments (used for specific actions like --check-system-tokens).

        Raises:
            ValueError: If essential configuration (e.g., LLM API key/URL) is missing.
        """
        self.cli_args = args # Store command-line args for potential overrides/actions
        print("Initializing Server...")

        # Load all configurations from environment variables
        self._load_configuration()

        # Override test mode if command-line flag is set
        if self.cli_args.test:
             print("Command-line argument '--test' detected, enabling test mode (overrides SERVER_TEST_MODE from .env).")
             self.enable_test_mode = True
        # Set comparison mode based on CLI argument
        self.stt_comparison_mode = self.cli_args.compare_speech_recognition
        if self.stt_comparison_mode:
            print("Command-line argument '--compare-speech-recognition' detected. Will only run STT comparison.")

        print(f"Effective Configuration: Test Mode={self.enable_test_mode}, Vision={self.enable_vision}, STT Provider={self.stt_provider}")

        # --- Model & Tokenizer ---
        try:
            self.tokenizer = tiktoken.encoding_for_model(self.llm_tokenizer_model)
            print(f"Tokenizer loaded for model: '{self.llm_tokenizer_model}'")
        except Exception as e:
            print(f"Warning: Could not load tokenizer for '{self.llm_tokenizer_model}'. Token counts may be inaccurate. Error: {e}")
            self.tokenizer = None # Gracefully handle tokenizer failure

        # --- Initialize Clients ---
        self._initialize_clients()

        # --- Setup Directories ---
        self.memory_base_dir = Path(MEMORY_BASE_DIR)
        self.test_dir = Path(TEST_FILES_DIR)
        self.screenshot_upload_dir = self.test_dir / 'uploaded_screenshots' # Specific test dir for organization

        self.memory_base_dir.mkdir(exist_ok=True)
        if self.enable_test_mode:
            self.test_dir.mkdir(exist_ok=True)
            self.screenshot_upload_dir.mkdir(exist_ok=True)
            print(f"Test mode enabled. Files will be saved to: {self.test_dir.resolve()}")
        else:
            print("Test mode disabled.")

        # --- System Prompt ---
        self._setup_system_prompt() # Loads from file or uses default

        print("Server Initialization Complete.")

    def _load_configuration(self):
        """Loads configuration from environment variables."""
        print("Loading configuration from environment variables...")

        # LLM Config (Required)
        self.llm_api_key = get_env_str("LLM_API_KEY")
        self.llm_api_url = get_env_str("LLM_API_URL")
        if not self.llm_api_key or not self.llm_api_url:
            raise ValueError("CRITICAL: LLM_API_KEY or LLM_API_URL not configured in .env")

        self.llm_api_model = get_env_str('LLM_API_MODEL', 'gpt-4o-mini')
        self.llm_tokenizer_model = get_env_str('LLM_TOKENIZER_MODEL', self.llm_api_model) # Default to API model
        self.max_llm_response_tokens = get_env_int('LLM_MAX_RESPONSE_TOKENS', 2000)
        self.api_timeout_seconds = get_env_int('LLM_API_TIMEOUT_SECONDS', 60)
        print(f"LLM Config: API_Model='{self.llm_api_model}', Tokenizer='{self.llm_tokenizer_model}', MaxRespTokens={self.max_llm_response_tokens}, Timeout={self.api_timeout_seconds}s")

        # Token Limits
        self.max_total_tokens = get_env_int('PROMPT_MAX_TOTAL_TOKENS', 4096)
        self.max_notepad_tokens_in_prompt = get_env_int('PROMPT_MAX_NOTEPAD_TOKENS', 712)
        self.max_chatlist_tokens_in_prompt = get_env_int('PROMPT_MAX_CHATLIST_TOKENS', 256)
        print(f"Token Limits: TotalPrompt={self.max_total_tokens}, NotepadInPrompt={self.max_notepad_tokens_in_prompt}, ChatlistInPrompt={self.max_chatlist_tokens_in_prompt}")

        # STT Config
        self.stt_provider = get_env_str('STT_PROVIDER', 'whisper').lower()
        if self.stt_provider not in ['youdao', 'whisper', 'both']:
             print(f"Warning: Invalid STT_PROVIDER '{self.stt_provider}' in .env. Valid options: 'youdao', 'whisper', 'both'. Defaulting to 'whisper'.")
             self.stt_provider = 'whisper'
        self.youdao_app_key = get_env_str("YOUDAO_APP_KEY")
        self.youdao_app_secret = get_env_str("YOUDAO_APP_SECRET")
        self.youdao_api_url = get_env_str('YOUDAO_API_URL', 'https://openapi.youdao.com/asrapi')
        self.use_youdao_stt = 'youdao' in self.stt_provider or 'both' in self.stt_provider
        self.use_whisper_stt = 'whisper' in self.stt_provider or 'both' in self.stt_provider

        if self.use_youdao_stt and (not self.youdao_app_key or not self.youdao_app_secret):
            print("Warning: STT_PROVIDER includes 'youdao', but YOUDAO_APP_KEY or YOUDAO_APP_SECRET is missing in .env. Youdao STT will likely fail.")
        print(f"STT Config: Provider='{self.stt_provider}', UseYoudao={self.use_youdao_stt}, UseWhisper={self.use_whisper_stt}")

        # Vision Config
        self.enable_vision = get_env_bool('VISION_ENABLE', False)
        self.vision_upload_provider = get_env_str('VISION_UPLOAD_PROVIDER', 'cloudinary').lower() if self.enable_vision else 'none'
        self.cloudinary_cloud_name = get_env_str("CLOUDINARY_CLOUD_NAME")
        self.cloudinary_api_key = get_env_str("CLOUDINARY_API_KEY")
        self.cloudinary_api_secret = get_env_str("CLOUDINARY_API_SECRET")
        self.cloudinary_upload_folder = get_env_str('CLOUDINARY_UPLOAD_FOLDER', "bilibili_live_screenshot")
        self.image_compression_quality = get_env_int('IMAGE_COMPRESSION_QUALITY', 50)
        # Validate compression quality
        if not (0 <= self.image_compression_quality <= 95):
             if self.image_compression_quality != 0: # Allow 0 explicitly for disabling
                  print(f"Warning: Invalid IMAGE_COMPRESSION_QUALITY ({self.image_compression_quality}). Must be between 0 (disable) and 95. Disabling compression.")
             self.image_compression_quality = 0 # Disable if invalid or explicitly 0

        self.cloudinary_configured = (self.vision_upload_provider == 'cloudinary' and
                                     all([self.cloudinary_cloud_name, self.cloudinary_api_key, self.cloudinary_api_secret]))

        if self.enable_vision:
             print(f"Vision Config: Enabled={self.enable_vision}, UploadProvider='{self.vision_upload_provider}', CompressQuality={self.image_compression_quality if self.image_compression_quality > 0 else 'Disabled'}")
             if self.vision_upload_provider == 'cloudinary' and not self.cloudinary_configured:
                 print("Warning: VISION_ENABLE is true and VISION_UPLOAD_PROVIDER is 'cloudinary', but Cloudinary credentials (NAME, KEY, SECRET) are incomplete in .env. Image uploads will fail.")
             elif self.vision_upload_provider == 'none':
                 print("Info: Vision enabled, but upload provider is 'none'. Screenshots will be processed locally only (e.g., saved in test mode).")
             elif self.vision_upload_provider not in ['cloudinary', 'none']:
                  print(f"Warning: Invalid VISION_UPLOAD_PROVIDER '{self.vision_upload_provider}'. Valid options: 'cloudinary', 'none'. Disabling uploads.")
                  self.vision_upload_provider = 'none'
        else:
            print("Vision Config: Disabled.")

        # System Prompt Config
        self.system_prompt_mode = get_env_str('SYSTEM_PROMPT_MODE', 'standard').lower()
        if self.system_prompt_mode not in ['standard', 'user_message_compatibility']:
             print(f"Warning: Invalid SYSTEM_PROMPT_MODE '{self.system_prompt_mode}'. Valid options: 'standard', 'user_message_compatibility'. Defaulting to 'standard'.")
             self.system_prompt_mode = 'standard'
        self.system_prompt_path = get_env_str('SYSTEM_PROMPT_PATH') # Path can be empty
        print(f"System Prompt Config: Mode='{self.system_prompt_mode}', Path='{self.system_prompt_path if self.system_prompt_path else '(Not Set, using default)'}'")

        # Other Settings pulled directly from env where used (e.g., FFMPEG_PATH)
        # SERVER_TEST_MODE is loaded directly from .env
        self.enable_test_mode = get_env_bool("SERVER_TEST_MODE", False)

    def _initialize_clients(self):
        """Initializes API clients based on configuration."""
        # Cloudinary Client (only if enabled and configured)
        if self.enable_vision and self.vision_upload_provider == 'cloudinary':
            if self.cloudinary_configured:
                try:
                    print("Initializing Cloudinary client...")
                    cloudinary.config(
                        cloud_name=self.cloudinary_cloud_name,
                        api_key=self.cloudinary_api_key,
                        api_secret=self.cloudinary_api_secret,
                        secure=True # Force HTTPS URLs
                    )
                    # Optional: Test connection (can slow down startup)
                    # cloudinary.api.ping()
                    print("Cloudinary client initialized successfully.")
                except Exception as e:
                    print(f"ERROR: Failed to initialize Cloudinary client: {e}. Disabling Cloudinary uploads.")
                    self.cloudinary_configured = False # Mark as not configured on error
            else:
                # Already warned during config load, but reiterate here
                print("Cloudinary client NOT initialized due to missing credentials.")
        elif self.enable_vision:
            print("Cloudinary client NOT initialized (Upload provider is not 'cloudinary').")
        else:
            print("Cloudinary client NOT initialized (Vision disabled).")

        # LLM Client (Required)
        try:
            print(f"Initializing OpenAI client (Base URL: {self.llm_api_url})...")
            self.llm_client = OpenAI(
                api_key=self.llm_api_key,
                base_url=self.llm_api_url,
                timeout=self.api_timeout_seconds + 10 # Give a bit more timeout buffer to the client constructor
            )
            # Optional: Test connection (can slow down startup and cost tokens/money)
            # print("Testing LLM connection...")
            # self.llm_client.models.list()
            # print("LLM connection successful.")
            print("OpenAI client initialized.")
        except Exception as e:
            # LLM Client initialization failure is critical
            raise ValueError(f"CRITICAL: Failed to initialize OpenAI client: {e}")

    def _setup_system_prompt(self):
        """Loads the system prompt from file or uses the default, sets up API messages."""
        prompt_content = None
        prompt_source = "Default Internal Prompt"

        if self.system_prompt_path:
            prompt_file = Path(self.system_prompt_path)
            if prompt_file.is_file():
                try:
                    with prompt_file.open('r', encoding='utf-8') as f:
                        prompt_content = f.read()
                    prompt_source = f"File: {self.system_prompt_path}"
                    print(f"Successfully loaded system prompt from {prompt_source}")
                except Exception as e:
                    print(f"Warning: Could not read system prompt file '{self.system_prompt_path}': {e}. Using default prompt.")
            else:
                print(f"Warning: System prompt file not found at '{self.system_prompt_path}'. Using default prompt.")

        if prompt_content is None:
            prompt_content = DEFAULT_SYSTEM_PROMPT
            print(f"Using {prompt_source}.")

        self.system_prompt_content = prompt_content

        # Configure how the prompt is sent to the API
        if self.system_prompt_mode == 'user_message_compatibility':
            print("System prompt mode: user_message_compatibility (sending as first user message).")
            self.initial_context_message = [{"role": "user", "content": self.system_prompt_content}]
            # This will be empty, the prompt is part of the 'user' message list
            self.system_prompt_message_for_api = []
        else: # Default 'standard' mode
            print("System prompt mode: standard (sending with 'system' role).")
            self.initial_context_message = [{"role": "system", "content": self.system_prompt_content}]
            # This holds the message to be prepended to API calls
            self.system_prompt_message_for_api = self.initial_context_message

        # Calculate system prompt tokens (approximate)
        self.system_prompt_tokens = self._calculate_tokens(self.system_prompt_content)
        print(f"System Prompt Tokens (approximate): {self.system_prompt_tokens}")

    # --- Static Utility Methods ---
    @staticmethod
    def _get_audio_base64(audio_path: Path) -> Optional[str]:
        """Reads an audio file and returns its Base64 encoded string."""
        try:
            with audio_path.open('rb') as f:
                audio_data = f.read()
            return base64.b64encode(audio_data).decode('utf-8')
        except FileNotFoundError:
            print(f"Error: Audio file not found at {audio_path}")
            return None
        except Exception as e:
            print(f"Error reading or encoding audio file {audio_path}: {e}")
            return None

    @staticmethod
    def _truncate_for_youdao(q: Optional[str]) -> Optional[str]:
        """Truncates a string according to Youdao API's requirement for signing."""
        if q is None: return None
        size = len(q)
        return q if size <= 20 else q[:10] + str(size) + q[-10:]

    # --- Instance Utility Methods ---
    def _calculate_tokens(self, text: str) -> int:
        """Calculates the number of tokens for a given text using the initialized tokenizer."""
        if not self.tokenizer or not isinstance(text, str) or not text:
            return 0
        try:
            # Note: Special tokens might affect count slightly depending on model/usage.
            # Use `allowed_special=set()` or `disallowed_special="all"` for stricter counts if needed.
            return len(self.tokenizer.encode(text))#, disallowed_special=()))
        except Exception as e:
            # Log token calculation errors sparingly if they become noisy
            # print(f"Warning: Token calculation error for text snippet: '{text[:50]}...': {e}")
            # Fallback: Estimate based on characters (adjust factor as needed)
            return math.ceil(len(text) / 3.5) # Common rough estimate

    def _get_youdao_sign(self, q_base64: str, salt: str, curtime: str) -> Optional[str]:
        """Generates the signature required for Youdao API calls."""
        if not self.youdao_app_key or not self.youdao_app_secret:
             print("Error: Cannot generate Youdao sign. App Key or Secret missing.")
             return None
        truncated_q = self._truncate_for_youdao(q_base64)
        if truncated_q is None: return None # Handle case where truncation fails (e.g., input None)

        sign_str = self.youdao_app_key + truncated_q + salt + curtime + self.youdao_app_secret
        hash_algorithm = hashlib.sha256()
        hash_algorithm.update(sign_str.encode('utf-8'))
        return hash_algorithm.hexdigest()

    def _print_context_debug(self, context_messages: List[Dict[str, Any]], final_token_count: int):
        """Prints the final context being sent to the LLM for debugging."""
        print(f"\n📤 Final Context ({len(context_messages)} messages, ~{final_token_count} tokens) Sent to LLM:")
        for i, msg in enumerate(context_messages):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            content_repr = ""
            if isinstance(content, list): # Handle Vison API format
                parts = []
                for item in content:
                    item_type = item.get("type")
                    if item_type == "text":
                        parts.append(f"Text: '{item.get('text', '')[:100]}...'")
                    elif item_type == "image_url":
                        url = item.get('image_url', {}).get('url', '')
                        parts.append(f"Image: '{url[:50]}...'")
                    else:
                        parts.append(f"{str(item)[:100]}...")
                content_repr = "[" + ", ".join(parts) + "]"
            elif isinstance(content, str):
                content_repr = f"'{content[:150]}...'"
            else:
                content_repr = f"{str(content)[:150]}..."
            print(f"  [{i}] Role: {role:<9} Content: {content_repr}")
        print("-" * 20)

    # --- State Management Methods (Filesystem) ---
    def _get_memory_folder(self, room_id: str) -> Path:
        """Gets the Path object for a specific room's memory folder."""
        # Ensure room_id is sanitized to prevent directory traversal issues if needed
        # For simplicity, assuming room_id is trustworthy here.
        safe_room_id = str(room_id).replace("..", "").replace("/", "").replace("\\", "")
        return self.memory_base_dir / safe_room_id

    def _get_notepad_file_path(self, room_id: str) -> Path:
        """Gets the Path object for a specific room's notepad file."""
        return self._get_memory_folder(room_id) / "notepad.txt"

    # def _get_chat_list_file_path(self, room_id: str) -> Path:
    #     """Gets the Path object for a specific room's chat list file (if persistent storage was needed)."""
    #     # Currently unused as chat list comes from request, but kept for potential future use.
    #     return self._get_memory_folder(room_id) / "chat_list.txt"

    def _get_context_file_path(self, room_id: str) -> Path:
        """Gets the Path object for a specific room's context history file."""
        return self._get_memory_folder(room_id) / "context.json"

    def _load_notepad_for_prompt(self, room_id: str) -> Tuple[str, int]:
        """
        Loads notepad content, formats it as a single string for the prompt,
        respecting the specific token limit for this section.
        Returns the formatted string and its token count.
        """
        file_path = self._get_notepad_file_path(room_id)
        notepad_content = ""
        total_tokens = 0
        if not file_path.exists():
            return notepad_content, total_tokens

        lines_to_include = []
        try:
            with file_path.open("r", encoding="utf-8") as f:
                all_lines = [line.strip() for line in f if line.strip()]
                # Iterate in reverse to prioritize recent notes
                for line in reversed(all_lines):
                    line_tokens = self._calculate_tokens(line)
                    # Check if adding this line fits within the notepad budget
                    if total_tokens + line_tokens <= self.max_notepad_tokens_in_prompt:
                        lines_to_include.insert(0, line) # Insert at beginning to maintain order
                        total_tokens += line_tokens
                    else:
                        break # Stop if budget exceeded
            if lines_to_include:
                # Format as a block for the prompt
                notepad_content = "{notepad:\n" + "\n".join(lines_to_include) + "\n}"
                # Recalculate tokens for the final formatted string
                total_tokens = self._calculate_tokens(notepad_content)

        except Exception as e:
            print(f"Error loading notepad for prompt (room {room_id}): {e}")
            notepad_content = "" # Return empty on error
            total_tokens = 0

        return notepad_content, total_tokens

    def _append_to_notepad(self, room_id: str, new_notes: List[str]):
        """Appends new notes to the room's notepad file."""
        if not new_notes: return
        file_path = self._get_notepad_file_path(room_id)
        file_path.parent.mkdir(parents=True, exist_ok=True) # Ensure directory exists
        try:
            with file_path.open("a", encoding="utf-8") as f:
                for note in new_notes:
                    # Basic validation: ensure it's a non-empty string
                    if isinstance(note, str) and note.strip():
                        f.write(note.strip() + "\n")
        except Exception as e:
             print(f"Error appending to notepad for room {room_id}: {e}")

    def _load_chat_list_for_prompt(self, current_chat_list: List[Dict[str, Any]]) -> Tuple[str, int]:
        """
        Formats the *current request's* chat list for the prompt, respecting token limits.
        Returns the formatted string and its token count.
        """
        formatted_chats = []
        total_tokens = 0
        if not current_chat_list:
            return "", 0

        # Iterate the *input* list in reverse to prioritize recent chats
        for chat in reversed(current_chat_list):
            uname = chat.get('uname', 'Unknown')
            content = chat.get('content', '').strip()
            if not content: continue # Skip empty messages

            line = f"{uname}: {content}"
            line_tokens = self._calculate_tokens(line)

            # Check if adding this line fits within the chat list budget
            if total_tokens + line_tokens <= self.max_chatlist_tokens_in_prompt:
                formatted_chats.insert(0, line) # Insert at beginning to maintain order
                total_tokens += line_tokens
            else:
                break # Stop if budget exceeded

        if formatted_chats:
            # Format as a block for the prompt
            chat_list_content = "{Chatlist content:\n" + "\n".join(formatted_chats) + "\n}"
            # Recalculate tokens for the final formatted string
            total_tokens = self._calculate_tokens(chat_list_content)
            return chat_list_content, total_tokens
        else:
            return "", 0

    def _load_trimmed_context_history(self, room_id: str, reserved_tokens: int) -> List[Dict[str, Any]]:
        """
        Loads historical context, trimming older messages to fit the available token budget
        (max_total - system_prompt - reserved_for_current_input).
        Excludes the system prompt itself.
        """
        file_path = self._get_context_file_path(room_id)
        if not file_path.exists():
            return []

        try:
            with file_path.open('r', encoding='utf-8') as f:
                # Load the full history including system prompt etc.
                full_context_history = json.load(f)
                # Filter out system prompt here before trimming
                history_to_trim = [msg for msg in full_context_history if msg.get("role") != "system"]
        except Exception as e:
            print(f"Error loading or parsing context file for room {room_id}: {e}. Starting with fresh context.")
            # Attempt to delete corrupted file? Maybe too risky.
            # try:
            #     file_path.unlink()
            # except OSError: pass
            return []

        # Calculate the token budget specifically for historical messages
        token_budget = self.max_total_tokens - self.system_prompt_tokens - reserved_tokens
        if token_budget <= 0:
            print("Warning: No token budget remaining for history after system prompt and reserved space.")
            return []

        trimmed_history = []
        current_tokens = 0

        # Iterate history in reverse (newest first)
        for msg in reversed(history_to_trim):
            # Skip any messages marked as temporary or special internal flags if needed
            if msg.get("is_temp"): continue

            msg_tokens = 0
            content = msg.get("content")
            if isinstance(content, list): # Handle vision messages in history
                msg_tokens = sum(self._calculate_tokens(item.get("text", ""))
                                 for item in content if item.get("type") == "text")
                # Note: Image tokens are not accurately calculated here. This assumes text dominates.
                # Add a heuristic cost per image if necessary:
                # msg_tokens += sum(150 for item in content if item.get("type") == "image_url")
            elif isinstance(content, str):
                msg_tokens = self._calculate_tokens(content)

            if msg_tokens == 0: continue # Skip empty or unprocessable messages

            if current_tokens + msg_tokens <= token_budget:
                trimmed_history.insert(0, msg) # Add to beginning to maintain order
                current_tokens += msg_tokens
            else:
                break # Stop when budget is full

        print(f"📦 Loaded context history for room {room_id}: {len(trimmed_history)} messages, ~{current_tokens} tokens (Budget: {token_budget})")
        return trimmed_history

    def _save_context(self, room_id: str, full_context_data: List[Dict[str, Any]]):
        """Saves the complete current context (including system prompt, user, assistant) to file."""
        # Ensure no temporary flags accidentally get saved
        context_to_save = [msg for msg in full_context_data if not msg.get("is_temp", False)] # Example temp flag

        file_path = self._get_context_file_path(room_id)
        file_path.parent.mkdir(parents=True, exist_ok=True) # Ensure directory exists
        try:
            with file_path.open('w', encoding='utf-8') as f:
                json.dump(context_to_save, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Error saving context for room {room_id}: {e}")

    # --- External Service Methods ---
    def _recognize_speech_youdao(self, audio_wav_path: Path) -> Optional[str]:
        """Calls the Youdao STT API."""
        if not self.youdao_app_key or not self.youdao_app_secret:
             print("Cannot perform Youdao STT: App Key or Secret is missing.")
             return None

        q_base64 = self._get_audio_base64(audio_wav_path)
        if not q_base64: return None # Error logged in _get_audio_base64

        curtime = str(int(time.time()))
        salt = str(uuid.uuid1())
        sign = self._get_youdao_sign(q_base64, salt, curtime)
        if not sign: return None # Error logged in _get_youdao_sign

        data = {
            'q': q_base64, 'langType': 'zh-CHS', # Consider making langType configurable if needed
            'appKey': self.youdao_app_key, 'salt': salt, 'curtime': curtime,
            'sign': sign, 'signType': 'v3', 'format': 'wav', 'rate': '16000',
            'channel': '1', 'type': '1',
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        try:
            # Use configured timeout, defaulting to 20s for STT
            stt_timeout = get_env_int('YOUDAO_TIMEOUT_SECONDS', 20)
            response = requests.post(self.youdao_api_url, data=data, headers=headers, timeout=stt_timeout)
            response.raise_for_status() # Check for HTTP errors (4xx, 5xx)
            result = response.json()

            if result.get('errorCode') == '0' and result.get('result'):
                recognized = result['result'][0]
                # print(f"Youdao STT Success: '{recognized[:100]}...'") # Reduced verbosity
                return recognized
            else:
                # Log Youdao-specific errors
                print(f"Youdao API returned an error: Code {result.get('errorCode')}, Msg: {result.get('msg', 'N/A')}, Response: {result}")
                return None
        except requests.exceptions.Timeout:
             print(f"Error: Timeout connecting to Youdao API ({self.youdao_api_url}) after {stt_timeout}s.")
             return None
        except requests.exceptions.RequestException as e:
            print(f"Error connecting to Youdao API ({self.youdao_api_url}): {e}")
            return None
        except json.JSONDecodeError as e:
             print(f"Error decoding Youdao API response: {e}. Response text: {response.text[:200] if response else 'N/A'}")
             return None
        except Exception as e:
            print(f"Unexpected error during Youdao recognition: {e}")
            traceback.print_exc()
            return None

    def _recognize_speech_whisper(self, audio_path: Path) -> Optional[str]:
        """Calls the Whisper STT API via the configured OpenAI-compatible endpoint."""
        # Requires LLM_API_KEY and LLM_API_URL to be set
        if not self.llm_api_key or not self.llm_api_url:
             print("Cannot perform Whisper STT: LLM API Key or URL is missing.")
             return None

        # Construct the specific API endpoint for audio transcriptions
        # Handle potential trailing slashes in the base URL
        base_url = self.llm_api_url.rstrip('/')
        api_url = f'{base_url}/audio/transcriptions'
        headers = {'Authorization': f'Bearer {self.llm_api_key}'}

        try:
            with audio_path.open('rb') as audio_file:
                 # The API expects multipart/form-data
                 files = {'file': (audio_path.name, audio_file, 'audio/webm')} # Assuming input is webm
                 data = {'model': 'whisper-1'} # Standard model name
                 # Use configured timeout, default 30s for STT
                 stt_timeout = get_env_int('WHISPER_TIMEOUT_SECONDS', 30)

                 response = requests.post(api_url, headers=headers, files=files, data=data, timeout=stt_timeout)
                 response.raise_for_status() # Check for HTTP errors
                 result = response.json()
                 recognized_text = result.get('text')

                 if recognized_text is not None: # Check for None explicitly, empty string is valid
                     # print(f"Whisper STT Success: '{recognized_text[:100]}...'") # Reduced verbosity
                     return recognized_text
                 else:
                     print(f"Whisper API response did not contain 'text': {result}")
                     return None # Treat missing text as failure

        except requests.exceptions.Timeout:
             print(f"Error: Timeout connecting to Whisper API ({api_url}) after {stt_timeout}s.")
             return None
        except requests.exceptions.RequestException as e:
             # Log details including the URL
             print(f"Error connecting to Whisper API endpoint ({api_url}): {e}")
             # If it's an auth error, the response might contain clues
             if hasattr(e, 'response') and e.response is not None:
                 print(f"Whisper API Response Status: {e.response.status_code}")
                 print(f"Whisper API Response Body: {e.response.text[:200]}...")
             return None
        except FileNotFoundError:
            print(f"Error: Audio file not found for Whisper STT: {audio_path}")
            return None
        except json.JSONDecodeError as e:
             print(f"Error decoding Whisper API response: {e}. Response text: {response.text[:200] if response else 'N/A'}")
             return None
        except Exception as e:
            print(f"Unexpected error during Whisper recognition: {e}")
            traceback.print_exc()
            return None

    def _convert_audio_to_wav(self, input_path: Path, output_path: Path) -> bool:
        """Converts input audio (e.g., webm) to WAV format required by Youdao using FFmpeg."""
        if not Path(FFMPEG_PATH).exists() and not shutil.which(FFMPEG_PATH):
             print(f"CRITICAL ERROR: FFmpeg executable not found at '{FFMPEG_PATH}' or in system PATH.")
             print("Audio conversion for Youdao STT will fail. Please install FFmpeg or correct FFMPEG_PATH in .env.")
             return False
        try:
            command = [
                FFMPEG_PATH, '-y',          # Overwrite output file if exists
                '-i', str(input_path),     # Input file path
                '-vn',                     # No video
                '-acodec', 'pcm_s16le',    # Standard WAV codec
                '-ac', '1',                # Mono channel
                '-ar', '16000',            # 16kHz sample rate
                '-f', 'wav',               # Output format WAV
                 str(output_path)          # Output file path
            ]
            # print(f"Running FFmpeg: {' '.join(command)}") # Reduced verbosity
            # Use timeout for ffmpeg process? Could hang indefinitely otherwise.
            ffmpeg_timeout = get_env_int('FFMPEG_TIMEOUT_SECONDS', 30)
            result = subprocess.run(
                command,
                capture_output=True, # Capture stdout/stderr
                text=True,           # Decode output as text
                check=False,         # Don't raise exception on non-zero exit code
                encoding='utf-8',    # Specify encoding
                timeout=ffmpeg_timeout
                )

            if result.returncode != 0:
                print(f"ERROR: FFmpeg failed to convert {input_path.name} to WAV.")
                print(f"FFmpeg Return Code: {result.returncode}")
                print(f"FFmpeg STDERR:\n{result.stderr}")
                # Clean up potentially incomplete output file
                output_path.unlink(missing_ok=True)
                return False
            else:
                # print(f"Successfully converted {input_path.name} to WAV.")
                return True
        except FileNotFoundError:
            # This case should be caught by the initial check, but added for robustness
            print(f"Error: '{FFMPEG_PATH}' command not found during execution attempt.")
            return False
        except subprocess.TimeoutExpired:
             print(f"Error: FFmpeg process timed out after {ffmpeg_timeout} seconds converting {input_path.name}.")
             output_path.unlink(missing_ok=True) # Clean up partial file
             return False
        except Exception as e:
            print(f"Error during FFmpeg execution: {e}")
            traceback.print_exc()
            output_path.unlink(missing_ok=True) # Clean up partial file
            return False

    def _perform_speech_recognition(self, audio_webm_path: Path) -> Tuple[Optional[str], Optional[str]]:
        """Performs speech recognition using the configured provider(s)."""
        recognized_text_youdao = None
        recognized_text_whisper = None
        temp_wav_path = None

        # Determine which services to run based on config and comparison mode
        run_youdao = self.use_youdao_stt or self.stt_comparison_mode
        run_whisper = self.use_whisper_stt or self.stt_comparison_mode

        if not run_youdao and not run_whisper:
            print("STT is disabled (neither Youdao nor Whisper configured).")
            return None, None

        with tempfile.TemporaryDirectory(prefix="stt_conversion_") as temp_dir:
            temp_dir_path = Path(temp_dir)

            # --- Prepare necessary files ---
            # Convert to WAV if Youdao is needed
            if run_youdao:
                temp_wav_filename = audio_webm_path.stem + ".wav"
                temp_wav_path = temp_dir_path / temp_wav_filename
                # print("Converting audio to WAV for Youdao...") # Reduced verbosity
                if not self._convert_audio_to_wav(audio_webm_path, temp_wav_path):
                    print("Youdao STT skipped due to audio conversion failure.")
                    run_youdao = False # Don't attempt Youdao if conversion failed
                # else:
                #      print(f"WAV file ready: {temp_wav_path}") # Reduced verbosity

            # --- Execute STT tasks concurrently ---
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {}
                if run_youdao and temp_wav_path and temp_wav_path.exists():
                     # print("Submitting Youdao STT task...") # Reduced verbosity
                     futures[executor.submit(self._recognize_speech_youdao, temp_wav_path)] = "youdao"
                if run_whisper:
                     # print("Submitting Whisper STT task...") # Reduced verbosity
                     futures[executor.submit(self._recognize_speech_whisper, audio_webm_path)] = "whisper" # Whisper uses original

                results = {}
                if futures:
                    # print(f"Waiting for {len(futures)} STT task(s) to complete...") # Reduced verbosity
                    for i, future in enumerate(as_completed(futures)):
                        service = futures[future]
                        try:
                            results[service] = future.result() # Get result (could be None)
                            # print(f"STT task '{service}' completed ({i+1}/{len(futures)}).") # Reduced verbosity
                        except Exception as exc:
                            print(f'ERROR: STT service "{service}" task generated an exception: {exc}')
                            results[service] = None # Mark as failed on exception

                # Assign results
                recognized_text_youdao = results.get("youdao")
                recognized_text_whisper = results.get("whisper")

                # Log final STT results concisely
                stt_log = []
                if self.use_youdao_stt or self.stt_comparison_mode:
                    stt_log.append(f"Youdao: {'OK' if recognized_text_youdao else 'Fail/NA'}")
                if self.use_whisper_stt or self.stt_comparison_mode:
                     stt_log.append(f"Whisper: {'OK' if recognized_text_whisper else 'Fail/NA'}")
                print(f"STT Results: {', '.join(stt_log)}")
                if recognized_text_youdao: print(f"  Youdao Text: {recognized_text_youdao[:80]}...")
                if recognized_text_whisper: print(f"  Whisper Text: {recognized_text_whisper[:80]}...")

        # temp_dir and temp_wav_path (if created) are automatically cleaned up here
        return recognized_text_youdao, recognized_text_whisper

    def _upload_screenshot_to_cloudinary(self, image_path: Path, room_id: str) -> Optional[str]:
        """Compresses (conditionally) and uploads image to Cloudinary, returns secure URL."""
        if not self.cloudinary_configured: # Check if client is actually configured and initialized
            print("Cloudinary upload skipped: Client not configured or initialization failed.")
            return None
        if not image_path.exists():
            print(f"Error: Screenshot file not found: {image_path}")
            return None

        path_to_upload = image_path
        temp_compressed_path = None
        upload_folder = self.cloudinary_upload_folder # From .env
        quality = self.image_compression_quality # From .env

        # --- Image Compression (Optional) ---
        if quality > 0: # Compression enabled only if quality is 1-95
             # Create a temporary file for the compressed image, ensure it's cleaned up
             try:
                 # Using NamedTemporaryFile for easier path handling and cleanup
                 with tempfile.NamedTemporaryFile(
                     suffix=".jpg", prefix="compressed_", dir=image_path.parent, delete=False
                 ) as temp_file:
                     temp_compressed_path = Path(temp_file.name)

                 # print(f"Attempting to compress screenshot to JPEG (Quality: {quality})...") # Reduced verbosity
                 with Image.open(image_path) as img:
                     # Convert to RGB if it has alpha (needed for JPEG)
                     if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                          # print(f"Converting image from {img.mode} to RGB for JPEG compression.") # Reduced verbosity
                          img = img.convert('RGB')
                     # Save compressed JPEG
                     img.save(temp_compressed_path, format='JPEG', optimize=True, quality=quality)
                 # print(f"Compressed screenshot temporary file: {temp_compressed_path}") # Reduced verbosity
                 path_to_upload = temp_compressed_path # Upload the compressed version
             except Exception as e:
                 print(f"Warning: Error compressing screenshot '{image_path.name}', attempting to upload original: {e}")
                 # Clean up the potentially failed/partial temp file if it exists
                 if temp_compressed_path and temp_compressed_path.exists():
                     temp_compressed_path.unlink(missing_ok=True)
                 temp_compressed_path = None # Ensure path is None so finally block doesn't try to delete again
                 path_to_upload = image_path # Revert to uploading original
        # else:
             # print("Image compression disabled (IMAGE_COMPRESSION_QUALITY=0).") # Reduced verbosity

        # --- Cloudinary Upload ---
        try:
            timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
            # Create a unique ID using room, timestamp, and a short UUID
            public_id = f"{room_id}_{timestamp_str}_{uuid.uuid4().hex[:6]}"

            print(f"Uploading '{path_to_upload.name}' to Cloudinary (Folder: {upload_folder}, ID: {public_id})...")
            upload_response = cloudinary.uploader.upload(
                str(path_to_upload),            # API needs string path
                folder=upload_folder,           # Configured folder
                public_id=public_id,            # Generated unique ID
                tags=["live-screenshot", f"room-{room_id}"] # Add searchable tags
                # resource_type = "image" # Default, but can be explicit
            )

            if upload_response and upload_response.get('secure_url'):
                uploaded_url = upload_response['secure_url']
                print(f"✅ Screenshot successfully uploaded: {uploaded_url}")
                return uploaded_url
            else:
                # Report failure clearly
                error_msg = "Unknown upload error"
                if upload_response and upload_response.get('error'):
                     error_msg = upload_response['error'].get('message', str(upload_response['error']))
                elif not upload_response:
                     error_msg = "Empty response from Cloudinary API"
                print(f"❌ Failed to upload screenshot to Cloudinary: {error_msg}")
                return None
        except cloudinary.exceptions.Error as e:
             print(f"❌ Cloudinary API Error during upload: Status={e.http_code}, Message={e}")
             return None
        except Exception as e:
            print(f"❌ Unexpected error during Cloudinary upload process: {e}")
            traceback.print_exc()
            return None
        finally:
            # --- Cleanup Compressed File ---
            if temp_compressed_path and temp_compressed_path.exists():
                try:
                    temp_compressed_path.unlink()
                    # print(f"Cleaned up temporary compressed file: {temp_compressed_path}") # Reduced verbosity
                except Exception as e_rem:
                    print(f"Warning: Could not remove temporary compressed file {temp_compressed_path}: {e_rem}")

    def _build_llm_prompt(self,
                          room_id: str,
                          current_chat_list: List[Dict[str, Any]],
                          stt_youdao: Optional[str],
                          stt_whisper: Optional[str],
                          image_url: Optional[str]) -> List[Dict[str, Any]]:
        """Constructs the list of messages to be sent to the LLM API, combining textual inputs."""

        # 1. Load notepad once as a system message (moved out of user content)
        notepad_prompt_str, _ = self._load_notepad_for_prompt(room_id)
        # ensure notepad is the first system message
        system_notepad_message = {"role": "system", "content": f"以下是你记录的该直播间的笔记: {notepad_prompt_str}"}

        # 2. Format chat list for prompt, getting its token count
        chatlist_prompt_str, _ = self._load_chat_list_for_prompt(current_chat_list)

        # 3. Prepare current STT input and image input text preamble
        stt_text_parts = []
        if self.stt_provider == 'both':
            if stt_youdao: stt_text_parts.append(f"{{Speech2text youdao: {stt_youdao}}}")
            if stt_whisper: stt_text_parts.append(f"{{Speech2text whisper: {stt_whisper}}}")
        elif self.stt_provider == 'whisper':
            if stt_whisper: stt_text_parts.append(f"{{Speech2text whisper: {stt_whisper}}}")
            elif stt_youdao: stt_text_parts.append(f"{{Speech2text youdao: {stt_youdao}}}")
        else:
            if stt_youdao: stt_text_parts.append(f"{{Speech2text youdao: {stt_youdao}}}")
            elif stt_whisper: stt_text_parts.append(f"{{Speech2text whisper: {stt_whisper}}}")

        if not stt_text_parts and (self.use_youdao_stt or self.use_whisper_stt):
            stt_prompt_str = "{Speech2text info: No speech detected or STT failed}"
        else:
            stt_prompt_str = "\n".join(stt_text_parts)

        image_preamble_text = ""
        if self.enable_vision and image_url:
            image_preamble_text = "\n下面是当前直播间图片: "
        # --- Combine all text components for this turn ---
        current_turn_text_components = []
        if chatlist_prompt_str:
            current_turn_text_components.append(chatlist_prompt_str)
        if stt_prompt_str:
            current_turn_text_components.append(stt_prompt_str)
        if image_preamble_text:
            current_turn_text_components.append(image_preamble_text)

        combined_text_for_turn = "\n".join(current_turn_text_components).strip()

        # 4. Calculate reserved tokens and load history
        reserved_tokens = self._calculate_tokens(combined_text_for_turn) + 50
        history_messages = self._load_trimmed_context_history(room_id, reserved_tokens)

        # 5. Assemble the final list of messages for the API
        final_messages = []
        # insert notepad system message before other system prompts
        final_messages.append(system_notepad_message)
        final_messages.extend(history_messages)
        final_messages.extend(self.system_prompt_message_for_api)

        # Construct the current user message
        if combined_text_for_turn or (self.enable_vision and image_url):
            content_list = []
            if combined_text_for_turn:
                content_list.append({"type": "text", "text": combined_text_for_turn})
            if self.enable_vision and image_url:
                content_list.append({
                    "type": "image_url",
                    "image_url": {"url": image_url}
                })
            final_messages.append({"role": "user", "content": content_list})
        else:
            print("Warning: No new user inputs; sending context only.")

        return final_messages

    def _invoke_llm(self, context_messages: List[Dict[str, Any]], room_id:str = "N/A") -> Optional[str]:
        """Calls the configured LLM API with the prepared context."""
        if not context_messages:
            print("Error: Cannot invoke LLM with empty context.")
            return None

        # Calculate final token count for debugging (approximates text tokens)
        final_token_count = 0
        for msg in context_messages:
             content = msg.get("content")
             if isinstance(content, str):
                  final_token_count += self._calculate_tokens(content)
             elif isinstance(content, list): # Vison API format
                 for item in content:
                     if item.get("type") == "text":
                          final_token_count += self._calculate_tokens(item.get("text", ""))
             # Note: Image token cost is model-specific and not calculated here.

        # Add system prompt tokens if they aren't already in the message list (standard mode)
        if self.system_prompt_mode == 'standard':
            final_token_count += self.system_prompt_tokens

        self._print_context_debug(context_messages, final_token_count) # Show what's being sent

        # Final check against theoretical max tokens (minus buffer for response)
        # This check is approximate because image tokens aren't counted.
        if final_token_count >= self.max_total_tokens:
             print(f"WARNING: Estimated text token count ({final_token_count}) is close to or exceeds limit ({self.max_total_tokens}). Prompt might be truncated by API.")
             # Proceed, but be aware. A stricter check could abort here.
             # return None

        try:
            print(f"🧠 Invoking LLM (Model: {self.llm_api_model})...")
            start_llm_time = time.monotonic()
            response = self.llm_client.chat.completions.create(
                model=self.llm_api_model,
                messages=context_messages,
                max_tokens=self.max_llm_response_tokens, # Limit response length
                timeout=self.api_timeout_seconds,      # API call timeout from config
                # Optional common parameters (can be added to .env too)
                # temperature=get_env_float('LLM_TEMPERATURE', 0.7),
                # top_p=get_env_float('LLM_TOP_P', 1.0),
            )
            end_llm_time = time.monotonic()
            llm_duration = end_llm_time - start_llm_time

            # Validate response structure
            if (response and response.choices and len(response.choices) > 0 and
                    response.choices[0].message and response.choices[0].message.content):

                gpt_content = response.choices[0].message.content.strip()
                finish_reason = response.choices[0].finish_reason

                # Log usage details from response object
                prompt_tokens = response.usage.prompt_tokens if response.usage else 'N/A'
                completion_tokens = response.usage.completion_tokens if response.usage else 'N/A'
                total_tokens = response.usage.total_tokens if response.usage else 'N/A'

                print(f"✅ LLM call successful ({llm_duration:.2f}s). Finish Reason: {finish_reason}")
                print(f"   LLM Token Usage: Prompt={prompt_tokens}, Completion={completion_tokens}, Total={total_tokens}")
                # print(f"   LLM Response Raw: {gpt_content[:500]}...") # Print start of raw response if needed

                # Check if response was cut off by token limit
                if finish_reason == 'length':
                    print("Warning: LLM response may have been truncated due to max_tokens limit.")

                return gpt_content
            else:
                print(f"Error: Unexpected LLM response structure or empty content.")
                print(f"Raw Response: {response}") # Log the raw response for diagnosis
                return None

        except openai.APITimeoutError as e: # Use specific exception type name 'openai.APITimeoutError'
            print(f"\n❌ Error: LLM API call timed out after {self.api_timeout_seconds} seconds.")
            print(f"   Error details: {e}")
            return None
        except openai.APIConnectionError as e:
             print(f"\n❌ Error: Could not connect to LLM API at {self.llm_api_url}.")
             print(f"   Check network connectivity and the LLM_API_URL in your .env file.")
             print(f"   Error details: {e}")
             return None
        except openai.AuthenticationError as e:
             print(f"\n❌ Error: LLM API Authentication failed. Check your LLM_API_KEY.")
             print(f"   Error details: {e}")
             return None
        except openai.RateLimitError as e:
             print(f"\n❌ Error: LLM API rate limit exceeded. Please check your plan and usage limits.")
             print(f"   Error details: {e}")
             # Consider implementing backoff/retry logic here for production
             return None
        except openai.APIStatusError as e: # Catch broader API errors (e.g., 4xx, 5xx)
             print(f"\n❌ Error: LLM API returned an error status.")
             print(f"   Status Code: {e.status_code}")
             print(f"   Response: {e.response.text[:500] if hasattr(e, 'response') and e.response else 'N/A'}")
             return None
        except Exception as e:
            # Catch any other unexpected exceptions during the API call
            print(f"\n❌ Unexpected Error during LLM API call: {e}")
            print(traceback.format_exc())
            return None

    def _parse_and_update_state(self,
                                room_id: str,
                                gpt_response_text: str,
                                full_context_this_turn: List[Dict[str, Any]] # Context *before* adding assistant response
                                ) -> Tuple[List[str], bool]:
        """
        Parses LLM response for commands, updates state (notepad, context).
        Returns list of messages to send and a boolean indicating if context was cleared.
        """
        new_notepad_notes = []
        msg_contents = []
        context_cleared = False

        # --- Special Command Handling ---
        # Check for {cls} command to clear context and notepad
        if gpt_response_text.strip() == "{cls}":
            print("Clear context command '{cls}' received. Resetting state.")
            # Reset in-memory context to initial state
            final_context = self.initial_context_message.copy() # Start fresh
            # Clear persistent storage files
            notepad_path = self._get_notepad_file_path(room_id)
            context_path = self._get_context_file_path(room_id)
            try: notepad_path.unlink(missing_ok=True)
            except OSError as e: print(f"Warning: Error removing notepad file during clear: {e}")
            try: context_path.unlink(missing_ok=True)
            except OSError as e: print(f"Warning: Error removing context file during clear: {e}")

            # Save the clean initial state
            self._save_context(room_id, final_context)
            context_cleared = True
            # Return empty messages and the cleared status (caller handles response)
            return [], context_cleared # No messages to send back

        # --- Regular Response Processing ---
        # Add the assistant's response to the context *before* saving.
        # The LLM response is expected to be a simple string here.
        gpt_response_message = {"role": "assistant", "content": gpt_response_text}

        # Append assistant response to the context that *includes* the user message from this turn
        final_recording_context = full_context_this_turn + [gpt_response_message]

        # --- Parse Commands from Response ---
        try:
            # Find notepad entries ({notepad: "..."}) - DOTALL allows matching across newlines
            new_notepad_notes = re.findall(r'{notepad:\s*"(.*?)"}', gpt_response_text, re.DOTALL | re.IGNORECASE)
            # Find messages to send ({msg_X: "..."})
            msg_contents = re.findall(r'{msg_\d+:\s*"(.*?)"}', gpt_response_text, re.DOTALL | re.IGNORECASE)
            # Find thoughts for logging ({think: "..."})
            thoughts = re.findall(r'{think:\s*"(.*?)"}', gpt_response_text, re.DOTALL | re.IGNORECASE)
            if thoughts:
                print(f"💡 LLM Thought: {thoughts[0][:200]}..." if thoughts else "No thoughts extracted.") # Log first thought

        except Exception as e:
             print(f"Error parsing commands from LLM response: {e}")
             # Continue saving context and notepad even if parsing fails for some commands

        # --- Update State ---
        # Append new notes to the persistent notepad file
        if new_notepad_notes:
            # print(f"📝 Adding {len(new_notepad_notes)} note(s) to notepad for room {room_id}.") # Reduced verbosity
            self._append_to_notepad(room_id, new_notepad_notes)

        # Save the updated *full* context (User turn + Assistant response)
        self._save_context(room_id, final_recording_context)

        # Return the extracted chat messages and the cleared status
        return msg_contents, context_cleared

    # --- Main Request Processing Method ---
    def process_request(self,
                        room_id: str,
                        audio_file_path: Path,
                        screenshot_file_path: Optional[Path] = None,
                        chat_list: Optional[List[Dict]] = None
                        ) -> Dict[str, Any]:
        """
        Main handler for a single request. Orchestrates STT, vision, LLM interaction, state updates.
        Returns a dictionary with results or error information.
        """
        start_time = time.monotonic()
        print(f"\n===== Processing request for Room ID: {room_id} at {datetime.now()} =====")

        # --- Input Validation ---
        if not room_id:
             print("Error: Missing room_id in request.")
             return {"status": "error", "message": "Missing room_id"}
        if not audio_file_path or not audio_file_path.exists():
             print(f"Error: Invalid or missing audio file path: {audio_file_path}")
             return {"status": "error", "message": f"Invalid or missing audio file path"}
        # Ensure chat_list is a list, default to empty list if missing or invalid type
        if chat_list is None:
             chat_list = []
        elif not isinstance(chat_list, list):
            print(f"Warning: Received non-list 'chats' data (type: {type(chat_list)}), defaulting to empty list.")
            chat_list = []

        # --- 1. Speech Recognition ---
        print("--- Step 1: Speech Recognition ---")
        stt_youdao, stt_whisper = self._perform_speech_recognition(audio_file_path)

        # Handle STT comparison mode (set by CLI flag --compare-speech-recognition)
        if self.stt_comparison_mode:
             print("--- STT Comparison Mode Active: Exiting after STT ---")
             processing_time = time.monotonic() - start_time
             print(f"===== Request (Comparison Mode) for Room {room_id} finished in {processing_time:.2f} seconds =====")
             return {
                 "status": "success", "mode": "comparison",
                 "recognized_text_youdao": stt_youdao,
                 "recognized_text_whisper": stt_whisper,
                 "processing_time_seconds": round(processing_time, 2)
             }

        # --- 2. Image Processing (Vision) ---
        print("--- Step 2: Image Processing (Vision) ---")
        image_url = None
        if self.enable_vision and screenshot_file_path and screenshot_file_path.exists():
             # print(f"Vision enabled. Processing screenshot: {screenshot_file_path.name}") # Reduced verbosity
             if self.vision_upload_provider == 'cloudinary':
                 image_url = self._upload_screenshot_to_cloudinary(screenshot_file_path, room_id)
                 if not image_url:
                     print("Warning: Cloudinary upload failed or was skipped due to config issues. Proceeding without image.")
             elif self.vision_upload_provider == 'none':
                  print("Info: Vision upload provider is 'none'. Screenshot not uploaded.")
             else:
                  print(f"Warning: Unsupported vision upload provider '{self.vision_upload_provider}'. No upload performed.")
        elif self.enable_vision:
             print("Vision enabled, but no valid screenshot file provided or found in this request.")
        # else:
            # print("Vision disabled. Skipping image processing.") # Reduced verbosity

        # --- 3. Build LLM Prompt ---
        print("--- Step 3: Building LLM Prompt ---")
        context_to_send = self._build_llm_prompt(
            room_id, chat_list, stt_youdao, stt_whisper, image_url
            )

        # --- 4. Invoke LLM ---
        print("--- Step 4: Invoking LLM ---")
        gpt_response_text = self._invoke_llm(context_to_send, room_id=room_id)

        # Handle LLM call failure
        if gpt_response_text is None:
            print("LLM invocation failed. Ending request processing with error.")
            processing_time = time.monotonic() - start_time
            print(f"===== Request for Room ID {room_id} finished with LLM ERROR in {processing_time:.2f} seconds =====")
            return {"status": "error", "message": "LLM response generation failed"}

        # print(f"\n🎯 Raw LLM Response (Room {room_id}):\n{gpt_response_text}") # Log full response

        # --- 5. Parse Response & Update State ---
        print("--- Step 5: Parsing Response and Updating State ---")
        # Pass the context *before* the assistant's response was added
        msg_contents, context_cleared = self._parse_and_update_state(
            room_id, gpt_response_text, context_to_send
            )

        if context_cleared:
             print("State cleared by {cls} command.")
             # Optionally modify response to client
             # msg_contents = ["Context Cleared by Operator"] # Example

        # --- 6. Prepare and Return Result ---
        print("--- Step 6: Preparing Final Response ---")
        end_time = time.monotonic()
        processing_time = end_time - start_time
        print(f"===== Request for Room ID {room_id} finished successfully in {processing_time:.2f} seconds =====")

        return {
            # Status and core results
            "status": "success",
            "msg_contents": msg_contents,         # Parsed {msg_x: ...} commands
            "context_cleared": context_cleared,   # Indicate if {cls} was processed

            # Diagnostic / informational fields (optional for client)
            "recognized_text_youdao": stt_youdao, # Include STT results for logging/debugging
            "recognized_text_whisper": stt_whisper,
            "image_url": image_url,               # Uploaded image URL (if any)
            "LLM_response_raw": gpt_response_text,# Full raw response from LLM
            "processing_time_seconds": round(processing_time, 2)
        }

# --- Flask Application Setup ---
app = Flask(__name__)
# Configure CORS - Allow all origins for /upload for development ease.
# For production, restrict origins: origins=["http://localhost:xxxx", "https://your_userscript_source.com"]
CORS(app, resources={r"/upload": {"origins": "*"}})
print("Flask app created. CORS enabled for /upload (all origins).")

# --- Command Line Argument Parsing ---
# Only for actions that don't fit well in .env or need explicit user trigger
parser = argparse.ArgumentParser(
    description="Bilibili Live Assistant Backend Server (Configured via .env)",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter # Show defaults
)
parser.add_argument(
    '--test',
    action='store_true',
    help='Enable test mode (save files), overrides SERVER_TEST_MODE in .env'
)
parser.add_argument(
    '--check-system-tokens',
    action='store_true',
    help='Calculate and print the token count of the configured system prompt and exit.'
)
parser.add_argument(
    '--compare-speech-recognition',
    action='store_true',
    help='Run both Youdao and Whisper STT, return results, but DO NOT call the LLM. Requires relevant STT keys.'
)

cli_args = parser.parse_args()

# --- Global Server Instance ---
# Initialize the server instance *after* parsing args, so CLI overrides work.
try:
    live_server = LiveAssistantServer(cli_args)
except ValueError as e:
     # Catch critical configuration errors during initialization
     print(f"FATAL SERVER INIT ERROR: {e}")
     exit(1)
except Exception as e:
     # Catch other unexpected initialization errors
     print(f"FATAL UNEXPECTED SERVER INIT ERROR: {e}")
     print(traceback.format_exc())
     exit(1)

# --- Flask Routes ---
@app.route('/upload', methods=['POST'])
def handle_upload():
    """Handles file uploads and forwards the request to the core processor."""
    start_handle_time = time.monotonic()
    temp_audio_path = None
    temp_screenshot_path = None
    scoped_room_id = "N/A" # For logging clarity in case of early failure

    try:
        # --- Basic Request Validation ---
        if 'audio' not in request.files:
            print("Upload Error: 'audio' file part missing.")
            abort(400, description="Missing 'audio' file part in the request.")
        audio_file_storage = request.files['audio']
        if not audio_file_storage.filename:
             print("Upload Error: Received audio file part with no filename.")
             abort(400, description="Received audio file part with no filename.")

        # Get mandatory room ID
        room_id_form = request.form.get('roomId')
        if not room_id_form or not room_id_form.strip():
             print("Upload Error: 'roomId' form data missing or empty.")
             abort(400, description="Missing or empty 'roomId' form data.")
        scoped_room_id = room_id_form.strip() # Use sanitized ID for logging

        # --- Summary Debug Output ---
        try:
            audio_size_kb = len(audio_file_storage.read()) / 1024
            audio_file_storage.seek(0)  # 重要！重置游标，确保后面 .save() 有效

            screenshot_file = request.files.get('screenshot')
            screenshot_size_kb = len(screenshot_file.read()) / 1024 if screenshot_file else 0
            if screenshot_file:
                screenshot_file.seek(0)

            chat_list_str = request.form.get('chats', '[]')
            chat_list_len = len(json.loads(chat_list_str)) if chat_list_str else 0

            print(f"[Upload Info] Room ID: {scoped_room_id}")
            print(f"  📦 Audio: {audio_file_storage.filename} | {audio_size_kb:.1f} KB")
            print(f"  🖼️ Screenshot: {screenshot_file.filename if screenshot_file else 'None'} | {screenshot_size_kb:.1f} KB")
            print(f"  💬 chats: {chat_list_len} 条")
        except Exception as e:
            print(f"Warning: Failed to print upload summary info: {e}")

        # print(f"\n--- Incoming POST /upload for Room {scoped_room_id} ---") # Reduced verbosity

        # --- Securely Save Uploaded Files Temporarily ---
        # Audio File
        suffix = Path(audio_file_storage.filename).suffix or '.webm' # Keep extension
        with tempfile.NamedTemporaryFile(delete=False, prefix=AUDIO_TEMP_PREFIX, suffix=suffix) as temp_audio_file:
            audio_file_storage.save(temp_audio_file.name)
            temp_audio_path = Path(temp_audio_file.name)
            # print(f"Saved temporary audio: {temp_audio_path}") # Reduced verbosity

        # Screenshot File (Optional, only if vision enabled)
        if live_server.enable_vision:
            screenshot_file_storage = request.files.get('screenshot') # Get safely
            if screenshot_file_storage and screenshot_file_storage.filename:
                suffix_ss = Path(screenshot_file_storage.filename).suffix or '.jpg' # Keep extension
                with tempfile.NamedTemporaryFile(delete=False, prefix=SCREENSHOT_TEMP_PREFIX, suffix=suffix_ss) as temp_ss_file:
                    screenshot_file_storage.save(temp_ss_file.name)
                    temp_screenshot_path = Path(temp_ss_file.name)
                    # print(f"Saved temporary screenshot: {temp_screenshot_path}") # Reduced verbosity
            # else:
                # print("No screenshot file found in request or filename missing.") # Reduced verbosity

        # --- Extract Chat List (from 'chats' field) ---
        chat_list_str = request.form.get('chats', '[]') # Default to empty JSON list string
        chat_list = [] # Default to empty list
        try:
            chat_list = json.loads(chat_list_str)
            if not isinstance(chat_list, list):
                 print(f"Warning: Decoded 'chats' data is not a list (type: {type(chat_list)}). Using empty list.")
                 chat_list = []
            # Optional: Limit chat list size here if needed before processing
            # max_chats = 50
            # if len(chat_list) > max_chats:
            #     print(f"Warning: Received large chat list ({len(chat_list)} items), truncating to last {max_chats}.")
            #     chat_list = chat_list[-max_chats:]
        except json.JSONDecodeError:
            print(f"Warning: Could not decode 'chats' JSON string: '{chat_list_str[:100]}...'. Using empty list.")
            chat_list = []
        # print(f"Received {len(chat_list)} chat messages (chats).") # Reduced verbosity

        # --- Delegate to Core Processing Logic ---
        result = live_server.process_request(
            room_id=scoped_room_id,
            audio_file_path=temp_audio_path,
            screenshot_file_path=temp_screenshot_path, # Will be None if not found/enabled
            chat_list=chat_list
        )

        # --- Test Mode: Save Files Permanently ---
        # Use the server's 'enable_test_mode' which respects .env + CLI override
        if live_server.enable_test_mode:
             request_uuid = uuid.uuid4().hex[:8] # Shorter UUID for filenames
             timestamp_save = datetime.now().strftime('%Y%m%d_%H%M%S')
             print(f"Test Mode: Saving artifacts for request {request_uuid}")
             save_dir = live_server.test_dir / scoped_room_id
             save_dir.mkdir(parents=True, exist_ok=True)

             base_filename = f"{timestamp_save}_{request_uuid}"

             # Save Audio
             if temp_audio_path and temp_audio_path.exists():
                  test_audio_dest = save_dir / f"{base_filename}{temp_audio_path.suffix}"
                  shutil.copy(temp_audio_path, test_audio_dest)
                  print(f"Saved test audio: {test_audio_dest.relative_to(Path.cwd())}")

             # Save Screenshot (if exists)
             if temp_screenshot_path and temp_screenshot_path.exists():
                  test_screenshot_dest = save_dir / f"{base_filename}{temp_screenshot_path.suffix}"
                  shutil.copy(temp_screenshot_path, test_screenshot_dest)
                  print(f"Saved test screenshot: {test_screenshot_dest.relative_to(Path.cwd())}")

                  # Also save to the specific uploaded_screenshots dir if using Cloudinary (for reference)
                  # if live_server.vision_upload_provider == 'cloudinary':
                  #     ts_dest_cloud = live_server.screenshot_upload_dir / f"{base_filename}{temp_screenshot_path.suffix}"
                  #     shutil.copy(temp_screenshot_path, ts_dest_cloud)

             # Save Request Info and Result as JSON
             request_info = {
                 'request_id': request_uuid,
                 'room_id': scoped_room_id,
                 'timestamp': datetime.now().isoformat(),
                 'form_data': dict(request.form), # Save form data
                 'files_received': {
                     'audio': audio_file_storage.filename if audio_file_storage else None,
                     'screenshot': request.files['screenshot'].filename if 'screenshot' in request.files else None
                 },
                 'processing_result': result # Include the full result dict
             }
             info_path = save_dir / f"{base_filename}_info.json"
             try:
                with info_path.open('w', encoding='utf-8') as f_info:
                    json.dump(request_info, f_info, indent=2, ensure_ascii=False) # Indent 2 for smaller files
                print(f"Saved request info: {info_path.relative_to(Path.cwd())}")
             except Exception as e:
                 print(f"Error saving request info JSON: {e}")

        return jsonify(result) # Return the processing result as JSON

    except Exception as e:
        # Catch-all for unexpected errors during request handling
        print(f"FATAL Error handling upload request for room {scoped_room_id}: {e}")
        print(traceback.format_exc())
        # Return a generic 500 error to the client
        abort(500, description="Internal server error processing your request.")

    finally:
        # --- Cleanup Temporary Files ---
        # Ensure temp files are deleted regardless of success or failure
        if temp_audio_path and temp_audio_path.exists():
            try: temp_audio_path.unlink()
            except Exception as e: print(f"Error removing temp audio {temp_audio_path}: {e}")
        if temp_screenshot_path and temp_screenshot_path.exists():
            try: temp_screenshot_path.unlink()
            except Exception as e: print(f"Error removing temp screenshot {temp_screenshot_path}: {e}")

        end_handle_time = time.monotonic()
        # print(f"--- Request handler for room {scoped_room_id} finished in {end_handle_time - start_handle_time:.3f} seconds ---") # Redundant with process_request log

# --- Main Execution Block ---
if __name__ == '__main__':
    # Handle one-off command-line actions first
    if cli_args.check_system_tokens:
        print("--- System Prompt Token Check ---")
        # Access the already initialized server instance
        print(f"System Prompt Content Source: {'File' if live_server.system_prompt_path else 'Default'}")
        print(f"System Prompt (~{live_server.system_prompt_tokens} tokens for model '{live_server.llm_tokenizer_model}'):\n-------START-------\n{live_server.system_prompt_content}\n--------END--------")
        exit(0) # Exit after checking tokens

    # Proceed with starting the server
    print("\n--- Starting Flask Server ---")
    # Get server settings from environment variables
    host = get_env_str('SERVER_HOST', '0.0.0.0')
    port = get_env_int('SERVER_PORT', 8181)
    enable_ssl = get_env_bool('SERVER_ENABLE_SSL', False)
    ssl_context_tuple = None

    if enable_ssl:
        print("SSL is ENABLED via SERVER_ENABLE_SSL=true in .env.")
        cert_path_str = get_env_str("SSL_CERT_PATH")
        key_path_str = get_env_str("SSL_KEY_PATH")
        cert_path = Path(cert_path_str) if cert_path_str else None
        key_path = Path(key_path_str) if key_path_str else None

        if cert_path and key_path and cert_path.is_file() and key_path.is_file():
            ssl_context_tuple = (str(cert_path), str(key_path))
            print(f"SSL configured using cert: {cert_path}, key: {key_path}")
            print(f"Server starting on HTTPS://{host}:{port}")
        else:
            print("ERROR: SSL enabled BUT SSL_CERT_PATH or SSL_KEY_PATH is invalid or missing in .env.")
            print(f"  Cert Path: '{cert_path_str}' (Exists: {cert_path.is_file() if cert_path else 'N/A'})")
            print(f"  Key Path: '{key_path_str}' (Exists: {key_path.is_file() if key_path else 'N/A'})")
            print("Server startup aborted due to SSL configuration error.")
            exit(1) # Exit if SSL is enabled but files are missing
    else:
        print("SSL is DISABLED (SERVER_ENABLE_SSL is false or not set in .env).")
        print(f"Server starting on HTTP://{host}:{port}")

    # Determine if Flask debug mode should be enabled (NOT recommended for production)
    flask_debug_mode = get_env_bool("FLASK_DEBUG_MODE", False)
    if flask_debug_mode:
        print("Warning: Flask debug mode is enabled via FLASK_DEBUG_MODE=true. Do not use in production!")

    # Run the Flask development server
    # Use a production-ready WSGI server (like Gunicorn or Waitress) for deployment
    try:
        # Use debug=flask_debug_mode, use_reloader=flask_debug_mode
        # Reloader helps in development but consumes more resources
        app.run(host=host, port=port, ssl_context=ssl_context_tuple, debug=flask_debug_mode, use_reloader=flask_debug_mode)
    except OSError as e:
        if ("address already in use" in str(e).lower()) or ("仅允许使用一次每个套接字地址" in str(e)): # Check common error messages
             print(f"FATAL STARTUP ERROR: Port {port} is already in use on host {host}.")
             print("Please check if another instance of the server is running or if another application is using this port.")
        else:
             print(f"FATAL STARTUP ERROR: Could not start Flask server due to an OS error: {e}")
        print(traceback.format_exc())
        exit(1)
    except Exception as start_error:
        print(f"FATAL STARTUP ERROR: An unexpected error occurred while starting Flask server: {start_error}")
        print(traceback.format_exc())
        exit(1)