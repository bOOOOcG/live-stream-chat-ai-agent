# src/app.py
import logging
from flask import Flask, request, jsonify, abort
from functools import wraps
import tempfile
from pathlib import Path
import json
from werkzeug.utils import secure_filename
import sys

import shutil
import uuid
from datetime import datetime
from flask_cors import CORS

# 模块导入
from .utils.config import config
from .services.state_service import StateService
from .services.external_apis import ExternalAPIs
from .services.llm_service import LLMService
import tiktoken

# --- 基础配置和应用创建 ---
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')
app = Flask(__name__)

CORS(app, resources={
    r"/v1/infer": {
        "origins": [
            "https://live.bilibili.com",
            "https://www.youtube.com",
            "https://www.twitch.tv"
        ],
        "methods": ["POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "X-Api-Key"]
    }
})

# --- 依赖注入：在应用启动时，创建所有服务的单例 ---
try:
    tokenizer = tiktoken.encoding_for_model(config.llm_tokenizer_model)
except:
    tokenizer = None
    logging.warning("Could not load tiktoken tokenizer!")

state_service = StateService(app_config=config, tokenizer=tokenizer) 
external_api_service = ExternalAPIs(config)
llm_service = LLMService(config, state_service, external_api_service)

# --- API 安全装饰器 ---
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.headers.get('X-Api-Key') != config.api_key:
            logging.warning(f"Unauthorized API call from IP: {request.remote_addr}")
            abort(401, description="Invalid or missing API Key.")
        return f(*args, **kwargs)
    return decorated_function

# --- API 路由 ---
@app.route('/v1/infer', methods=['POST'])
@require_api_key
def handle_upload():
    if 'audio' not in request.files:
        abort(400, description="Missing 'audio' file part.")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)

        # --- 保存临时文件 (FIX: 使用 secure_filename) ---
        audio_file = request.files['audio']
        # 使用 secure_filename 防止恶意路径
        safe_audio_filename = secure_filename(audio_file.filename or "audio.webm")
        audio_path = temp_dir_path / safe_audio_filename
        audio_file.save(audio_path)

        screenshot_path = None
        screenshot_file = request.files.get('screenshot')
        if screenshot_file:
            safe_ss_filename = secure_filename(screenshot_file.filename or "screenshot.png")
            screenshot_path = temp_dir_path / safe_ss_filename
            screenshot_file.save(screenshot_path)

        # --- 解析表单数据 (FIX: 增加健壮性) ---
        try:
            chats = json.loads(request.form.get('chats', '[]'))
        except json.JSONDecodeError:
            logging.warning(f"Invalid JSON format in 'chats' field from {request.remote_addr}.")
            abort(400, description="Invalid JSON format for 'chats'.")

        room_id = request.form.get('roomId')
        streamer_name = request.form.get('streamerName')

        # 将请求委托给 LLMService
        result = llm_service.process_request(
            room_id=room_id,
            streamer_name=streamer_name,
            audio_file_path=audio_path,
            screenshot_file_path=screenshot_path,
            chat_list=chats
        )

        # 测试模式
        if config.enable_test_mode:
            request_uuid = uuid.uuid4().hex[:8]
            timestamp_save = datetime.now().strftime('%Y%m%d_%H%M%S')
            logging.info(f"[Test Mode] Saving artifacts for request {request_uuid}")
            
            save_dir = Path(config.test_files_dir) / room_id
            save_dir.mkdir(parents=True, exist_ok=True)
            base_filename = f"{timestamp_save}_{request_uuid}"

            # 保存音频
            if audio_path and audio_path.exists():
                test_audio_dest = save_dir / f"{base_filename}{audio_path.suffix}"
                shutil.copy(audio_path, test_audio_dest)

            # 保存截图 (如果存在)
            if screenshot_path and screenshot_path.exists():
                test_ss_dest = save_dir / f"{base_filename}{screenshot_path.suffix}"
                shutil.copy(screenshot_path, test_ss_dest)

            # 保存请求信息和处理结果
            request_info = {
                'request_id': request_uuid, 'room_id': room_id,
                'timestamp': datetime.now().isoformat(),
                'form_data': dict(request.form),
                'files_received': {
                    'audio': audio_file.filename,
                    'screenshot': screenshot_file.filename if screenshot_file else None,
                },
                'processing_result': result
            }
            info_path = save_dir / f"{base_filename}_info.json"
            try:
                with info_path.open('w', encoding='utf-8') as f:
                    json.dump(request_info, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logging.error(f"[Test Mode] Error saving request info JSON: {e}")

        return jsonify(result)

# --- 主程序入口 ---
if __name__ == '__main__':
    # SSL/TLS 配置
    ssl_context = None
    if config.enable_ssl:
        logging.info("SSL/TLS is ENABLED. Checking for certificate and key files...")
        cert_path = Path(config.ssl_cert_path)
        key_path = Path(config.ssl_key_path)

        if not cert_path.is_file() or not key_path.is_file():
            logging.critical(f"SSL cert or key not found at the specified paths.")
            logging.critical(f"  - Cert Path checked: {cert_path.resolve()}")
            logging.critical(f"  - Key Path checked:  {key_path.resolve()}")
            logging.critical("Server startup aborted.")
            sys.exit(1)
        
        ssl_context = (str(cert_path), str(key_path))
        logging.info(f"Starting server with HTTPS on https://{config.server_host}:{config.server_port}")
    else:
        logging.info(f"SSL/TLS is DISABLED. Starting server with HTTP on http://{config.server_host}:{config.server_port}")

    app.run(
        host=config.server_host, 
        port=config.server_port, 
        debug=False,
        ssl_context=ssl_context  # 应用SSL上下文
    )