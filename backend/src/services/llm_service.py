# src/services/llm_service.py

import logging
import json
import re
import time
import traceback
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, Future

# 外部库
import openai # FIX: 导入整个 openai 库以访问其异常类
from openai import OpenAI
import tiktoken

# 本地模块
from ..utils.config import Config, get_env_int # FIX: 假设 get_env_int 在 config 中
from .state_service import StateService
from .external_apis import ExternalAPIs

# --- FIX: 在模块级别定义 Logger ---
# 这确保了所有函数和方法都可以访问到同一个 logger 实例
logger = logging.getLogger(__name__)

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

class LLMService:
    """
    封装了所有与核心AI逻辑相关的服务，包括提示词工程、LLM调用和状态解析。
    这是AI的“大脑”。
    """

    def __init__(self, app_config: Config, state_service: StateService, api_service: ExternalAPIs):
        self.config = app_config
        self.state = state_service
        self.apis = api_service
        
        logger.info("Initializing LLM Service...")
        self.llm_client = OpenAI(
            api_key=self.config.llm_api_key,
            base_url=self.config.llm_api_url,
            timeout=self.config.api_timeout_seconds + 10 # 为建立连接等设置一个稍长的默认超时
        )
        
        try:
            self.tokenizer = tiktoken.encoding_for_model(self.config.llm_tokenizer_model)
        except Exception as e:
            logger.warning(f"Could not load tokenizer. Token counts may be inaccurate. Error: {e}")
            self.tokenizer = None

        self.optimization_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='Optimizer_')
        self.optimizing_rooms = set()
        
        self._setup_system_prompt()
        logger.info("LLM Service initialized successfully.")

    def _setup_system_prompt(self):
        """Loads the system prompt from file or uses the default, sets up API messages."""
        prompt_content = None
        prompt_source = "Default Internal Prompt"

        # FIX: 通过 self.config 访问配置，并使用 logger
        if self.config.system_prompt_path:
            prompt_file = Path(self.config.system_prompt_path)
            if prompt_file.is_file():
                try:
                    with prompt_file.open('r', encoding='utf-8') as f:
                        prompt_content = f.read()
                    prompt_source = f"File: {self.config.system_prompt_path}"
                    logger.info(f"Successfully loaded system prompt from {prompt_source}")
                except Exception as e:
                    logger.warning(f"Could not read system prompt file '{self.config.system_prompt_path}': {e}. Using default prompt.")
            else:
                logger.warning(f"System prompt file not found at '{self.config.system_prompt_path}'. Using default prompt.")

        if prompt_content is None:
            prompt_content = DEFAULT_SYSTEM_PROMPT
            logger.info(f"Using {prompt_source}.")

        self.system_prompt_content = prompt_content

        # FIX: 通过 self.config 访问配置
        if self.config.system_prompt_mode == 'user_message_compatibility':
            logger.info("System prompt mode: user_message_compatibility (sending as first user message).")
            self.initial_context_message = [{"role": "user", "content": self.system_prompt_content}]
            self.system_prompt_message_for_api = []
        else: # Default 'standard' mode
            logger.info("System prompt mode: standard (sending with 'system' role).")
            self.initial_context_message = [{"role": "system", "content": self.system_prompt_content}]
            self.system_prompt_message_for_api = self.initial_context_message

        self.system_prompt_tokens = self._calculate_tokens(self.system_prompt_content)
        logger.info(f"System Prompt Tokens (approximate): {self.system_prompt_tokens}")

    # --- 核心业务流程 ---
    def process_request(self,
                        room_id: str,
                        streamer_name: Optional[str],
                        audio_file_path: Path,
                        screenshot_file_path: Optional[Path] = None,
                        chat_list: Optional[List[Dict]] = None
                        ) -> Dict[str, Any]:
        """
        Main handler for a single request. Orchestrates STT, vision, LLM interaction, state updates.
        """
        start_time = time.monotonic()
        logger.info(f"\n===== Processing request for Room ID: {room_id} at {datetime.now()} =====")

        if not room_id or not streamer_name:
            logger.error(f"Error: Missing required parameter. RoomID: {room_id}, Streamer: {streamer_name}")
            return {"status": "error", "message": "Missing room_id or streamer_name"}
        if not audio_file_path or not audio_file_path.exists():
            logger.error(f"Error: Invalid or missing audio file path: {audio_file_path}")
            return {"status": "error", "message": "Invalid or missing audio file path"}
        if not isinstance(chat_list, list):
            logger.warning(f"Received non-list 'chats' data (type: {type(chat_list)}), defaulting to empty list.")
            chat_list = []

        # --- 1. Speech Recognition ---
        logger.info("--- Step 1: Speech Recognition ---")
        # FIX: 调用正确的方法名 _perform_stt
        stt_youdao, stt_whisper = self._perform_stt(audio_file_path)

        # FIX: 通过 self.config 访问配置
        if self.config.stt_comparison_mode:
            logger.info("--- STT Comparison Mode Active: Exiting after STT ---")
            processing_time = time.monotonic() - start_time
            logger.info(f"===== Request (Comparison Mode) for Room {room_id} finished in {processing_time:.2f} seconds =====")
            return {
                "status": "success", "mode": "comparison",
                "recognized_text_youdao": stt_youdao,
                "recognized_text_whisper": stt_whisper,
                "processing_time_seconds": round(processing_time, 2)
            }

        # --- 2. Image Processing (Vision) ---
        logger.info("--- Step 2: Image Processing (Vision) ---")
        # FIX: 重构视觉处理逻辑，调用 _process_vision 辅助方法，更清晰
        image_url = self._process_vision(screenshot_file_path, room_id)

        # --- 3. Build LLM Prompt ---
        logger.info("--- Step 3: Building LLM Prompt ---")
        context_to_send = self._build_llm_prompt(
            room_id, streamer_name, chat_list, stt_youdao, stt_whisper, image_url
        )

        # --- 4. Invoke LLM ---
        logger.info("--- Step 4: Invoking LLM ---")
        gpt_response_text = self._invoke_llm(context_to_send, room_id=room_id)

        if gpt_response_text is None:
            logger.error("LLM invocation failed. Ending request processing with error.")
            processing_time = time.monotonic() - start_time
            logger.error(f"===== Request for Room ID {room_id} finished with LLM ERROR in {processing_time:.2f} seconds =====")
            return {"status": "error", "message": "LLM response generation failed"}

        # --- 5. Parse Response & Update State ---
        logger.info("--- Step 5: Parsing Response and Updating State ---")
        parsed_result = self._parse_and_update_state(
            room_id, gpt_response_text, context_to_send
        )

        # --- 6. Prepare and Return Result ---
        logger.info("--- Step 6: Preparing Final Response ---")
        processing_time = time.monotonic() - start_time
        logger.info(f"===== Request for Room ID {room_id} finished successfully in {processing_time:.2f} seconds =====")

        # FIX: 将解析结果合并到最终响应中
        final_response = {
            "status": "success",
            "chat_messages": [{"type": "message", "content": msg} for msg in parsed_result.get("msg_contents", [])],
            "internal_think": parsed_result.get("think_content"),
            "continues": parsed_result.get("continues_count"),
            "new_notepad": parsed_result.get("new_notepad", []),
            "context_cleared": parsed_result.get("context_cleared", False),
            "recognized_text_youdao": stt_youdao,
            "recognized_text_whisper": stt_whisper,
            "image_url": image_url,
            "LLM_response_raw": gpt_response_text,
            "processing_time_seconds": round(processing_time, 2)
        }
        return final_response
        
    # --- 私有辅助方法 ---

    def _calculate_tokens(self, text: str) -> int:
        """Calculates token count for a given text."""
        if not self.tokenizer or not text:
            return 0
        try:
            return len(self.tokenizer.encode(text))
        except Exception as e:
            logger.warning(f"Token calculation failed: {e}")
            return 0

    def _perform_stt(self, audio_path: Path) -> Tuple[Optional[str], Optional[str]]:
        """执行语音识别流程"""
        if not audio_path or not audio_path.exists():
            return None, None
        
        stt_youdao, stt_whisper = None, None
        # 使用 with 来确保临时目录被清理
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_wav_path = Path(temp_dir) / "converted.wav"
            # 尝试有道 STT
            if self.config.use_youdao_stt:
                if self.apis.convert_audio_to_wav(audio_path, temp_wav_path):
                    stt_youdao = self.apis.recognize_speech_youdao(temp_wav_path)
                else:
                    logger.warning("Audio to WAV conversion failed, skipping Youdao STT.")
            # 尝试 Whisper STT
            if self.config.use_whisper_stt:
                stt_whisper = self.apis.recognize_speech_whisper(audio_path)
        
        return stt_youdao, stt_whisper
            
    def _process_vision(self, screenshot_path: Optional[Path], room_id: str) -> Optional[str]:
        """执行视觉处理流程, 包括上传图片并返回URL"""
        # FIX: 通过 self.config 访问配置
        if not self.config.enable_vision:
            # logger.debug("Vision disabled. Skipping image processing.")
            return None
        
        if not screenshot_path or not screenshot_path.exists():
            logger.debug("Vision enabled, but no valid screenshot file provided.")
            return None

        # FIX: 通过 self.config 访问配置并调用 self.apis
        if self.config.vision_upload_provider == 'cloudinary':
            image_url = self.apis.upload_screenshot_to_cloudinary(screenshot_path, room_id)
            if not image_url:
                logger.warning("Cloudinary upload failed or was skipped. Proceeding without image.")
            return image_url
        elif self.config.vision_upload_provider == 'none':
            logger.info("Vision upload provider is 'none'. Screenshot not uploaded.")
        else:
            logger.warning(f"Unsupported vision upload provider '{self.config.vision_upload_provider}'.")
        
        return None

    def _build_llm_prompt(self,
                          room_id: str,
                          streamer_name: Optional[str],
                          current_chat_list: List[Dict[str, Any]],
                          stt_youdao: Optional[str],
                          stt_whisper: Optional[str],
                          image_url: Optional[str]) -> List[Dict[str, Any]]:
        """构建将要发送给 LLM API 的消息列表。"""
        tokens_main_system, tokens_notepad_system, tokens_history, tokens_current_user_text = 0, 0, 0, 0

        if self.config.system_prompt_mode == 'standard':
            tokens_main_system = self.system_prompt_tokens

        # FIX: 假设 _load_notepad_for_prompt 是 StateService 的一部分
        notepad_content, tokens_notepad_raw = self.state.load_notepad_for_prompt(room_id)
        notepad_system_content = f"以下是你记录的该直播间的笔记 记得多做笔记 因为你的记忆很短 只能靠记笔记维持记忆: {notepad_content}" if notepad_content else ""
        system_notepad_message = {"role": "system", "content": notepad_system_content}
        tokens_notepad_system = self._calculate_tokens(notepad_system_content) if notepad_system_content else 0

        # --- 格式化当前用户回合的输入信息 ---
        timestamp_text = f"[当前时间]\n{datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}"
        streamer_name_text = f"[主播用户名]: \"{streamer_name}\""
        
        chatlist_content, tokens_chatlist = self.state.load_chat_list_for_prompt(current_chat_list)
        chatlist_text = f"[当前聊天列表]\n{chatlist_content}" if chatlist_content else ""
        
        stt_text_parts = []
        stt_label = "[主播语音输入]"
        # FIX: 通过 self.config 访问配置
        if self.config.stt_provider == 'both':
            if stt_youdao: stt_text_parts.append(f"  (有道识别): {stt_youdao}")
            if stt_whisper: stt_text_parts.append(f"  (Whisper识别): {stt_whisper}")
        elif self.config.stt_provider == 'whisper' and (stt_whisper or stt_youdao):
            stt_text_parts.append(f"  (Whisper识别): {stt_whisper}" if stt_whisper else f"  (有道识别 - 备用): {stt_youdao}")
        else: # 默认为 'youdao'
            if stt_youdao or stt_whisper:
                stt_text_parts.append(f"  (有道识别): {stt_youdao}" if stt_youdao else f"  (Whisper识别 - 备用): {stt_whisper}")
        
        stt_block_text = ""
        if stt_text_parts:
            stt_block_text = f"{stt_label}\n" + "\n".join(stt_text_parts)
        elif self.config.use_youdao_stt or self.config.use_whisper_stt:
            stt_block_text = f"{stt_label}\n  (无语音输入或识别失败)"

        image_preamble_text = ""
        if self.config.enable_vision and image_url:
            image_preamble_text = "[当前直播间画面信息]\n  (下方消息包含图片链接)"

        combined_text_for_turn = "\n\n".join(filter(None, [timestamp_text, streamer_name_text, chatlist_text, stt_block_text, image_preamble_text])).strip()
        tokens_current_user_text = self._calculate_tokens(combined_text_for_turn)
        
        # 使用 get_env_int 函数并从 config 获取
        reserved_buffer = get_env_int('PROMPT_RESERVED_BUFFER_TOKENS', 50)
        reserved_tokens_for_current_input = tokens_current_user_text + reserved_buffer

        # 历史记录的预算计算和方法调用
        logger.info(f"Reserving {reserved_tokens_for_current_input} tokens for current input and {tokens_notepad_system} for notepad.")
        # 先计算出给历史记录的最终token预算
        history_budget = self.config.max_total_tokens - (tokens_main_system + tokens_notepad_system + reserved_tokens_for_current_input)
        
        # 调用签名修正后的方法
        history_messages = self.state.load_trimmed_context_history(
            room_id,
            history_budget
        )
        
        tokens_history = sum(self._calculate_tokens(msg.get("content")) for msg in history_messages if isinstance(msg.get("content"), str))
        # (注意: 此处未计算历史多模态消息中的图像 token)

        # --- 打印 Token 调试信息 ---
        tokens_total_estimated_text = tokens_main_system + tokens_notepad_system + tokens_history + tokens_current_user_text
        logger.info("\n--- 📊 LLM Prompt Token Breakdown (Text Estimate) ---")
        logger.info(f"  [1] Main System Prompt:     {tokens_main_system:>5} tokens")
        logger.info(f"  [2] Notepad System Message:   {tokens_notepad_system:>5} tokens")
        logger.info(f"  [3] History Messages:         {tokens_history:>5} tokens ({len(history_messages)} messages)")
        logger.info(f"  [4] Current User Input Text:  {tokens_current_user_text:>5} tokens")
        logger.info("  ---")
        logger.info(f"  >>> Est. TEXT Tokens Sent:  {tokens_total_estimated_text:>5} tokens")
        logger.info(f"  Configured Max Total:       {self.config.max_total_tokens:>5} tokens")
        if image_url and self.config.enable_vision:
            logger.warning("  !!! Vision enabled, image URL included. Its token cost is NOT in the estimate above!")
        logger.info("------------------------------------------------")

        # --- 组装最终消息列表 ---
        final_messages = []
        final_messages.extend(self.system_prompt_message_for_api)
        final_messages.append(system_notepad_message)
        final_messages.extend(history_messages)

        content_list = []
        if combined_text_for_turn:
            content_list.append({"type": "text", "text": combined_text_for_turn})
        if self.config.enable_vision and image_url:
            content_list.append({"type": "image_url", "image_url": {"url": image_url}})
        
        if content_list:
            final_messages.append({"role": "user", "content": content_list})
        else:
            logger.warning("Current turn has no new text or image input. Sending only history and system prompts.")
            
        return final_messages

    def _invoke_llm(self, messages: List[Dict[str, Any]], room_id: str = "N/A", max_tokens_override: Optional[int] = None) -> Optional[str]:
        """使用准备好的消息调用配置好的 LLM API。"""
        start_time = time.monotonic()
        if not messages:
            logger.error(f"[Room {room_id}] Cannot invoke LLM with empty context messages.")
            return None

        # FIX: 通过 self.config 访问配置
        is_optimization_call = max_tokens_override is not None
        current_max_tokens = max_tokens_override if is_optimization_call else self.config.max_llm_response_tokens
        current_timeout = self.config.llm_optimize_timeout_seconds if is_optimization_call else self.config.api_timeout_seconds

        try:
            api_params = {
                "model": self.config.llm_api_model,
                "messages": messages,
                "max_tokens": current_max_tokens,
                "timeout": current_timeout,
            }
            
            logger.info(f"[Room {room_id}] Calling LLM API. Model: {api_params['model']}, MaxTokens: {api_params['max_tokens']}, Timeout: {api_params['timeout']}s")
            response = self.llm_client.chat.completions.create(**api_params)
            duration = time.monotonic() - start_time

            if response and response.choices:
                content = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason
                usage = response.usage
                logger.info(f"[Room {room_id}] LLM call successful. Duration: {duration:.2f}s, Finish: {finish_reason}")
                if usage:
                    logger.info(f"LLM Tokens: Prompt={usage.prompt_tokens}, Completion={usage.completion_tokens}, Total={usage.total_tokens}")

                if finish_reason == 'length':
                    logger.warning(f"LLM response may have been truncated due to max_tokens limit ({current_max_tokens}).")
                
                return content.strip() if content else ""
            else:
                logger.error(f"[Room {room_id}] Unexpected LLM response structure: {response}")
                return None

        # FIX: 捕获 openai 的标准异常
        except openai.APIConnectionError as e: logger.error(f"LLM API Connection Error: {e}")
        except openai.RateLimitError as e: logger.error(f"LLM Rate Limit Exceeded: {e}")
        except openai.APITimeoutError as e: logger.error(f"LLM API Timeout Error ({current_timeout}s): {e}")
        except openai.AuthenticationError as e: logger.error(f"LLM API Authentication Error: {e}. Check API key.")
        except openai.APIStatusError as e: logger.error(f"LLM API Status Error: Code={e.status_code}, Response={e.response}")
        except Exception as e:
            logger.error(f"An unexpected error occurred during LLM invocation: {e}")
            logger.error(traceback.format_exc()) # 记录完整的堆栈信息

        return None

    def _parse_and_update_state(self, room_id: str, gpt_response_text: str, full_context_this_turn: List[Dict[str, Any]]) -> Dict[str, Any]:
        """解析 LLM 响应，更新状态，并返回结构化字典。"""
        if gpt_response_text.strip() == "{cls}":
            logger.warning(f"Clear context command '{{cls}}' received for room {room_id}. Resetting state.")
            # FIX: 假设 clear_room_state 是 StateService 的一部分
            self.state.clear_room_state(room_id, self.initial_context_message)
            return {"msg_contents": [], "think_content": None, "continues_count": None, "new_notepad": [], "context_cleared": True}

        # 将 LLM 的回复添加到本轮对话历史中，以便保存
        gpt_response_message = {"role": "assistant", "content": gpt_response_text}
        final_recording_context = full_context_this_turn + [gpt_response_message]

        new_notepad_notes, msg_contents = [], []
        think_content, continues_count = None, None
        try:
            new_notepad_notes = re.findall(r'"notepad"\s*:\s*"([^"]*)"', gpt_response_text, re.DOTALL)
            msg_contents = re.findall(r'"msg_\d+"\s*:\s*"([^"]*)"', gpt_response_text, re.DOTALL)
            think_match = re.search(r'"think"\s*:\s*"([^"]*)"', gpt_response_text, re.DOTALL)
            if think_match: think_content = think_match.group(1)
            continues_match = re.search(r'"continues"\s*:\s*(\d+)', gpt_response_text)
            if continues_match: continues_count = int(continues_match.group(1))
        except Exception as e:
            logger.error(f"Error parsing commands from LLM response: {e}")

        if new_notepad_notes:
            # FIX: 假设 append_to_notepad 是 StateService 的一部分
            self.state.append_to_notepad(room_id, new_notepad_notes)
            # 触发后台 Notepad 优化检查
            self._schedule_notepad_optimization_if_needed(room_id)
        
        # FIX: 假设 _save_context 是 StateService 的一部分
        self.state.save_context(room_id, final_recording_context)

        return {
            "msg_contents": msg_contents, "think_content": think_content,
            "continues_count": continues_count, "new_notepad": new_notepad_notes,
            "context_cleared": False
        }

    def _schedule_notepad_optimization_if_needed(self, room_id: str):
        """检查 Notepad 大小并按需调度后台优化任务。"""
        if not self.config.notepad_auto_optimize_enabled:
            return
        try:
            # FIX: 假设 get_notepad_total_tokens 是 StateService 的一部分
            current_tokens = self.state.get_notepad_total_tokens(room_id)
            threshold = self.config.notepad_auto_optimize_threshold_tokens
            
            # 使用集合进行并发控制，防止重复提交任务
            if current_tokens > threshold and room_id not in self.optimizing_rooms:
                logger.warning(f"[Room {room_id}] Notepad size ({current_tokens} tokens) > threshold ({threshold}). Scheduling optimization.")
                self.optimizing_rooms.add(room_id)
                future = self.optimization_executor.submit(self._run_notepad_optimization, room_id)
                # 添加回调函数，无论成功或失败，都会在任务结束后释放锁定
                future.add_done_callback(lambda f: self._optimization_task_done(room_id, f))
        except Exception as e:
            logger.error(f"[Room {room_id}] Error during notepad auto-optimization check/scheduling: {e}")

    def _run_notepad_optimization(self, room_id: str):
        """
        [IMPLEMENTED] 后台执行 Notepad 优化的核心逻辑。
        """
        logger.info(f"[Optimizer Task Room {room_id}] Starting notepad optimization.")
        try:
            # FIX: 假设 read_full_notepad 和 overwrite_notepad 是 StateService 的一部分
            original_notes = self.state.read_full_notepad(room_id)
            if not original_notes:
                logger.info(f"[Optimizer Task Room {room_id}] Notepad is empty, skipping optimization.")
                return

            # 1. 构建优化提示
            prompt = NOTEPAD_OPTIMIZATION_PROMPT_TEMPLATE.format(original_notes="\n".join(original_notes))
            messages = [{"role": "user", "content": prompt}]
            
            # 2. 调用 LLM 进行优化
            logger.info(f"[Optimizer Task Room {room_id}] Invoking LLM for optimization...")
            # 为优化任务设置一个更大的响应 token 限制
            optimized_text = self._invoke_llm(
                messages,
                room_id=f"Optimizer-{room_id}",
                max_tokens_override=self.config.notepad_optimize_max_tokens
            )

            if not optimized_text:
                logger.error(f"[Optimizer Task Room {room_id}] LLM call for optimization failed or returned empty. Aborting.")
                return

            # 3. 解析并保存优化后的笔记
            new_notes = [line.strip() for line in optimized_text.strip().split('\n') if line.strip()]
            if new_notes:
                original_token_count = sum(self._calculate_tokens(n) for n in original_notes)
                new_token_count = sum(self._calculate_tokens(n) for n in new_notes)
                self.state.overwrite_notepad(room_id, new_notes)
                logger.info(f"[Optimizer Task Room {room_id}] Notepad optimization successful. Tokens reduced from ~{original_token_count} to ~{new_token_count}.")
            else:
                logger.warning(f"[Optimizer Task Room {room_id}] Optimization resulted in empty notes. Original notepad preserved.")
                
        except Exception as e:
            logger.error(f"[Optimizer Task Room {room_id}] An error occurred in optimization task: {e}")
            logger.error(traceback.format_exc())

    def _optimization_task_done(self, room_id: str, future: Future):
        """
        [IMPLEMENTED] 优化任务完成后的回调函数。
        负责从正在优化的集合中移除房间ID，并记录任何异常。
        """
        try:
            # 检查任务是否在执行期间引发了异常
            exception = future.exception()
            if exception:
                logger.error(f"[Callback Room {room_id}] Background optimization task failed with an exception: {exception}")
                logger.error(traceback.format_exc()) # 记录详细堆栈
            else:
                logger.info(f"[Callback Room {room_id}] Background optimization task finished.")
        finally:
            # 无论成功或失败，都必须将 room_id 从集合中移除，以便下次可以再次触发
            self.optimizing_rooms.discard(room_id)
            logger.info(f"[Callback Room {room_id}] Released optimization lock. Current optimizing rooms: {self.optimizing_rooms}")
            