# src/services/external_apis.py

import logging
import requests
import json
import base64
import hashlib
import time
import uuid
import subprocess
import shutil
from pathlib import Path
from typing import Optional

# 外部库
import cloudinary
import cloudinary.uploader
import cloudinary.api
from PIL import Image

# 本地模块导入
from ..utils.config import Config

class ExternalAPIs:
    """
    封装了所有与第三方API和服务交互的逻辑，
    例如语音识别（STT）、图像上传和音频格式转换。
    """

    def __init__(self, app_config: Config):
        """
        初始化外部API服务。

        Args:
            app_config (Config): 包含所有密钥和URL的全局配置对象。
        """
        self.config = app_config
        self.session = requests.Session() # 为所有HTTP请求使用一个会话
        
        # --- 只初始化本类需要的客户端：Cloudinary ---
        if self.config.enable_vision and self.config.vision_upload_provider == 'cloudinary':
            if self.config.cloudinary_configured:
                try:
                    logging.info("Initializing Cloudinary client...")
                    cloudinary.config(
                        cloud_name=self.config.cloudinary_cloud_name,
                        api_key=self.config.cloudinary_api_key,
                        api_secret=self.config.cloudinary_api_secret,
                        secure=True
                    )
                    logging.info("Cloudinary client initialized successfully.")
                except Exception as e:
                    logging.error(f"Failed to initialize Cloudinary client: {e}. Uploads will be disabled.")
                    # 在配置对象中更新状态，以便其他部分能感知到
                    self.config.cloudinary_configured = False
            else:
                logging.warning("Cloudinary client not initialized due to missing credentials.")

    def _get_audio_base64(self, audio_path: Path) -> Optional[str]:
        try:
            with audio_path.open('rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            logging.error(f"Error reading or encoding audio file {audio_path}: {e}")
            return None

    def _get_youdao_sign(self, q_base64: str, salt: str, curtime: str) -> Optional[str]:
        def _truncate(q: str) -> str:
            size = len(q)
            return q if size <= 20 else q[:10] + str(size) + q[-10:]

        if not self.config.youdao_app_key or not self.config.youdao_app_secret:
            logging.error("Cannot generate Youdao sign. App Key or Secret missing.")
            return None
        
        truncated_q = _truncate(q_base64)
        sign_str = self.config.youdao_app_key + truncated_q + salt + curtime + self.config.youdao_app_secret
        hash_algorithm = hashlib.sha256()
        hash_algorithm.update(sign_str.encode('utf-8'))
        return hash_algorithm.hexdigest()

    def recognize_speech_youdao(self, audio_wav_path: Path) -> Optional[str]:
        if not self.config.use_youdao_stt: return None
        
        q_base64 = self._get_audio_base64(audio_wav_path)
        if not q_base64: return None

        curtime = str(int(time.time()))
        salt = str(uuid.uuid1())
        sign = self._get_youdao_sign(q_base64, salt, curtime)
        if not sign: return None

        data = {
            'q': q_base64, 'langType': 'zh-CHS', 'appKey': self.config.youdao_app_key, 
            'salt': salt, 'curtime': curtime, 'sign': sign, 'signType': 'v3', 
            'format': 'wav', 'rate': '16000', 'channel': '1', 'type': '1'
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        
        try:
            response = self.session.post(self.config.youdao_api_url, data=data, headers=headers, timeout=20)
            response.raise_for_status()
            result = response.json()
            if result.get('errorCode') == '0' and result.get('result'):
                return result['result'][0]
            else:
                logging.error(f"Youdao API returned an error: {result}")
                return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Error connecting to Youdao API: {e}")
            return None
        except json.JSONDecodeError:
            logging.error(f"Error decoding Youdao API response: {response.text}")
            return None

    def recognize_speech_whisper(self, audio_path: Path) -> Optional[str]:
        if not self.config.use_whisper_stt: return None
        
        base_url = self.config.whisper_api_url.rstrip('/')
        api_url = f'{base_url}/audio/transcriptions'
        headers = {'Authorization': f'Bearer {self.config.whisper_api_key}'}

        try:
            with audio_path.open('rb') as audio_file:
                files = {'file': (audio_path.name, audio_file, 'audio/webm')}
                data = {'model': 'whisper-1'}
                response = self.session.post(api_url, headers=headers, files=files, data=data, timeout=30)
                response.raise_for_status()
                result = response.json()
                recognized_text = result.get('text')
                return recognized_text
        except requests.exceptions.RequestException as e:
            logging.error(f"Error connecting to Whisper API: {e}")
            return None
        except Exception as e:
            logging.error(f"Unexpected error during Whisper recognition: {e}")
            return None

    def convert_audio_to_wav(self, input_path: Path, output_path: Path) -> bool:
        ffmpeg_path = self.config.ffmpeg_path
        if not Path(ffmpeg_path).exists() and not shutil.which(ffmpeg_path):
            logging.critical(f"FFmpeg not found at '{ffmpeg_path}'. Please install or set FFMPEG_PATH.")
            return False
        try:
            command = [ffmpeg_path, '-y', '-i', str(input_path), '-vn', '-acodec', 'pcm_s16le', '-ac', '1', '-ar', '16000', '-f', 'wav', str(output_path)]
            result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
            if result.returncode != 0:
                logging.error(f"FFmpeg failed to convert {input_path.name}:\n{result.stderr}")
                return False
            return True
        except Exception as e:
            logging.error(f"Error during FFmpeg execution: {e}")
            return False
            
    def upload_screenshot_to_cloudinary(self, image_path: Path, room_id: str) -> Optional[str]:
        """
        压缩截图（如果已配置）并上传到Cloudinary。
        """
        if not self.config.cloudinary_configured:
            logging.warning("Cloudinary upload skipped: not configured.")
            return None
            
        path_to_upload = image_path # 默认上传原始文件
        quality = self.config.image_compression_quality

        # 仅当 quality 值在有效压缩区间 (1-95) 时执行压缩
        if 0 < quality <= 95:
            # 定义压缩后文件的路径，后缀改为 .jpg
            compressed_path = image_path.with_suffix('.jpg')
            try:
                logging.info(f"Compressing image {image_path.name} with quality={quality}...")
                with Image.open(image_path) as img:
                    # 如果图像包含透明通道(RGBA)或为P模式(调色板)，需转换为RGB，因为JPEG不支持透明度
                    if img.mode in ('RGBA', 'P'):
                        img = img.convert('RGB')
                    
                    # 保存为JPEG，应用指定的质量和优化选项
                    img.save(compressed_path, 'jpeg', quality=quality, optimize=True)
                    
                    # 记录压缩效果
                    original_size_kb = image_path.stat().st_size / 1024
                    compressed_size_kb = compressed_path.stat().st_size / 1024
                    logging.info(
                        f"Image compressed successfully: "
                        f"{original_size_kb:.1f} KB -> {compressed_size_kb:.1f} KB. "
                        f"Uploading compressed version."
                    )
                    
                    # 更新上传路径为压缩后的文件
                    path_to_upload = compressed_path
            except Exception as e:
                # 如果压缩过程中出现任何错误，则记录错误并退回至上传原始文件
                logging.error(f"Failed to compress image {image_path.name}: {e}. Uploading original file.")
        else:
            logging.info(f"Image compression skipped due to quality setting ({quality}).")

        try:
            public_id = f"{room_id}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
            upload_response = cloudinary.uploader.upload(
                str(path_to_upload), # 使用最终决定要上传的文件路径
                folder=self.config.cloudinary_upload_folder,
                public_id=public_id,
                tags=["live-screenshot", f"room-{room_id}"]
            )
            return upload_response.get('secure_url')
        except Exception as e:
            logging.error(f"Cloudinary upload failed: {e}")
            return None
        