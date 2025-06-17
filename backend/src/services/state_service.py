# src/services/state_service.py (最终清理版)

import json
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Any

# 从本地模块导入 Config 以便类型提示
from ..utils.config import Config

logger = logging.getLogger(__name__)

class StateService:
    """
    负责所有基于文件系统的状态管理，包括读写Notepad和Context历史。
    """
    def __init__(self, app_config: Config, tokenizer: Any):
        self.config = app_config
        self.memory_base_dir = Path(self.config.memory_base_dir)
        self.tokenizer = tokenizer
        self.memory_base_dir.mkdir(exist_ok=True)
        logger.info(f"StateService initialized. Memory directory: {self.memory_base_dir.resolve()}")

    def _calculate_tokens(self, text: str) -> int:
        if not self.tokenizer or not isinstance(text, str) or not text:
            return 0
        try:
            return len(self.tokenizer.encode(text))
        except Exception as e:
            logger.warning(f"Token calculation failed for text: '{text[:50]}...'. Error: {e}")
            return len(text) // 3

    def _get_memory_folder(self, room_id: str) -> Path:
        safe_room_id = str(room_id).replace("..", "").replace("/", "").replace("\\", "")
        folder = self.memory_base_dir / safe_room_id
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _get_notepad_path(self, room_id: str) -> Path:
        return self._get_memory_folder(room_id) / "notepad.txt"

    def _get_context_path(self, room_id: str) -> Path:
        return self._get_memory_folder(room_id) / "context.json"

    def load_notepad_for_prompt(self, room_id: str) -> Tuple[str, int]:
        """从文件加载最近的笔记，直到达到token上限。"""
        max_tokens = self.config.max_notepad_tokens_in_prompt
        file_path = self._get_notepad_path(room_id)
        if not file_path.exists():
            return "", 0

        lines_to_include = []
        total_tokens = 0
        try:
            with file_path.open("r", encoding="utf-8") as f:
                all_lines = [line.strip() for line in f if line.strip()]
                for line in reversed(all_lines):
                    line_tokens = self._calculate_tokens(line)
                    if total_tokens + line_tokens <= max_tokens:
                        lines_to_include.insert(0, line)
                        total_tokens += line_tokens
                    else:
                        break
            
            if not lines_to_include:
                return "", 0
            
            notepad_content = "\n".join(lines_to_include)
            return notepad_content, self._calculate_tokens(notepad_content)
        except Exception as e:
            logger.error(f"Error loading notepad for room {room_id}: {e}")
        
        return "", 0

    def load_chat_list_for_prompt(self, chat_list: List[Dict]) -> Tuple[str, int]:
        """
        格式化聊天列表，并根据配置的Token上限(max_chatlist_tokens_in_prompt)进行裁剪。
        会优先保留最新的消息。
        """
        max_tokens = self.config.max_chatlist_tokens_in_prompt
        
        # 如果没有聊天记录或token上限为0，则直接返回空
        if not chat_list or max_tokens <= 0:
            return "", 0

        lines_to_include = []
        total_tokens = 0
        
        # 反向遍历列表，优先处理最新的消息
        for chat in reversed(chat_list):
            # 格式化单条消息
            line = f"{chat.get('user', '未知用户')}: {chat.get('message', '')}"
            line_tokens = self._calculate_tokens(line)

            # 检查加上这条消息（以及一个换行符的token）是否会超出预算
            # 我们用 +1 来近似换行符的token消耗
            if total_tokens + line_tokens + 1 <= max_tokens:
                # 使用 insert(0, ...) 将新消息插入到列表开头，以保持正确的时序
                lines_to_include.insert(0, line)
                total_tokens += line_tokens + 1
            else:
                # 如果超出预算，则停止添加更早的消息
                logger.info(f"Chat list trimmed due to token limit ({max_tokens}). Original message count: {len(chat_list)}, included: {len(lines_to_include)}.")
                break
        
        if not lines_to_include:
            return "", 0
        
        # 将选定的行合并成最终的文本块
        final_chat_text = "\n".join(lines_to_include)
        
        # 返回最终文本和精确的token计数
        final_tokens = self._calculate_tokens(final_chat_text)
        return final_chat_text, final_tokens

    def load_trimmed_context_history(self, room_id: str, budget: int) -> List[Dict[str, Any]]:
        """根据给定的token预算加载并裁剪历史记录。"""
        file_path = self._get_context_path(room_id)
        if not file_path.exists():
            return []

        try:
            with file_path.open('r', encoding='utf-8') as f:
                full_context = json.load(f)
                history_to_trim = [msg for msg in full_context if msg.get("role") != "system"]
        except Exception as e:
            logger.error(f"Error loading context for room {room_id}: {e}")
            return []
        
        if budget <= 0:
            return []

        trimmed_history = []
        current_tokens = 0
        for msg in reversed(history_to_trim):
            content = msg.get("content")
            msg_tokens = 0
            if isinstance(content, list):
                msg_tokens = sum(self._calculate_tokens(item.get("text", "")) for item in content if item.get("type") == "text")
            elif isinstance(content, str):
                msg_tokens = self._calculate_tokens(content)

            if msg_tokens > 0 and (current_tokens + msg_tokens <= budget):
                trimmed_history.insert(0, msg)
                current_tokens += msg_tokens
            elif msg_tokens > 0:
                break
        
        logger.info(f"Loaded context for room {room_id}: {len(trimmed_history)} messages, ~{current_tokens} tokens (Budget: {budget})")
        return trimmed_history

    def save_context(self, room_id: str, full_context_data: List[Dict[str, Any]]):
        """保存完整的对话历史。"""
        file_path = self._get_context_path(room_id)
        try:
            with file_path.open('w', encoding='utf-8') as f:
                json.dump(full_context_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving context for room {room_id}: {e}")

    def append_to_notepad(self, room_id: str, new_notes: List[str]):
        """向Notepad追加新笔记。"""
        if not new_notes: return
        file_path = self._get_notepad_path(room_id)
        try:
            with file_path.open("a", encoding="utf-8") as f:
                for note in new_notes:
                    if isinstance(note, str) and note.strip():
                        f.write(note.strip() + "\n")
        except Exception as e:
            logger.error(f"Error appending to notepad for room {room_id}: {e}")

    def get_notepad_total_tokens(self, room_id: str) -> int:
        """获取一个房间notepad的总token数。"""
        all_notes = self.read_full_notepad(room_id)
        return sum(self._calculate_tokens(note) for note in all_notes)

    def read_full_notepad(self, room_id: str) -> List[str]:
        """读取并返回一个房间的全部笔记。"""
        file_path = self._get_notepad_path(room_id)
        if not file_path.exists():
            return []
        try:
            with file_path.open("r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
        except Exception as e:
            logger.error(f"Error reading full notepad for room {room_id}: {e}")
            return []

    def overwrite_notepad(self, room_id: str, new_notes: List[str]):
        """用新笔记覆盖整个notepad文件。"""
        file_path = self._get_notepad_path(room_id)
        try:
            with file_path.open("w", encoding="utf-8") as f:
                for note in new_notes:
                    f.write(note.strip() + "\n")
        except Exception as e:
            logger.error(f"Error overwriting notepad for room {room_id}: {e}")

    def clear_room_state(self, room_id: str, initial_context: List[Dict]):
        """清除一个房间的所有状态（notepad和context）。"""
        notepad_path = self._get_notepad_path(room_id)
        try:
            notepad_path.unlink(missing_ok=True)
            logger.info(f"Deleted notepad for room {room_id}")
            self.save_context(room_id, initial_context)
            logger.info(f"Reset context for room {room_id}")
        except Exception as e:
            logger.error(f"Error clearing state for room {room_id}: {e}")
            