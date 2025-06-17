# src/utils/config.py
import os
import sys
import logging
from dotenv import load_dotenv

# --- Helper Functions ---
def get_env_bool(var_name: str, default: bool = False) -> bool:
    value = os.getenv(var_name, str(default)).lower()
    return value in ('true', '1', 't', 'y', 'yes')

def get_env_int(var_name: str, default: int) -> int:
    value_str = os.getenv(var_name)
    if value_str is None:
        return default
    try:
        return int(value_str)
    except ValueError:
        logging.warning(f"Invalid integer value for {var_name} ('{value_str}'). Using default: {default}")
        return default

def get_env_str(var_name: str, default: str = "") -> str:
    return os.getenv(var_name, default)

# --- Config Class (修改后) ---
class Config:
    def __init__(self):
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        load_dotenv(dotenv_path=os.path.join(project_root, '.env'))
        
        logging.info("Loading configuration from environment variables...")

        # --- 服务自身配置 ---
        self.server_host = get_env_str('SERVER_HOST', '0.0.0.0')
        self.server_port = get_env_int('SERVER_PORT', 8181)
        self.api_key = get_env_str("INFERENCE_SERVICE_API_KEY")

        # --- START: 新增SSL配置读取 ---
        self.enable_ssl = get_env_bool('SERVER_ENABLE_SSL', False)
        self.ssl_cert_path = get_env_str('SSL_CERT_PATH')
        self.ssl_key_path = get_env_str('SSL_KEY_PATH')

        # --- 文件与路径 ---
        self.memory_base_dir = get_env_str('MEMORY_BASE_DIR', "memory")
        self.test_files_dir = get_env_str('TEST_FILES_DIR', "test")
        self.ffmpeg_path = get_env_str('FFMPEG_PATH', "ffmpeg")
        self.enable_test_mode = get_env_bool("SERVER_TEST_MODE", False)

        # --- LLM 配置 ---
        self.llm_api_key = get_env_str("LLM_API_KEY")
        self.llm_api_url = get_env_str("LLM_API_URL")
        self.llm_api_model = get_env_str('LLM_API_MODEL', 'gpt-4o-mini')
        self.llm_tokenizer_model = get_env_str('LLM_TOKENIZER_MODEL', self.llm_api_model)
        self.max_llm_response_tokens = get_env_int('LLM_MAX_RESPONSE_TOKENS', 2000)
        self.api_timeout_seconds = get_env_int('LLM_API_TIMEOUT_SECONDS', 60)
        self.llm_optimize_timeout_seconds = get_env_int("LLM_OPTIMIZE_TIMEOUT_SECONDS", 180)

        # --- Token 限制 ---
        self.max_total_tokens = get_env_int('PROMPT_MAX_TOTAL_TOKENS', 4096)
        self.max_notepad_tokens_in_prompt = get_env_int('PROMPT_MAX_NOTEPAD_TOKENS', 712)
        self.max_chatlist_tokens_in_prompt = get_env_int('PROMPT_MAX_CHATLIST_TOKENS', 256)
        self.notepad_optimize_max_tokens = get_env_int('LLM_MAX_OPTIMIZE_RESP_TOKENS', 4096)

        # --- Notepad 自动优化 ---
        self.notepad_auto_optimize_enabled = get_env_bool('NOTEPAD_AUTO_OPTIMIZE_ENABLE', False)
        self.notepad_auto_optimize_threshold_tokens = get_env_int('NOTEPAD_AUTO_OPTIMIZE_THRESHOLD_TOKENS', 2500)

        # --- STT 配置 ---
        self.stt_provider = get_env_str('STT_PROVIDER', 'whisper').lower()
        if self.stt_provider not in ['youdao', 'whisper', 'both']:
            self.stt_provider = 'whisper'
        self.youdao_app_key = get_env_str("YOUDAO_APP_KEY")
        self.youdao_app_secret = get_env_str("YOUDAO_APP_SECRET")
        self.youdao_api_url = get_env_str('YOUDAO_API_URL', 'https://openapi.youdao.com/asrapi')
        self.whisper_api_url = get_env_str("WHISPER_API_URL", self.llm_api_url)
        self.whisper_api_key = get_env_str("WHISPER_API_KEY", self.llm_api_key)
        self.use_youdao_stt = 'youdao' in self.stt_provider or 'both' in self.stt_provider
        self.use_whisper_stt = 'whisper' in self.stt_provider or 'both' in self.stt_provider
        self.stt_comparison_mode = get_env_bool('STT_COMPARISON_MODE', False)

        # --- Vision 配置 ---
        self.enable_vision = get_env_bool('VISION_ENABLE', False)
        self.vision_upload_provider = get_env_str('VISION_UPLOAD_PROVIDER', 'cloudinary').lower() if self.enable_vision else 'none'
        self.cloudinary_cloud_name = get_env_str("CLOUDINARY_CLOUD_NAME")
        self.cloudinary_api_key = get_env_str("CLOUDINARY_API_KEY")
        self.cloudinary_api_secret = get_env_str("CLOUDINARY_API_SECRET")
        self.cloudinary_upload_folder = get_env_str('CLOUDINARY_UPLOAD_FOLDER', "live_screenshots")
        self.image_compression_quality = get_env_int('IMAGE_COMPRESSION_QUALITY', 50)
        self.cloudinary_configured = (self.vision_upload_provider == 'cloudinary' and
                                      all([self.cloudinary_cloud_name, self.cloudinary_api_key, self.cloudinary_api_secret]))
        
        # --- System Prompt 配置 ---
        self.system_prompt_mode = get_env_str('SYSTEM_PROMPT_MODE', 'standard').lower()
        self.system_prompt_path = get_env_str('SYSTEM_PROMPT_PATH')
        
        # --- 统一的必需项检查 ---
        self._validate_required_vars()

    def _validate_required_vars(self):
        """检查所有必需的环境变量是否已设置。"""
        required = {
            "INFERENCE_SERVICE_API_KEY": self.api_key,
            "LLM_API_KEY": self.llm_api_key,
            "LLM_API_URL": self.llm_api_url
        }
        
        missing = [key for key, value in required.items() if not value]
        if missing:
            logging.critical(f"关键环境变量缺失! 请在 .env 文件中设置: {', '.join(missing)}")
            sys.exit(1)

        if self.enable_ssl and (not self.ssl_cert_path or not self.ssl_key_path):
            logging.critical("SERVER_ENABLE_SSL 设置为 true, 但 SSL_CERT_PATH 或 SSL_KEY_PATH 未提供！")
            sys.exit(1)

        if self.use_youdao_stt and (not self.youdao_app_key or not self.youdao_app_secret):
            logging.warning("STT_PROVIDER 包含 'youdao', 但 YOUDAO_APP_KEY 或 YOUDAO_APP_SECRET 未设置。有道STT将无法使用。")
        
        if self.enable_vision and self.vision_upload_provider == 'cloudinary' and not self.cloudinary_configured:
            logging.warning("VISION_ENABLE 为 true 且 VISION_UPLOAD_PROVIDER 为 'cloudinary', 但 Cloudinary 凭证不完整。图片上传将失败。")

# 创建全局唯一的配置实例，供其他模块导入
config = Config()