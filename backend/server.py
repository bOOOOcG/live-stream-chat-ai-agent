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
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image

import atexit

import logging

# 获取日志记录器实例 (假设已在别处配置)
logger = logging.getLogger(__name__)

# 设置根 logger 的日志级别
logging.basicConfig(
    level=logging.INFO,  # 显示 INFO、WARNING、ERROR、CRITICAL 日志
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

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
"You are an autonomous chat agent for live streaming platforms. You must strictly follow the rules below:"
""
"1. Each input is a transcription of approximately 30 seconds of the streamer's speech. It may contain recognition errors, missing context, or background music/lyrics. Use your judgment to interpret it."
"2. Your output must follow a strict JSON object format with the following optional fields:"
"    - \"continues\": x — Used when you choose not to send any message. x represents the number of consecutive silent turns."
"    - \"msg_0\", \"msg_1\", \"msg_2\": Chat messages to be sent. 0–2 messages per turn, preferably under 20 characters each."
"    - \"think\": Internal thoughts for reasoning and analysis. Not visible to the public."
"    - \"notepad\": Long-term memory notes to help you interact better over time. Notes must be concise and self-contained (no multi-line or continued notes)."
"    You may omit any field you don't need. For example, if you don’t want to send messages, include only continues/think/notepad."
"3. Chat messages must be natural, concise, and meaningful. Avoid empty or repetitive phrases."
"4. If someone appears to be speaking to you, try to interpret and respond appropriately."
"5. Avoid political topics and do not reveal internal mechanisms (e.g., transcription processes)."
"6. Messages should match the language used in the stream’s chat environment."
"7. Control your message frequency: no more than 3 messages every 2 turns to avoid spamming."
"8. Do not talk to yourself repeatedly. Engage with the chat or ongoing conversations instead."
"9. Never reveal that you can't see the video. Avoid guessing the streamer’s emotion or actions from audio alone."
"10. Use the chat list (viewer messages) for context. You may respond to other viewers."
"11. If asked for commercial services (e.g., gift requests), reply with: 'I currently don't support that feature.'"
"12. If mistaken for a bot, explain your behavior in a natural and human-like manner."
"13. If lyrics, music, or song titles are detected, be cautious and don’t misinterpret them as the streamer’s speech."
"14. Chatting with the audience is encouraged to reduce errors and stay context-aware."
"15. Avoid sending multiple messages with identical structures (e.g., several questions or exclamations in a row)."
""
"Example response:"
"{"
"    \"continues\": 0,"
"    \"think\": \"The transcript may include lyrics or noise, but it seems the streamer mentioned liking pineapple buns.\","
"    \"msg_0\": \"pineapple bun sounds awesome\","
"    \"notepad\": \"This stream often has BGM that can confuse ASR; streamer likes pineapple buns.\""
"}"
""
"You must respond strictly using this format and comply with all rules above."
)

NOTEPAD_OPTIMIZATION_PROMPT_TEMPLATE = """
You are an AI assistant helping another AI agent manage and optimize its long-term memory stored in a notepad.

**Background:** The system prompt above defines the personality and rules for the AI agent you are supporting. Think of this as editing and cleaning up its memory.

Your task is to clean, compress, and optimize the following notepad entries from a specific live stream environment.

**Guidelines:**

1. **Compress & Merge:** Combine related notes into concise bullet points.
2. **Prioritize Key Information:** Focus on critical points related to:
    * Direct behavioral instructions or rules (e.g., how to respond, how fast to chat, known usernames).
    * Important facts about the streamer or regular viewers (preferences, repeated topics).
    * Promises or actions the AI has previously made.
3. **Refine Language:** Shorten and simplify wording without losing meaning. Remove filler words.
4. **Remove Redundancy:** Delete repeated or duplicate information.
5. **Filter Out Minor Details:** Remove outdated or trivial observations unless they reflect a clear pattern. When unsure, lean toward keeping it, but compress it.
6. **Keep Plain Text Format:** Output should be plain text only. One note per line. No JSON, explanations, or extra formatting.

**Original Notepad:**
--- START NOTES ---
{original_notes}
--- END NOTES ---

**Optimized Notepad (Output only one note per line):**
"""

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

        # Initialize thread pool for background tasks (like notepad optimization)
        # 初始化用于后台任务（如Notepad优化）的线程池
        # max_workers 可以根据需要调整，一般 2-4 个足够处理优化任务
        self.optimization_executor = ThreadPoolExecutor(max_workers=int(os.getenv("OPTIMIZATION_WORKERS", 2)), thread_name_prefix='Optimizer_')
        # Set to keep track of rooms currently undergoing optimization
        # 用于跟踪当前正在进行优化的房间的集合
        self.optimizing_rooms = set()
        # self.optimizing_room_lock = Lock() # 如果使用 Lock 替代 set
        print(f"Background optimization executor initialized (Workers: {self.optimization_executor._max_workers}).")

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
        self.llm_optimize_timeout_seconds = int(os.getenv("LLM_OPTIMIZE_TIMEOUT_SECONDS", 180))
        print(f"LLM Config: API_Model='{self.llm_api_model}', Tokenizer='{self.llm_tokenizer_model}', MaxRespTokens={self.max_llm_response_tokens}, Timeout={self.api_timeout_seconds}s, OptimizeTimeout={self.llm_optimize_timeout_seconds}s")

        # Token Limits
        self.max_total_tokens = get_env_int('PROMPT_MAX_TOTAL_TOKENS', 4096)
        self.max_notepad_tokens_in_prompt = get_env_int('PROMPT_MAX_NOTEPAD_TOKENS', 712)
        self.max_chatlist_tokens_in_prompt = get_env_int('PROMPT_MAX_CHATLIST_TOKENS', 256)
        self.llm_max_optimize_resp_tokens = int(os.getenv('LLM_MAX_OPTIMIZE_RESP_TOKENS', '4096'))
        print(f"Token Limits: TotalPrompt={self.max_total_tokens}, NotepadInPrompt={self.max_notepad_tokens_in_prompt}, ChatlistInPrompt={self.max_chatlist_tokens_in_prompt}, OptimizeRespTokens={self.llm_max_optimize_resp_tokens}")

        # Notepad Auto Optimization Config
        self.notepad_auto_optimize_enabled = get_env_bool('NOTEPAD_AUTO_OPTIMIZE_ENABLE', False)
        self.notepad_auto_optimize_threshold_tokens = get_env_int('NOTEPAD_AUTO_OPTIMIZE_THRESHOLD_TOKENS', 2500) # Example threshold
        print(f"Notepad Auto-Optimize: Enabled={self.notepad_auto_optimize_enabled}, Threshold={self.notepad_auto_optimize_threshold_tokens} tokens")
        if self.notepad_auto_optimize_enabled and self.notepad_auto_optimize_threshold_tokens <= self.max_notepad_tokens_in_prompt:
            print(f"Warning: NOTEPAD_AUTO_OPTIMIZE_THRESHOLD_TOKENS ({self.notepad_auto_optimize_threshold_tokens}) should generally be larger than PROMPT_MAX_NOTEPAD_TOKENS ({self.max_notepad_tokens_in_prompt}) to avoid frequent optimizations.")

        # STT Config
        self.stt_provider = get_env_str('STT_PROVIDER', 'whisper').lower()
        if self.stt_provider not in ['youdao', 'whisper', 'both']:
             print(f"Warning: Invalid STT_PROVIDER '{self.stt_provider}' in .env. Valid options: 'youdao', 'whisper', 'both'. Defaulting to 'whisper'.")
             self.stt_provider = 'whisper'
        self.youdao_app_key = get_env_str("YOUDAO_APP_KEY")
        self.youdao_app_secret = get_env_str("YOUDAO_APP_SECRET")
        self.youdao_api_url = get_env_str('YOUDAO_API_URL', 'https://openapi.youdao.com/asrapi')
        # Whisper专用API（如果没有设置就回退到 LLM通用API）
        self.whisper_api_url = get_env_str("WHISPER_API_URL", self.llm_api_url)
        self.whisper_api_key = get_env_str("WHISPER_API_KEY", self.llm_api_key)

        print(f"Whisper Config: URL='{self.whisper_api_url}', Key={'Set' if self.whisper_api_key else 'Not Set'}")
        
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
        # for i, msg in enumerate(context_messages):
        #     role = msg.get("role", "unknown")
        #     content = msg.get("content", "")
        #     content_repr = ""
        #     if isinstance(content, list): # Handle Vison API format
        #         parts = []
        #         for item in content:
        #             item_type = item.get("type")
        #             if item_type == "text":
        #                 parts.append(f"Text: '{item.get('text', '')[:100]}...'")
        #             elif item_type == "image_url":
        #                 url = item.get('image_url', {}).get('url', '')
        #                 parts.append(f"Image: '{url[:50]}...'")
        #             else:
        #                 parts.append(f"{str(item)[:100]}...")
        #         content_repr = "[" + ", ".join(parts) + "]"
        #     elif isinstance(content, str):
        #         content_repr = f"'{content[:150]}...'"
        #     else:
        #         content_repr = f"{str(content)[:150]}..."
        #     print(f"  [{i}] Role: {role:<9} Content: {content_repr}")
        # print("-" * 20)

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
    
    def _get_notepad_total_tokens(self, room_id: str) -> int:
        """
        Reads the entire notepad file for a room and calculates its total token count.
        读取指定房间的整个 Notepad 文件并计算其总 Token 数量。

        Returns:
            int: The total token count, or 0 if the file doesn't exist or is empty/unreadable.
                 总 Token 数，如果文件不存在、为空或不可读则返回 0。
        """
        file_path = self._get_notepad_file_path(room_id)
        if not file_path.exists():
            return 0

        try:
            content = file_path.read_text(encoding="utf-8")
            if not content.strip():
                return 0
            return self._calculate_tokens(content)
        except Exception as e:
            print(f"Error reading or calculating tokens for full notepad (room {room_id}): {e}")
            return 0 # Return 0 on error to avoid triggering optimization incorrectly

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

    def optimize_notepad(self, room_id: str) -> Dict[str, Any]:
        """
        使用 LLM 优化指定 room 的记事本内容，并直接覆盖文件（含备份）。
        返回一个 dict，包含 status、message、optimized_content_preview、processing_time_seconds。
        """
        start = time.monotonic()
        notepad_path = self._get_notepad_file_path(room_id)

        if not notepad_path.exists():
            return {"status": "error", "message": "Notepad file not found."}

        # 读取原始内容
        try:
            original = notepad_path.read_text(encoding='utf-8')
            if not original.strip():
                return {"status": "success", "message": "Notepad was empty, skipped."}
        except Exception as e:
            return {"status": "error", "message": f"Error reading notepad: {e}"}

        # 构建优化提示
        sys_prompt = self.system_prompt_content or ""
        prompt = NOTEPAD_OPTIMIZATION_PROMPT_TEMPLATE.format(original_notes=original)
        msgs = []
        if sys_prompt:
            msgs.append({"role":"system","content":
                         f"You are optimizing notes for an AI assistant. Persona:\n---\n{sys_prompt}\n---"})
        msgs.append({"role":"user","content": prompt})

        # 调用 LLM
        optimized = self._invoke_llm(
            msgs,
            room_id=room_id,
            max_tokens_override=self.llm_max_optimize_resp_tokens
        )
        if optimized is None:
            return {"status": "error", "message": "LLM generation failed."}

        optimized = optimized.strip()
        # 备份并写回
        backup = notepad_path.with_suffix(f'.bak.{time.strftime("%Y%m%d%H%M%S")}')
        shutil.copy2(notepad_path, backup)
        notepad_path.write_text(optimized, encoding='utf-8')

        elapsed = time.monotonic() - start
        preview = optimized[:200] + ("..." if len(optimized)>200 else "")
        return {
            "status": "success",
            "message": f"Optimized notepad for room {room_id}.",
            "optimized_content_preview": preview,
            "processing_time_seconds": round(elapsed,2)
        }
    
    def _run_notepad_optimization(self, room_id: str) -> str:
        """
        Worker function executed in the background thread to optimize notepad.
        在后台线程中执行的 Notepad 优化工作函数。

        Logs results and handles exceptions. Always returns the room_id for cleanup.
        记录结果并处理异常。始终返回 room_id 以便清理。

        Args:
            room_id: The ID of the room whose notepad needs optimization.
                     需要优化 Notepad 的房间 ID。

        Returns:
            str: The room_id that was processed.
                 处理过的 room_id。
        """
        scoped_logger = logging.getLogger(__name__).getChild(f"Optimizer(Room:{room_id})")
        scoped_logger.info(f"Starting background notepad optimization...")
        start_time = time.monotonic()
        try:
            # Call the existing optimization logic
            # 调用现有的优化逻辑
            result = self.optimize_notepad(room_id)
            duration = time.monotonic() - start_time
            status = result.get('status', 'unknown')
            message = result.get('message', 'No message returned.')
            scoped_logger.info(f"Optimization finished in {duration:.2f}s. Status: {status}. Message: {message}")
        except Exception as e:
            duration = time.monotonic() - start_time
            scoped_logger.error(f"EXCEPTION during background notepad optimization after {duration:.2f}s: {e}")
            scoped_logger.error(traceback.format_exc())
        finally:
            # Crucial: Always return the room_id so the callback knows which room finished.
            # 关键：始终返回 room_id，以便回调函数知道哪个房间完成了。
            return room_id

    def _optimization_task_done(self, future: Future):
        """
        Callback function executed when a notepad optimization task completes (success or failure).
        当 Notepad 优化任务完成（成功或失败）时执行的回调函数。

        Removes the room_id from the `optimizing_rooms` set to allow future optimizations.
        从 `optimizing_rooms` 集合中移除 room_id，以允许未来的优化。

        Args:
            future: The Future object representing the completed task.
                    代表已完成任务的 Future 对象。
        """
        room_id = None
        try:
            # Get the room_id returned by _run_notepad_optimization
            # 获取 _run_notepad_optimization 返回的 room_id
            room_id = future.result() # This might re-raise exceptions caught *within* optimize_notepad if not handled there

            # Log if the task itself raised an exception *not* caught internally
            # 如果任务本身抛出了未在内部捕获的异常，则记录日志
            exc = future.exception()
            if exc:
                 # Logged inside _run_notepad_optimization already, but good to confirm here.
                 logger.error(f"[Optimizer Callback Room {room_id or 'Unknown'}] Task indicated failure with exception: {exc}")

            # Optional: Log successful completion indication from callback side
            # logger.info(f"[Optimizer Callback Room {room_id or 'Unknown'}] Task completed processing.")

        except Exception as e:
            # Catch errors during future.result() or future.exception() calls
            # 捕获调用 future.result() 或 future.exception() 期间的错误
            # We might not know the room_id if future.result() failed badly
            logger.error(f"[Optimizer Callback Room {room_id or 'Unknown'}] Error in optimization 'done' callback itself: {e}")
        finally:
            # --- CRITICAL SECTION ---
            # Ensure the room is removed from the tracking set, regardless of task success/failure.
            # 无论任务成功与否，确保从跟踪集合中移除该房间。
             # --- 使用集合进行并发控制 ---
            if room_id and room_id in self.optimizing_rooms:
                try:
                    self.optimizing_rooms.remove(room_id)
                    logger.info(f"[Optimizer Callback Room {room_id}] Optimization lock released.")
                except KeyError:
                     # Should not happen if logic is correct, but good to log defensively
                     logger.warning(f"[Optimizer Callback Room {room_id}] Tried to release lock, but room was not found in the set. (Possibly already removed?)")
            elif room_id:
                # If room_id was retrieved but wasn't in the set (e.g., callback ran twice?)
                logger.warning(f"[Optimizer Callback Room {room_id}] Task finished, but room was not marked as optimizing in the set.")
            else:
                # If we couldn't even get the room_id (serious error in task or callback)
                logger.error("[Optimizer Callback] Cannot release lock: room_id is unknown due to failure retrieving task result.")
            # --- 如果使用 Lock ---
            # # Alternative using Lock (need self.optimizing_room_lock initialized)
            # # with self.optimizing_room_lock:
            # #     if room_id in self.optimizing_rooms:
            # #         self.optimizing_rooms.remove(room_id)
            # #         logger.info(f"[Optimizer Callback Room {room_id}] Optimization lock released.")
            # #     # Handle cases where room_id is missing or not in set as above

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

    def _load_trimmed_context_history(self, 
                                      room_id: str, 
                                      reserved_tokens_for_current_input: int,
                                      tokens_notepad_system: int # 新增参数
                                      ) -> List[Dict[str, Any]]:
        """
        Loads historical context, trimming older messages to fit the available token budget.
        The budget accounts for the main system prompt, the notepad system message, 
        and the space reserved for the current input. Excludes system prompts themselves during trimming.
        
        Args:
            room_id: The ID of the room.
            reserved_tokens_for_current_input: Tokens reserved for the current user message (text + buffer).
            tokens_notepad_system: Tokens consumed by the separate notepad system message.
            
        Returns:
            A list of historical user/assistant messages fitting the budget.
        """
        file_path = self._get_context_file_path(room_id)
        if not file_path.exists():
            return []

        try:
            with file_path.open('r', encoding='utf-8') as f:
                # Load the full history including system prompt etc.
                full_context_history = json.load(f)
                # Filter out ALL system prompts here before trimming
                history_to_trim = [msg for msg in full_context_history if msg.get("role") != "system"]
        except Exception as e:
            print(f"Error loading or parsing context file for room {room_id}: {e}. Starting with fresh context.")
            return []

        # --- 修改预算计算 ---
        # Budget = Max Total - MainSystem - NotepadSystem - ReservedForCurrentInput
        token_budget = self.max_total_tokens - self.system_prompt_tokens - tokens_notepad_system - reserved_tokens_for_current_input
        
        if token_budget <= 0:
            print(f"Warning: No token budget remaining for history (Budget: {token_budget}). Max: {self.max_total_tokens}, MainSys: {self.system_prompt_tokens}, NotepadSys: {tokens_notepad_system}, Reserved: {reserved_tokens_for_current_input}")
            return []

        trimmed_history = []
        current_tokens = 0

        # Iterate history in reverse (newest first)
        for msg in reversed(history_to_trim):
            # Skip any messages marked as temporary or special internal flags if needed
            if msg.get("is_temp"): continue

            msg_tokens = 0
            content = msg.get("content")
            if isinstance(content, list): # Handle vision messages in history (count text only as requested)
                msg_tokens = sum(self._calculate_tokens(item.get("text", ""))
                                 for item in content if item.get("type") == "text")
                # >>> important: We are IGNORING image tokens in history as requested <<<
            elif isinstance(content, str):
                msg_tokens = self._calculate_tokens(content)

            if msg_tokens == 0: continue # Skip empty or unprocessable messages

            if current_tokens + msg_tokens <= token_budget:
                trimmed_history.insert(0, msg) # Add to beginning to maintain order
                current_tokens += msg_tokens
            else:
                # Print message indicating why trimming stopped
                # print(f"History trimming stopped: Adding message ({msg_tokens} tokens) would exceed budget ({current_tokens}/{token_budget}). Message content: {str(content)[:50]}...")
                break # Stop when budget is full

        # 在函数退出前打印加载结果，方便调试
        print(f"📦 Loaded context history for room {room_id}: {len(trimmed_history)} messages, ~{current_tokens} tokens (Budget for history: {token_budget})")
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
        if not self.whisper_api_key or not self.whisper_api_url:
            print("Cannot perform Whisper STT: Whisper API Key or URL is missing.")
            return None

        # Construct the specific API endpoint for audio transcriptions
        # Handle potential trailing slashes in the base URL
        base_url = self.whisper_api_url.rstrip('/')
        api_url = f'{base_url}/audio/transcriptions'
        headers = {'Authorization': f'Bearer {self.whisper_api_key}'}

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
                          streamer_name: Optional[str],
                          current_chat_list: List[Dict[str, Any]],
                          stt_youdao: Optional[str],
                          stt_whisper: Optional[str],
                          image_url: Optional[str]) -> List[Dict[str, Any]]:
        """
        构建将要发送给 LLM API 的消息列表。

        该函数负责整合各种输入源（系统指令、房间笔记、历史对话、当前聊天、
        语音识别结果、图像信息），为当前用户回合构建结构化的文本输入，
        并计算各部分的 Token 数量（主要是文本部分）用于调试和上下文管理。

        Args:
            room_id: 当前直播间的唯一标识符。
            streamer_name: 主播的用户名。
            current_chat_list: 当前请求中包含的最新聊天/弹幕列表。
            stt_youdao: 有道语音识别服务返回的文本结果 (如果启用且成功)。
            stt_whisper: Whisper 语音识别服务返回的文本结果 (如果启用且成功)。
            image_url: 上传到图像服务器后的图像 URL (如果启用视觉且成功)。

        Returns:
            一个包含多条消息字典的列表，可以直接传递给 LLM API 的 `messages` 参数。
            每个消息字典包含 'role' 和 'content' 键。
        """
        logger = logging.getLogger(__name__) # 获取 logger 实例 (推荐)

        # --- Token 计数器初始化 ---
        # 用于追踪构建过程中各部分文本内容的 Token 消耗，以进行精确的预算管理
        tokens_main_system = 0      # 主系统提示的 Token
        tokens_notepad_system = 0   # 笔记专用系统消息的 Token
        tokens_history = 0          # 历史对话消息的 Token
        tokens_current_user_text = 0 # 当前用户回合生成的文本内容的 Token

        # --- 1. 计算主系统提示的 Token ---
        # 根据配置加载的主系统提示 ('standard' 模式) 计算其 Token 消耗。
        # 注意: 'user_message_compatibility' 模式下，系统提示作为第一条用户消息，
        # 其 Token 会包含在 history 或 initial message 中，不应在这里重复计算。
        if self.system_prompt_mode == 'standard':
            # self.system_prompt_tokens 应在 _setup_system_prompt 中预先计算好
             tokens_main_system = self.system_prompt_tokens
             # 或者，如果 self.system_prompt_message_for_api 已准备好，可实时计算：
             # tokens_main_system = sum(self._calculate_tokens(msg.get("content", ""))
             #                        for msg in self.system_prompt_message_for_api
             #                        if isinstance(msg.get("content"), str))
        # TODO: 确认并确保 user_message_compatibility 模式下涉及的 system prompt Token
        #       在其他地方（如历史加载预算）被正确考虑。

        # --- 2. 加载房间笔记并计算其专属系统消息的 Token ---
        # 笔记作为一种持久化记忆，通过一个特定的 system role 消息注入，提醒 LLM 关键信息。
        notepad_prompt_str, _ = self._load_notepad_for_prompt(room_id)
        # 构建笔记的系统消息内容
        notepad_system_content = f"以下是你记录的该直播间的笔记 记得多做笔记 因为你的记忆很短 只能靠记笔记维持记忆: {notepad_prompt_str}"
        system_notepad_message = {"role": "system", "content": notepad_system_content}
        # 计算这条特定笔记系统消息的 Token
        tokens_notepad_system = self._calculate_tokens(notepad_system_content)

        # --- 3. 格式化当前用户回合的输入信息 (时间戳、聊天、STT、图像引言) ---
        # 将当前回合的所有动态信息整合成结构化的文本。

        # 3a. 添加当前时间戳
        current_time_str = datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')
        timestamp_text = f"[当前时间]\n{current_time_str}"

        # 3b. 添加主播用户名
        streamer_name_text = f"[主播用户名]: \"{streamer_name}\""

        # 3c. 格式化聊天列表
        # _load_chat_list_for_prompt 应负责加载、截断并格式化聊天列表，并返回带标签的字符串
        chatlist_text, _ = self._load_chat_list_for_prompt(current_chat_list)
        # 示例：chatlist_text 可能返回 "{Chatlist content:\nUser1: Hello\nUser2: Hi\n}"

        # 3d. 格式化语音识别 (STT) 结果
        stt_text_parts = []
        stt_label = "[主播语音输入]" # 主标签
        provider_tag = "" # 用于记录最终使用的 provider

        # 根据配置和识别结果选择性地包含 STT 文本，并使用更友好的标签
        if self.stt_provider == 'both':
            if stt_youdao:
                stt_text_parts.append(f"  (有道识别): {stt_youdao}")
                provider_tag = "有道"
            if stt_whisper:
                stt_text_parts.append(f"  (Whisper识别): {stt_whisper}")
                provider_tag = "Whisper" if not provider_tag else "两者" # 如果两者都有，标记为两者
        elif self.stt_provider == 'whisper':
            # 优先使用 Whisper，若失败则回退到 Youdao
            if stt_whisper:
                stt_text_parts.append(f"  (Whisper识别): {stt_whisper}")
                provider_tag = "Whisper"
            elif stt_youdao: # Fallback
                stt_text_parts.append(f"  (有道识别 - 备用): {stt_youdao}")
                provider_tag = "有道(备用)"
        else: # 默认为 'youdao' 或仅配置了 'youdao'
            # 优先使用 Youdao，若失败则回退到 Whisper
            if stt_youdao:
                stt_text_parts.append(f"  (有道识别): {stt_youdao}")
                provider_tag = "有道"
            elif stt_whisper: # Fallback
                stt_text_parts.append(f"  (Whisper识别 - 备用): {stt_whisper}")
                provider_tag = "Whisper(备用)"

        stt_block_text = "" # 初始化 STT 块文本
        if stt_text_parts:
             # 如果有识别结果，构建带标签的文本块
             stt_block_text = f"{stt_label}\n" + "\n".join(stt_text_parts)
        elif (self.use_youdao_stt or self.use_whisper_stt):
             # 如果 STT 功能已开启，但本次没有识别结果
             stt_block_text = f"{stt_label}\n  (无语音输入或识别失败)"
        # else: # 如果 STT 功能未开启，stt_block_text 保持为空字符串

        # 3d. 格式化图像信息的文本引言 (仅当视觉功能启用且有图像时)
        image_preamble_text = ""
        if self.enable_vision and image_url:
            # 这个引言文本用于提示 LLM 下方将附带图像信息
            # 注意：这部分文本的 Token 会被计算，但图像本身的 Token 成本复杂且未在此计入总估算
            image_preamble_text = "[当前直播间画面信息]\n  (下方消息包含图片链接)"

        # 3e. 组合当前回合的所有文本组件
        # 将时间戳、聊天列表、STT结果、图像引言组合成一个连贯的文本输入
        current_turn_text_components = [
            timestamp_text,
            streamer_name_text, # 主播的用户名
            chatlist_text,      # 来自 _load_chat_list_for_prompt, 假设自带标签或格式
            stt_block_text,     # 构建好的 STT 文本块，自带标签
            image_preamble_text # 图像引言文本，自带标签
        ]

        # 使用双换行符分隔主要信息块，以提高可读性
        # filter(None, ...) 会移除列表中的空字符串，防止产生多余的换行符
        combined_text_for_turn = "\n\n".join(filter(None, current_turn_text_components)).strip()

        # --- 4. 计算当前用户输入文本的 Token 及所需的预留空间 ---
        # 计算上面组合好的 `combined_text_for_turn` 的 Token 数量
        tokens_current_user_text = self._calculate_tokens(combined_text_for_turn)

        # 定义一个缓冲区 Token 数量，为 LLM 的响应或其他动态变化预留空间
        # 这个值可以从环境变量配置，例如: PROMPT_RESERVED_BUFFER_TOKENS
        reserved_buffer = get_env_int('PROMPT_RESERVED_BUFFER_TOKENS', 50) # 从 env 获取，默认 50

        # 如果启用了视觉功能且有图像，需要特别注意图像的 Token 成本
        # 这里仅是文本 Token 估算，图像成本很高，可能需要大幅增加 buffer 或进行估算
        # if self.enable_vision and image_url:
        #      # 图像 Token 成本通常较高 (e.g., 数百到上千 tokens)
        #      # 这里的 buffer 可能不足以覆盖，需要考虑增大或实现图像 token 估算
        #      vision_extra_buffer = get_env_int('VISION_EXTRA_BUFFER_TOKENS', 800) # 示例: 为vision增加额外buffer
        #      reserved_buffer += vision_extra_buffer
        #      logger.warning(f"视觉功能启用，已增加 {vision_extra_buffer} Token 到预留 Buffer (总 Buffer: {reserved_buffer}). "
        #                    f"注意：这仍是估算，实际图像 Token 成本可能更高。")

        # 计算加载历史记录时需要为当前输入预留的总 Token 空间
        reserved_tokens_for_current_input = tokens_current_user_text + reserved_buffer

        # --- 5. 加载裁剪后的历史对话记录 ---
        # 调用历史记录加载函数，传入必要的预算信息，确保加载的历史记录
        # 加上系统提示、笔记、当前输入后，不超过总 Token 限制。
        logger.info(f"为当前输入(含Buffer)预留 {reserved_tokens_for_current_input} tokens, 为Notepad系统消息预留 {tokens_notepad_system} tokens。")
        history_messages = self._load_trimmed_context_history(
            room_id,
            reserved_tokens_for_current_input, # 传入为当前输入（文本+Buffer）计算的预留值
            tokens_notepad_system              # !! 传入笔记系统消息的 Token 成本
        )
        # _load_trimmed_context_history 内部会使用这些值来计算历史记录可用的精确 Token 预算:
        # history_budget = max_total_tokens - main_system_tokens - notepad_system_tokens - reserved_for_current_input

        # --- 6. 计算加载到的历史记录的 Token ---
        # 遍历返回的、裁剪后的历史消息，累加其文本内容的 Token。
        # 重要：根据设计要求，这里忽略历史消息中可能存在的图像内容的 Token 成本。
        tokens_history = 0
        for msg in history_messages:
            content = msg.get("content")
            if isinstance(content, str):
                # 标准文本消息
                tokens_history += self._calculate_tokens(content)
            elif isinstance(content, list):
                # 处理多模态消息 (通常是带图像的历史记录)
                for item in content:
                    # 只计算文本部分的 Token
                    if item.get("type") == "text":
                        tokens_history += self._calculate_tokens(item.get("text", ""))
            # >>> 注意：历史图像的 Token 成本在此被忽略 <<<

        # --- 7. 计算各项 Token 小计和总计 (文本估算) ---
        tokens_conversation_context = tokens_history + tokens_current_user_text
        tokens_total_estimated_text = tokens_main_system + tokens_notepad_system + tokens_history + tokens_current_user_text
        # ^^^ 变量名明确指出这是文本 Token 的估算值

        # --- 8. 打印详细的 Token 消耗调试信息 ---
        # 使用 logger 输出，便于问题排查和性能分析
        logger.info("\n--- 📊 LLM Prompt Token Breakdown (Text Estimate) ---")
        logger.info(f"  [1] Main System Prompt:      {tokens_main_system:>5} tokens")
        logger.info(f"  [2] Notepad System Message:  {tokens_notepad_system:>5} tokens")
        logger.info(f"  [3] History Messages:        {tokens_history:>5} tokens ({len(history_messages)} messages)")
        logger.info(f"  [4] Current User Input Text: {tokens_current_user_text:>5} tokens (Incl. Time, Labels etc.)")
        logger.info(f"  ---")
        logger.info(f"  Subtotal (History + Current):{tokens_conversation_context:>5} tokens ([3] + [4])")
        logger.info(f"  ---")
        logger.info(f"  >>> Est. TEXT Tokens Sent:   {tokens_total_estimated_text:>5} tokens ([1] + [2] + [3] + [4])")
        if image_url and self.enable_vision:
            logger.warning(f"  !!! 视觉启用且包含图片 URL，但其 Token 成本未计入上述估算 !!!")
        logger.info(f"  Configured Max Total:        {self.max_total_tokens:>5} tokens")
        # 计算基于文本估算的剩余空间
        token_diff = self.max_total_tokens - tokens_total_estimated_text
        status = "OK (Text Only)" if token_diff >= 0 else "OVER BUDGET (Based on Text!)"
        # 如果启用了视觉，对剩余空间做更保守的判断
        if image_url and self.enable_vision and token_diff < (reserved_buffer - 50): # 检查是否接近或超出（减去基础buffer）
             status += " - Risk of Image Exceeding Context!"
        logger.info(f"  Remaining Budget / Overrun:  {token_diff:>+5} tokens ({status})")
        logger.info(f"  (Note: Reserved buffer for current input: {reserved_buffer} tokens)")
        logger.info("------------------------------------------------")

        # --- 9. 组装最终发送给 LLM API 的消息列表 ---
        final_messages = []

        # 9a. 添加主系统提示消息 (如果适用 'standard' 模式)
        # self.system_prompt_message_for_api 在 'standard' 模式下包含系统提示，
        # 在 'user_message_compatibility' 模式下为空列表。
        final_messages.extend(self.system_prompt_message_for_api)

        # 9b. 添加笔记系统消息
        final_messages.append(system_notepad_message)

        # 9c. 添加裁剪后的历史对话消息
        final_messages.extend(history_messages)

        # 9d. 构建并添加当前用户回合的消息
        # 这一回合的消息可能包含文本和图像两部分
        if combined_text_for_turn or (self.enable_vision and image_url):
            content_list = [] # 用于存储用户消息的 content 部分 (列表形式)

            # 如果有文本内容，添加到 content_list
            if combined_text_for_turn:
                content_list.append({
                    "type": "text",
                    "text": combined_text_for_turn
                })

            # 如果启用了视觉且有图像 URL，添加到 content_list
            if self.enable_vision and image_url:
                # 图像部分的 Token 成本由 LLM API 计算，这里只传递 URL
                content_list.append({
                    "type": "image_url",
                    "image_url": {"url": image_url}
                })

            # 只有当 content_list 非空时，才添加这条 user 消息
            # (理论上，如果进入这个 if 分支，content_list 应该至少有一项)
            if content_list:
                final_messages.append({"role": "user", "content": content_list})

        else:
            # 处理没有新的用户输入的情况 (例如 STT 失败且聊天列表为空)
            logger.warning("当前回合没有新的文本或图像输入，主要发送历史和系统/笔记信息。")
            # 可以在这里考虑是否添加一条提示性的用户消息，例如：
            # final_messages.append({"role": "user", "content": [{"type": "text", "text": "(无新内容，请继续)"}]})
            # 如果添加，需要注意其对 Token 预算的微小影响，或接受这个误差。
            # 当前实现：不添加额外的用户消息，让 LLM 基于历史和系统提示进行响应。

        # --- 10. 返回最终构建好的消息列表 ---
        return final_messages

    def _invoke_llm(self, messages: List[Dict[str, Any]], room_id: str = "N/A", max_tokens_override: Optional[int] = None) -> Optional[str]:
        """
        使用准备好的消息调用配置好的 LLM API。
        如果提供了 max_tokens_override，则可能使用更长的特定超时时间。

        参数:
            messages (list): 符合 LLM API 规范的消息字典列表。
            room_id (str, 可选): 用于日志记录的房间 ID。
            max_tokens_override (int, 可选): 覆盖默认最大响应 token 数。

        返回:
            str 或 None: 来自 LLM 的响应内容，如果发生错误则为 None。
        """
        # 创建一个带作用域的日志记录器
        scoped_logger = logger.getChild(f"LLM_Invoke(Room:{room_id or 'Global'})")
        start_time = time.monotonic()

        if not messages:
            scoped_logger.error("Cannot invoke LLM with empty context messages.")
            return None

        # --- 确定本次调用使用的 max_tokens 和 timeout ---
        current_max_tokens = max_tokens_override if max_tokens_override is not None else self.max_llm_response_tokens
        is_optimization_call = max_tokens_override is not None # 标记这是否是一个 override 调用 (可能需要长超时)

        # **** 开始修改：条件超时逻辑 ****
        if is_optimization_call:
            # 如果 max_tokens 被覆盖了 (假设是优化调用)，使用特定的优化超时时间
            current_timeout = self.llm_optimize_timeout_seconds
            # (或者，如果硬编码: current_timeout = self.llm_optimize_timeout_value)
            scoped_logger.info(f"Using specific optimization timeout: {current_timeout}s")
        else:
            # 否则，使用默认的 API 超时时间
            current_timeout = self.api_timeout_seconds
            scoped_logger.info(f"Using default timeout: {current_timeout}s")
        # **** 结束修改 ****

        scoped_logger.info(f"Using max_tokens: {current_max_tokens} (Override active: {is_optimization_call})")

        try:
            # --- 准备 API 调用参数 ---
            api_params = {
                "model": self.llm_api_model,
                "messages": messages,
                "max_tokens": current_max_tokens,
                # **** 使用计算出的 current_timeout ****
                "timeout": current_timeout,
                # 如果需要温度等参数，确保它们也在这里
                # "temperature": self.llm_temperature,
            }
            api_params = {k: v for k, v in api_params.items() if v is not None}

            scoped_logger.debug(f"Calling LLM API. Model: {self.llm_api_model}, Messages Count: {len(messages)}, Max Tokens: {current_max_tokens}, Timeout: {current_timeout}s")
            if scoped_logger.isEnabledFor(logging.DEBUG):
                short_messages_preview = json.dumps(messages, ensure_ascii=False, indent=2)
                if len(short_messages_preview) > 500:
                     short_messages_preview = short_messages_preview[:500] + "..."
                scoped_logger.debug(f"Messages (preview): {short_messages_preview}")

            # --- 执行 API 调用 ---
            response = self.llm_client.chat.completions.create(**api_params)

            # --- 处理响应 ---
            duration = time.monotonic() - start_time

            if (response and response.choices and len(response.choices) > 0 and
                    response.choices[0].message and hasattr(response.choices[0].message, 'content') ): # 稍微改进检查

                # 特别处理 content 可能为 None 的情况 (虽然理论上 ChatCompletionMessage.content 不应为 None，但以防万一)
                content_value = response.choices[0].message.content
                if content_value is None:
                    scoped_logger.warning("LLM response message content is unexpectedly None, treating as empty.")
                    content = "" # 将 None 视为空字符串处理
                else:
                    content = content_value.strip()

                finish_reason = response.choices[0].finish_reason
                prompt_tokens = getattr(response.usage, 'prompt_tokens', 'N/A')
                completion_tokens = getattr(response.usage, 'completion_tokens', 'N/A')
                total_tokens = getattr(response.usage, 'total_tokens', 'N/A')

                scoped_logger.info(f"LLM call successful. Duration: {duration:.2f}s, Finish Reason: {finish_reason}")
                scoped_logger.info(f"LLM Token Usage: Prompt={prompt_tokens}, Completion={completion_tokens}, Total={total_tokens}")
                if scoped_logger.isEnabledFor(logging.DEBUG):
                     scoped_logger.debug(f"LLM Raw Response (content preview): {content[:200] + '...' if len(content) > 200 else content}")

                if finish_reason == 'length':
                     scoped_logger.warning(f"LLM response may have been truncated due to the max_tokens limit ({current_max_tokens}) or potentially an internal model limit if content is empty.")
                     # 补充检查：如果 finish_reason 是 length 但内容为空，可能意味着输入+请求输出超过了模型上下文总长
                     if not content and prompt_tokens != 'N/A' and completion_tokens == 0:
                         scoped_logger.warning(f"Finish reason is 'length' with empty content and 0 completion tokens (Prompt tokens: {prompt_tokens}). This often indicates the prompt itself consumed most or all of the model's context window.")

                # 即使内容为空也返回，让调用者决定如何处理空字符串
                return content
            else:
                 # 记录更详细的错误，为什么我们认为它结构不正确
                error_details = []
                if not response: error_details.append("Response object is None")
                elif not response.choices: error_details.append("Response has no 'choices'")
                elif len(response.choices) == 0: error_details.append("Response 'choices' list is empty")
                elif not response.choices[0].message: error_details.append("First choice has no 'message' object")
                elif not hasattr(response.choices[0].message, 'content'): error_details.append("Message object has no 'content' attribute")
                # else content is None or empty handled above

                scoped_logger.error(f"Unexpected LLM response structure or empty content. Details: {', '.join(error_details)}")
                try:
                    raw_resp_str = str(response)
                    scoped_logger.error(f"Raw Response Object (truncated): {raw_resp_str[:1000]}")
                except Exception as log_err:
                    scoped_logger.error(f"Could not serialize raw response for logging: {log_err}")
                return None

        # --- 错误处理 ---
        except openai.APIConnectionError as e:
            scoped_logger.error(f"LLM API Connection Error: {e}")
        except openai.RateLimitError as e:
            scoped_logger.error(f"LLM Rate Limit Exceeded: {e}")
        except openai.APITimeoutError as e:
            # **** 在日志中报告实际使用的超时时间 ****
            scoped_logger.error(f"LLM API Timeout Error ({current_timeout}s): {e}")
        except openai.AuthenticationError as e:
             scoped_logger.error(f"LLM API Authentication Error: {e}. Check your API key.")
        except openai.APIStatusError as e:
             scoped_logger.error(f"LLM API Status Error: Status Code={getattr(e, 'status_code', 'N/A')}, Response={getattr(e, 'response', 'N/A')}")
        except Exception as e:
            scoped_logger.error(f"An unexpected error occurred during LLM invocation: {e}")
            scoped_logger.error(traceback.format_exc())

        return None

    def _parse_and_update_state(
        self,
        room_id: str,
        gpt_response_text: str,
        full_context_this_turn: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Parses LLM response for commands, updates state (notepad, context).
        Returns a structured dictionary with parsed fields.
        """

        new_notepad_notes = []
        msg_contents = []
        think_content = None
        continues_count = None
        context_cleared = False

        # --- Special Command Handling ---
        if gpt_response_text.strip() == "{cls}":
            print("Clear context command '{cls}' received. Resetting state.")
            final_context = self.initial_context_message.copy()
            notepad_path = self._get_notepad_file_path(room_id)
            context_path = self._get_context_file_path(room_id)
            try: notepad_path.unlink(missing_ok=True)
            except OSError: pass
            try: context_path.unlink(missing_ok=True)
            except OSError: pass
            self._save_context(room_id, final_context)
            context_cleared = True
            return {
                "msg_contents": [],
                "think_content": None,
                "continues_count": None,
                "new_notepad": [],
                "context_cleared": True
            }

        # --- Regular Response Processing ---
        gpt_response_message = {"role": "assistant", "content": gpt_response_text}
        final_recording_context = full_context_this_turn + [gpt_response_message]

        try:
            new_notepad_notes = re.findall(r'"notepad"\s*:\s*"([^"]*)"', gpt_response_text, re.DOTALL)
            msg_contents = re.findall(r'"msg_\d+"\s*:\s*"([^"]*)"', gpt_response_text, re.DOTALL)

            think_match = re.search(r'"think"\s*:\s*"([^"]*)"', gpt_response_text, re.DOTALL)
            if think_match:
                think_content = think_match.group(1)

            continues_match = re.search(r'"continues"\s*:\s*(\d+)', gpt_response_text)
            if continues_match:
                continues_count = int(continues_match.group(1))

        except Exception as e:
            print(f"Error parsing commands from LLM response: {e}")

        if new_notepad_notes:
            self._append_to_notepad(room_id, new_notepad_notes)
            
        # +++ 新增: 检查并触发后台 Notepad 优化 +++
        # +++ Added: Check and trigger background notepad optimization +++
        if self.notepad_auto_optimize_enabled and new_notepad_notes: # Only check if notes were actually added
            try:
                current_total_tokens = self._get_notepad_total_tokens(room_id)
                # print(f"DEBUG: Notepad total tokens for room {room_id}: {current_total_tokens}") # Debug print

                # Check threshold and if not already optimizing
                # 检查阈值以及是否尚未在优化中
                # --- 使用集合进行并发控制 ---
                if current_total_tokens > self.notepad_auto_optimize_threshold_tokens and room_id not in self.optimizing_rooms:
                    logger.warning(f"[Room {room_id}] Notepad size ({current_total_tokens} tokens) exceeded threshold ({self.notepad_auto_optimize_threshold_tokens}). Scheduling background optimization.")
                    # Mark room as optimizing BEFORE submitting task
                    # 在提交任务前将房间标记为优化中
                    self.optimizing_rooms.add(room_id)
                    # Submit the optimization task to the background executor
                    # 将优化任务提交到后台执行器
                    future = self.optimization_executor.submit(self._run_notepad_optimization, room_id)
                    # Add the callback to release the lock when done
                    # 添加回调以在完成后释放锁
                    future.add_done_callback(self._optimization_task_done)

                # --- 如果使用 Lock (需要 self.optimizing_room_lock) ---
                # # Alternative using Lock:
                # # check_needed = False
                # # with self.optimizing_room_lock:
                # #     if room_id not in self.optimizing_rooms:
                # #         check_needed = True
                #
                # # if check_needed and current_total_tokens > self.notepad_auto_optimize_threshold_tokens:
                # #     logger.warning(f"[Room {room_id}] Notepad size ({current_total_tokens} tokens) exceeded threshold ({self.notepad_auto_optimize_threshold_tokens}). Scheduling background optimization.")
                # #     # Mark room as optimizing WITHIN the lock usually, or handle race carefully
                # #     with self.optimizing_room_lock:
                # #          self.optimizing_rooms.add(room_id) # Mark under lock
                # #     future = self.optimization_executor.submit(self._run_notepad_optimization, room_id)
                # #     future.add_done_callback(self._optimization_task_done) # Callback handles removal

            except Exception as check_err:
                 # Log error during check/schedule phase, but don't crash request
                 logger.error(f"[Room {room_id}] Error during notepad auto-optimization check/scheduling: {check_err}")

        self._save_context(room_id, final_recording_context)

        return {
            "msg_contents": msg_contents,
            "think_content": think_content,
            "continues_count": continues_count,
            "new_notepad": new_notepad_notes,
            "context_cleared": context_cleared
        }

    # --- Main Request Processing Method ---
    def process_request(self,
                        room_id: str,
                        streamer_name: Optional[str],
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
        if not streamer_name:
             print("Error: Missing streamer_name in request.")
             return {"status": "error", "message": "streamer_name"}
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
            room_id, streamer_name, chat_list, stt_youdao, stt_whisper, image_url
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
        parsed_result = self._parse_and_update_state(
            room_id, gpt_response_text, context_to_send
        )

        msg_contents = parsed_result.get("msg_contents", [])
        think_content = parsed_result.get("think_content")
        continues_count = parsed_result.get("continues_count")
        new_notepad = parsed_result.get("new_notepad", [])
        context_cleared = parsed_result.get("context_cleared", False)

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
            "status": "success",
            "chat_messages": [{"type": "message", "content": msg} for msg in msg_contents],
            "internal_think": think_content,
            "continues": continues_count,
            "new_notepad": new_notepad,
            "context_cleared": context_cleared,
            "recognized_text_youdao": stt_youdao,
            "recognized_text_whisper": stt_whisper,
            "image_url": image_url,
            "LLM_response_raw": gpt_response_text,
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

        # Get streamer username
        streamer_name = request.form.get('streamerName')
        if not streamer_name or not streamer_name.strip():
            print("Upload Warning: 'streamer_name' form data missing or empty.")
            streamer_name = 'unknown'
        scoped_streamer_name = streamer_name.strip() # Use sanitized ID for logging

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
            print(f"     streamer name: {scoped_streamer_name}")
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
            streamer_name=streamer_name,
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

@atexit.register
def shutdown_executor():
    """Function to be called upon script exit to shutdown the thread pool."""
    """脚本退出时调用以关闭线程池的函数。"""
    if hasattr(live_server, 'optimization_executor') and live_server.optimization_executor:
        print("\nShutting down background optimization executor...")
        # wait=True ensures pending tasks try to complete. Adjust as needed.
        # wait=True 确保待处理的任务尝试完成。根据需要调整。
        live_server.optimization_executor.shutdown(wait=True)
        print("Optimization executor shut down.")

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