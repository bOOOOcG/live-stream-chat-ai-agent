#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil
import re
import subprocess
import platform
import webbrowser
import zipfile
import tarfile
import stat
import urllib.request
import urllib.error
import json
import time
from pathlib import Path
try:
    import getpass
except ImportError:
    getpass = None # Fallback if getpass isn't available

# --- 常量与配置 ---
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
BACKEND_DIR = PROJECT_ROOT / "backend"
TOOLS_DIR = PROJECT_ROOT / "tools"
BIN_DIR = TOOLS_DIR / "bin"              # 本地工具安装目录
DOWNLOADS_DIR = TOOLS_DIR / "downloads"  # 临时下载目录
ENV_EXAMPLE_EN = BACKEND_DIR / ".env.example"
ENV_EXAMPLE_ZH = BACKEND_DIR / ".env.zh-CN.example"
ENV_FILE = BACKEND_DIR / ".env"
REQUIREMENTS_FILE = BACKEND_DIR / "requirements.txt"
LICENSE_FILE_NAMES = ["LICENSE", "LICENSE.md"]
MIN_PYTHON_VERSION = (3, 8)
USER_AGENT = "LiveAgentSetupScript/1.1" # 增加版本号

# --- 工具下载配置 (优先从 GitHub API 获取最新，失败则用 Fallback) ---
MKCERT_REPO = "FiloSottile/mkcert"
MKCERT_VERSION_TARGET = "v1.4.4"
MKCERT_FALLBACK_VERSION = "v1.4.4"
MKCERT_FALLBACK_URLS = {
    "windows_amd64": "https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-windows-amd64.exe",
    "darwin_amd64": "https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-darwin-amd64",
    "darwin_arm64": "https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-darwin-arm64",
    "linux_amd64": "https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-linux-amd64",
}
MKCERT_EXPECTED_EXE = "mkcert.exe" if platform.system() == "Windows" else "mkcert"

FFMPEG_VERSION = "7.1.1"
FFMPEG_URLS = {
    "windows_amd64": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
}
FFMPEG_EXPECTED_EXE = "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"
# 注意：需要知道 FFmpeg zip 包内 ffmpeg.exe 相对路径，gyan.dev Essentials 通常是 'ffmpeg-版本号-essentials_build/bin/ffmpeg.exe'
FFMPEG_INTERNAL_PATH_PATTERN = re.compile(r"ffmpeg-[\d.]+-essentials_build[\\/]bin[\\/]" + FFMPEG_EXPECTED_EXE, re.IGNORECASE)

# --- 帮助函数 ---
def print_separator(char='-', length=70): print(char * length)
def print_header(text): print_separator('='); print(f"配置向导: {text}"); print_separator('='); print()
def print_info(text): print(f"[信息] {text}")
def print_warning(text): print(f"[警告] {text}")
def print_error(text): print(f"[错误] {text}")
def print_success(text): print(f"[成功] {text}")
def print_step(num, text): print_separator(); print(f"步骤 {num}: {text}"); print_separator(); print()
def print_action(text): print(f"\n>>> {text} <<<\n") # 突出用户操作

def load_env(env_path):
    """从 .env 文件中加载键值对为 dict。忽略注释与空行。"""
    config = {}
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip().strip('"').strip("'")
    except Exception as e:
        print_error(f"读取 .env 文件失败: {e}")
    return config

def save_env(env_path, config_dict, template_path=None):
    """
    将配置字典写入 .env 文件，如果提供了模板文件，将保留其注释与格式。
    """
    try:
        output_lines = []
        used_keys = set()

        if template_path and Path(template_path).is_file():
            with open(template_path, 'r', encoding='utf-8') as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith('#'):
                        output_lines.append(line.rstrip())  # 保留注释与空行
                        continue

                    if '=' in line:
                        key, _ = line.split('=', 1)
                        key = key.strip()
                        if key in config_dict:
                            value = str(config_dict[key])
                            if re.search(r'\s', value) or any(c in value for c in '"\'='):
                                value = f'"{value}"'  # 自动加引号
                            output_lines.append(f"{key}={value}")
                            used_keys.add(key)
                        else:
                            output_lines.append(line.rstrip())
                    else:
                        output_lines.append(line.rstrip())
        else:
            print_warning(f"未找到模板文件 {template_path}，将仅根据 config_dict 写入。")

        # 添加未出现在模板中的新键
        for key, value in config_dict.items():
            if key not in used_keys:
                value = str(value)
                if re.search(r'\s', value) or any(c in value for c in '"\'='):
                    value = f'"{value}"'
                output_lines.append(f"{key}={value}")

        # 写入目标文件
        with open(env_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(output_lines) + '\n')

        print_success(f".env 文件已成功保存到: {env_path}")
        return True
    except Exception as e:
        print_error(f"保存 .env 文件失败: {e}")
        return False

def ask_yes_no(prompt, default=None):
    while True:
        options = "[Y/n]" if default == 'yes' else "[y/N]" if default == 'no' else "[y/n]"
        choice = input(f"{prompt} {options}: ").strip().lower()
        if not choice: return default == 'yes' if default is not None else False # Handle empty input with default
        if choice in ['y', 'yes']: return True
        if choice in ['n', 'no']: return False
        print("请输入 'y' (是) 或 'n' (否).")

def ask_string(prompt, default=None, required=False, secret=False, validation_func=None):
    while True:
        default_display = f" (默认为: '{default}')" if default else ""
        input_prompt = f"{prompt}{default_display}: "
        value = ""
        try:
          if secret:
              if getpass: value = getpass.getpass(input_prompt)
              else: value = input(input_prompt + "[输入不可见]: ").strip()
          else:
              value = input(input_prompt).strip()
        except EOFError: # Handle cases where input stream is closed unexpectedly
            print_error("输入流已关闭。")
            sys.exit(1)
        except KeyboardInterrupt:
            print_info("\n操作被中断。")
            sys.exit(1)

        if not value and default is not None: value = default # Assign default if empty and default exists
        if not value and required: print_warning("此项为必填项，不能为空。"); continue
        if validation_func and value:
            is_valid, error_msg = validation_func(value)
            if not is_valid: print_warning(error_msg); continue
        return value or "" # Return empty string if not required and no value/default

# ... (其余 ask_choice, ask_path, ask_integer, load_env, save_env 基本不变, 确保路径处理用 pathlib) ...
def ask_choice(prompt, choices, default=None):
    print(prompt)
    choices_map = {str(i+1): choice for i, choice in enumerate(choices)}
    default_num_str = None
    for num, choice_val in choices_map.items():
        print(f"  {num}) {choice_val}")
        if choice_val == default: default_num_str = num
    while True:
        default_prompt = f" (默认为: {default_num_str})" if default_num_str else ""
        choice_num = input(f"请选择编号{default_prompt}: ").strip()
        if not choice_num and default_num_str: return choices_map[default_num_str]
        if choice_num in choices_map: return choices_map[choice_num]
        print_warning(f"无效选择，请输入 1 到 {len(choices)}.")

def ask_path(prompt, default=None, check_exists=False, must_exist=False, is_file=True, ensure_executable=False):
     while True:
        path_str = ask_string(prompt, default)
        if not path_str:
            if must_exist: print_warning("此路径为必填项."); continue
            else: return "" # Allow empty if not required
        try:
             # Normalize and resolve the path
             path = Path(path_str).expanduser().resolve()
        except Exception as e:
             print_warning(f"无法解析路径 '{path_str}': {e}")
             continue

        path_ok = True; error_msg = ""
        if check_exists:
            if not path.exists(): path_ok = False; error_msg = f"路径不存在: {path}"
            elif is_file and not path.is_file(): path_ok = False; error_msg = f"这不是一个文件: {path}"
            elif not is_file and not path.is_dir(): path_ok = False; error_msg = f"这不是一个目录: {path}"
            # Executable check (basic os.access)
            elif ensure_executable and is_file and not os.access(path, os.X_OK):
                 # On Windows, just being .exe is often enough unless ACLs prevent it
                 if platform.system() != "Windows" or not str(path).lower().endswith(('.exe', '.bat', '.cmd')):
                      path_ok = False; error_msg = f"文件似乎不可执行 (权限不足?): {path}"

        if path_ok: return str(path) # Return absolute path string
        else:
            print_warning(error_msg)
            if must_exist: continue
            else: # Warn but allow if not must_exist
                if ask_yes_no(f"路径 '{path_str}' 无效或不满足条件。是否仍要使用此路径?", default='no'):
                     return str(path)
                else: continue

def ask_integer(prompt, default=None, min_val=None, max_val=None):
     while True:
        default_display = f" (默认为: {default})" if default is not None else ""
        value_str = input(f"{prompt}{default_display}: ").strip()
        if not value_str and default is not None: return default
        try:
            value = int(value_str)
            valid = True
            if min_val is not None and value < min_val: print_warning(f"值需 >= {min_val}."); valid = False
            if max_val is not None and value > max_val: print_warning(f"值需 <= {max_val}."); valid = False
            if valid: return value
        except ValueError: print_warning("请输入有效的整数.")

def run_command(command, cwd=None, capture_output=False, text=True, check=False, env=None, timeout=None, display_output=False):
    """Runs command, adds local bin to PATH, captures/displays output."""
    current_env = os.environ.copy()
    if env: current_env.update(env)
    if BIN_DIR.is_dir(): current_env['PATH'] = str(BIN_DIR.resolve()) + os.pathsep + current_env.get('PATH', '')
    cmd_str = ' '.join(str(c) for c in command) if isinstance(command, list) else command
    print_info(f"执行命令: {cmd_str} {'(在 ' + str(cwd) + ')' if cwd else ''}")
    try:
        use_shell = isinstance(command, str) and platform.system() == "Windows"
        process = subprocess.run(command, cwd=cwd, capture_output=capture_output, text=text, check=check, env=current_env, shell=use_shell, encoding='utf-8', errors='ignore', timeout=timeout)
        if display_output:
            if process.stdout: print("--- 命令输出 ---\n" + process.stdout + "\n---------------")
            if process.stderr: print_warning("--- 命令错误输出 ---\n" + process.stderr + "\n-------------------")
        return process
    except FileNotFoundError: print_error(f"命令未找到: {command[0] if isinstance(command, list) else command.split()[0]}."); return None
    except subprocess.TimeoutExpired: print_error("命令执行超时。"); return None
    except subprocess.CalledProcessError as e:
        print_error(f"命令失败 (返回码 {e.returncode}): {cmd_str}")
        # Captured output available on the exception object 'e'
        if e.stdout: print_error(f"输出:\n{e.stdout}")
        if e.stderr: print_error(f"错误输出:\n{e.stderr}")
        return e
    except Exception as e: print_error(f"执行命令时出错: {e}"); return None

# --- Core Logic Functions ---

def find_executable(name):
    """Checks local BIN_DIR first, then system PATH."""
    expected_ext = ".exe" if platform.system() == "Windows" else ""
    local_path = BIN_DIR / (name + expected_ext)
    if local_path.is_file():
        # Double check execute permission, though os.access can be tricky on Windows ACLs
        if os.access(local_path, os.X_OK): return str(local_path.resolve())
        else: print_warning(f"找到本地文件 {local_path} 但似乎不可执行。")

    system_path_str = shutil.which(name)
    if system_path_str:
         system_path = Path(system_path_str).resolve()
         # Ensure it's not just pointing back to our (potentially non-executable) local file
         if system_path != local_path.resolve():
             return str(system_path)
    return None

def check_network(test_url="https://www.google.com", timeout=5):
    """Tries to connect to a URL to check network connectivity."""
    print_info("检查网络连接...")
    try:
        req = urllib.request.Request(test_url, headers={'User-Agent': USER_AGENT})
        response = urllib.request.urlopen(req, timeout=timeout)
        response.read() # Consume some data
        print_success("网络连接正常。")
        return True
    except Exception as e:
        print_error(f"网络连接测试失败 (访问 {test_url}): {e}")
        print_warning("后续下载可能失败。请检查您的网络。")
        # Ask user if they want to continue anyway
        return ask_yes_no("是否在无网络连接的情况下继续尝试?", default='no')

def check_python_version():
    if sys.version_info < MIN_PYTHON_VERSION:
        print_error(f"Python 版本过低! 需要 >= {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}. 您是: {platform.python_version()}"); sys.exit(1)
    print_success(f"Python 版本检查通过 ({platform.python_version()}).")

def is_in_venv():
     return (hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix))

def check_and_setup_venv():
    if is_in_venv(): print_success("检测到正在虚拟环境 (venv) 中运行。"); return True
    else:
        print_warning("未检测到 Python 虚拟环境 (venv)。"); print_info("强烈建议使用。")
        if ask_yes_no("是否需要查看创建/激活命令并退出脚本以便您操作?", default='no'):
             # ... (print instructions for venv creation/activation) ...
             sys.exit(0)
        print_warning("继续在全局环境中运行，依赖项将安装在全局，不推荐。")
        return False

def check_and_install_requirements():
    print_info(f"检查 Python 库依赖 ({REQUIREMENTS_FILE})...")
    try:
        # Simple import check first
        import flask; import dotenv; import requests; import openai; import tiktoken; import cloudinary; import Pillow
        print_success("核心 Python 依赖库似乎已安装。")
        return True
    except ImportError:
        print_warning("检测到缺少必要的 Python 库。")
        if ask_yes_no(f"是否尝试使用 'pip install -r {REQUIREMENTS_FILE}' 安装? (需要网络)", default='yes'):
             command = [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)]
             result = run_command(command, display_output=True) # Show pip output
             if result is not None and isinstance(result, subprocess.CompletedProcess) and result.returncode == 0:
                 print_success("依赖库安装命令执行成功。")
                 # Simple re-check
                 try: import flask; import dotenv; import requests; print_success("核心库已可导入。"); return True
                 except ImportError: print_error("安装后仍无法导入核心库，请检查 pip 输出。"); return False
             else:
                 print_error("依赖库安装失败。请检查上方 pip 的错误信息和网络连接。")
                 return False
        else:
            print_error(f"依赖库未安装。脚本无法继续。请稍后手动运行 `pip install -r {REQUIREMENTS_FILE}`。")
            return False

def download_with_retries(url, dest_path, description="文件", retries=2, delay=5):
    """Downloads file with retries on failure."""
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    final_dest = DOWNLOADS_DIR / Path(url).name # Download to specific subdir first
    for attempt in range(retries + 1):
        print_info(f"开始下载 {description} (尝试 {attempt + 1}/{retries + 1})...")
        print_info(f"  从: {url}")
        print_info(f"  到: {final_dest}")

        headers = {'User-Agent': USER_AGENT}
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response, open(final_dest, 'wb') as out_file: # Increased timeout
                # Handle potential redirects (urlopen handles basic ones)
                final_url = response.geturl()
                if final_url != url: print_info(f"  (重定向到: {final_url})")
                total_size = int(response.getheader('Content-Length', 0))
                if total_size: print(f"  文件大小: {total_size / (1024*1024):.2f} MB")
                else: print("  未指定文件大小...")

                chunk_size = 8192 * 16 # Larger chunk size
                bytes_read = 0; start_time = time.time()
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk: break
                    out_file.write(chunk); bytes_read += len(chunk)
                    # ... (Progress display - same logic as before) ...
                    if total_size:
                        percent = min(100, int(100 * bytes_read / total_size)); elapsed = time.time() - start_time
                        speed = bytes_read / (1024 * elapsed) if elapsed > 0 else 0
                        eta_sec = (total_size - bytes_read) / (speed * 1024) if speed > 5 else 0 # Only if speed > 5KB/s
                        eta_str = f"{int(eta_sec // 60)}m{int(eta_sec % 60)}s" if speed > 5 and eta_sec < 3600*2 else "~"
                        sys.stdout.write(f"\r下载中: {percent}% @{speed:.1f}KB/s ETA:{eta_str}  ")
                    else: sys.stdout.write(f"\r已下载: {bytes_read / (1024*1024):.2f} MB   ")
                    sys.stdout.flush()
            print() # Newline after progress
            # Verify downloaded size if possible
            if total_size > 0 and abs(final_dest.stat().st_size - total_size) > total_size * 0.01 : # Allow 1% tolerance
                 print_warning(f"下载完成但文件大小不匹配 (预期: {total_size}, 实际: {final_dest.stat().st_size})。文件可能不完整。")
                 # Optionally ask user to retry or continue? For now, return path but warn.
            elif total_size == 0 and final_dest.stat().st_size == 0:
                 print_error("下载完成但文件大小为 0。下载失败。")
                 raise ValueError("Downloaded file size is zero") # Treat as error

            print_success(f"{description} 下载成功！")
            return final_dest # Return Path object
        except urllib.error.HTTPError as e:
            print_error(f"下载 HTTP 错误 (状态码 {e.code}): {e.reason}")
            if e.code == 404: print_error("资源未找到 (404)。URL 可能已失效。"); break # No point retrying 404
            if e.code == 403: print_error("访问被禁止 (403)。可能是权限问题或速率限制。"); break # No point retrying 403
        except urllib.error.URLError as e: print_error(f"下载 URL 错误: {e.reason}") # DNS errors etc.
        except ConnectionResetError: print_error("下载连接被重置。")
        except TimeoutError: print_error("下载连接超时。")
        except Exception as e: print_error(f"下载时发生未知错误: {e}")

        # If loop didn't break and not last attempt, wait and retry
        if attempt < retries:
            print_warning(f"下载将在 {delay} 秒后重试...")
            time.sleep(delay)
        else:
            print_error(f"{description} 下载失败，已达到最大重试次数。")
            if final_dest.exists(): 
                try: os.remove(final_dest); 
                except Exception: pass # Clean up failed download
            return None

def extract_archive(archive_path, extract_dir):
    print_info(f"正在解压 {archive_path.name} 到 {extract_dir}...")
    extract_dir.mkdir(parents=True, exist_ok=True)
    # Clean target directory before extraction? Risky if user put files there.
    # Let's extract and potentially overwrite instead.
    extracted_members = []
    try:
        if archive_path.suffix == '.zip':
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                # Check for common archive vulnerability (absolute paths)
                for member in zip_ref.infolist():
                    member_path = Path(member.filename)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        raise IOError(f"压缩文件包含无效/危险的路径: {member.filename}")
                extracted_members = zip_ref.namelist()
                zip_ref.extractall(extract_dir)
            print_success("成功解压 (zip).")
            return True, extracted_members
        elif archive_path.name.endswith('.tar.gz'):
            with tarfile.open(archive_path, "r:gz") as tar:
                 # Check members before extraction
                 for member in tar.getmembers():
                     member_path = Path(member.name)
                     if member_path.is_absolute() or ".." in member_path.parts or member.issym() or member.islnk(): # Check for symlinks too
                         raise IOError(f"压缩文件包含无效/危险的路径或链接: {member.name}")
                 extracted_members = [m.name for m in tar.getmembers()] # Get names again safely
                 tar.extractall(path=extract_dir, members=[m for m in tar.getmembers() if not (m.issym() or m.islnk())]) # Extract only regular files/dirs
            print_success("成功解压 (tar.gz).")
            return True, extracted_members
        else:
            print_error(f"不支持的压缩格式: {archive_path.name}")
            return False, []
    except zipfile.BadZipFile: print_error(f"文件损坏或不是有效的 Zip 文件: {archive_path.name}"); return False, []
    except tarfile.TarError as e: print_error(f"Tar 文件错误: {e}"); return False, []
    except Exception as e: print_error(f"解压时出错: {e}"); return False, []
    finally:
        # Clean up archive only if extraction was fully successful?
        # Let's leave it for now in case user needs to retry manually.
        pass

def find_and_move_executable(extracted_dir, target_exe_name_pattern, dest_dir):
    """Searches extracted dir using regex for target exe and moves it."""
    print_info(f"在 {extracted_dir} 中搜索匹配 '{target_exe_name_pattern.pattern}' 的文件...")
    found_exe_path = None
    best_match_path = None # Prefer path with 'bin' in it

    # Using rglob for recursive search
    for item in extracted_dir.rglob("*"):
        rel_path_str = str(item.relative_to(extracted_dir)).replace("\\", "/")
        if item.is_file() and target_exe_name_pattern.search(rel_path_str):
            current_path = item
            # Heuristic: Prefer paths containing 'bin' directory
            if 'bin' in [p.name.lower() for p in current_path.parents]:
                if not best_match_path or len(current_path.parts) < len(best_match_path.parts): # Prefer higher-level 'bin'
                    best_match_path = current_path
            elif not best_match_path: # Found a match, but not in 'bin', keep as fallback
                 if not found_exe_path or len(current_path.parts) < len(found_exe_path.parts): # Prefer shorter paths
                      found_exe_path = current_path

    # Use the 'bin' path if found, otherwise the shortest non-bin path
    final_found_exe = best_match_path or found_exe_path

    if not final_found_exe:
        print_error(f"在 {extracted_dir} 中未能自动定位到匹配 '{target_exe_name_pattern.pattern}' 的可执行文件。")
        return None

    print_success(f"找到可执行文件: {final_found_exe}")
    dest_path = dest_dir / expected_exe_name_from_pattern(target_exe_name_pattern) # Use expected final name

    # Ensure dest_dir exists
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        shutil.move(str(final_found_exe), str(dest_path))
        print_success(f"已将找到的文件移动到: {dest_path}")
        # Set executable permission
        if platform.system() != "Windows":
            try:
                # Read/Execute for User, Group; Read/Execute for Others
                mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
                dest_path.chmod(mode)
                print_info("已设置执行权限 (Linux/macOS)。")
            except Exception as chmod_e: print_warning(f"设置执行权限失败: {chmod_e}")
        return str(dest_path.resolve()) # Return absolute str path
    except Exception as e:
        print_error(f"移动 '{final_found_exe.name}' 到 '{dest_path}' 时出错: {e}")
        # Try to copy as a fallback? Maybe not, complicates things.
        return None

def expected_exe_name_from_pattern(pattern):
    """Gets the base executable name from a regex pattern (heuristic)."""
    if "ffmpeg" in pattern.pattern.lower():
        return FFMPEG_EXPECTED_EXE
    if "mkcert" in pattern.pattern.lower():
        return MKCERT_EXPECTED_EXE
    # Fallback (less ideal)
    match = re.search(r'([a-zA-Z0-9_-]+)(\.exe)?', pattern.pattern)
    return match.group(0) if match else "executable"

def get_platform_key():
    """Determines a key string for the current platform."""
    sys_plat = platform.system().lower()
    sys_arch = platform.machine().lower()
    if sys_plat == "windows" and sys_arch.endswith("64"): return "windows_amd64"
    if sys_plat == "darwin": return "darwin_" + ("arm64" if "arm" in sys_arch else "amd64")
    if sys_plat == "linux" and sys_arch == "x86_64": return "linux_amd64"
    print_warning(f"无法识别的平台组合: 系统={sys_plat}, 架构={sys_arch}")
    return None

def get_latest_github_release_url(repo, asset_pattern):
    # ... (Same as before, with User-Agent, timeout, 403 handling) ...
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"; headers = {'User-Agent': USER_AGENT, 'Accept': 'application/vnd.github.v3+json'}
    request = urllib.request.Request(api_url, headers=headers)
    print_info(f"尝试从 GitHub API 获取 {repo} 最新版本...")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status == 200:
                release_data = json.loads(response.read().decode())
                for asset in release_data.get('assets', []):
                    if asset_pattern and re.match(asset_pattern, asset['name']):
                        print_info(f"找到匹配资源: {asset['name']}")
                        return asset['browser_download_url']
                print_warning(f"在 {repo} 最新版本中未找到匹配 '{asset_pattern or ''}' 的资源。")
            elif response.status == 403: print_warning(f"GitHub API 请求被拒绝 (状态: {response.status}) - 可能触发速率限制。")            
            else: print_warning(f"GitHub API 错误 (状态: {response.status} {response.reason})。")
    except Exception as e: print_warning(f"访问 GitHub API 时出错: {e}")
    return None

def open_folder(path):
    """Opens the specified folder in the default file explorer."""
    resolved_path = Path(path).resolve() # Ensure path is absolute
    print_info(f"尝试打开文件夹: {resolved_path}")
    try:
        if platform.system() == "Windows": os.startfile(resolved_path)
        elif platform.system() == "Darwin": subprocess.run(['open', str(resolved_path)], check=True)
        else: subprocess.run(['xdg-open', str(resolved_path)], check=True) # Linux desktop
    except FileNotFoundError: # If open/xdg-open not found
        print_error("无法找到用于打开文件夹的命令 (xdg-open/open)。")
        print_info(f"请手动导航到: {resolved_path}")
    except Exception as e:
        print_error(f"无法自动打开文件夹: {e}")
        print_info(f"请手动导航到: {resolved_path}")

def user_action_required(message, folder_to_open=None):
    """Prints a prominent message indicating user needs to do something."""
    print_action(f"[ 用户操作要求 ] {message}")
    if folder_to_open:
        if ask_yes_no(f"是否打开相关文件夹 ({folder_to_open}) 以方便操作?", default="yes"):
            open_folder(folder_to_open)

def setup_tool(tool_name, expected_exe_name, expected_exe_pattern, # Pass regex pattern now
                    download_urls=None,
                    github_repo=None, github_version="latest",
                    github_asset_name_pattern=None, # Pattern for matching asset filename
                    github_fallback_urls=None):
    """Comprehensive function to find, download, extract, and set up a tool."""
    print_info(f"--- 开始设置工具: {tool_name} ---")
    BIN_DIR.mkdir(exist_ok=True); DOWNLOADS_DIR.mkdir(exist_ok=True)

    # 1. Check if already available
    exe_path = find_executable(expected_exe_name)
    if exe_path:
        print_success(f"已找到 {tool_name}: {exe_path}")
        # Basic version check
        test_cmd = [exe_path, "-version"] if tool_name in ["ffmpeg", "mkcert"] else None
        if test_cmd:
            run_command(test_cmd, capture_output=True, timeout=5) # Just run, don't check output strictly
        return exe_path

    print_warning(f"在本地工具目录或系统 PATH 中未找到 '{expected_exe_name}'。")

    # 2. Determine download URL
    platform_key = get_platform_key()
    download_url = None
    if not platform_key:
         print_error("无法确定当前平台，无法自动下载。")
    else:
        # Try GitHub first if configured
        if github_repo:
            asset_pattern = github_asset_name_pattern.get(platform_key) if github_asset_name_pattern else None
            if not asset_pattern:
                print_warning(f"未找到适用于平台 '{platform_key}' 的 GitHub 资源名称模式。")
            else:
                api_url = f"https://api.github.com/repos/{github_repo}/releases"
                api_url += "/latest" if github_version == "latest" else f"/tags/{github_version}"
                print_info(f"尝试从 GitHub 获取版本 [{github_version}] 的 release 信息: {api_url}")

                headers = {'User-Agent': USER_AGENT}
                try:
                    request = urllib.request.Request(api_url, headers=headers)
                    with urllib.request.urlopen(request, timeout=10) as response:
                        data = json.loads(response.read().decode())
                        for asset in data.get("assets", []):
                            if re.match(asset_pattern, asset["name"]):
                                print_success(f"找到匹配资源: {asset['name']}")
                                download_url = asset["browser_download_url"]
                                break
                        else:
                            print_warning("未在 GitHub release 中找到匹配资源。")
                except Exception as e:
                    print_warning(f"GitHub 请求失败: {e}")

        # Fallback URL
        if not download_url and github_fallback_urls and github_fallback_urls.get(platform_key):
            print_info("使用 fallback 下载链接。")
            download_url = github_fallback_urls[platform_key]

        # Optional: direct download URLs（优先级最低）
        if not download_url and download_urls and download_urls.get(platform_key):
            print_info("使用直接配置的下载链接。")
            download_url = download_urls[platform_key]

    # 3. Offer and Download
    if not ask_yes_no(f"是否尝试从此链接下载 {tool_name}?\n  {download_url}", default='yes'):
         print_info(f"跳过 {tool_name} 下载。需要手动安装。")
         user_action_required(f"请手动下载 '{expected_exe_name}' 并将其放入 '{BIN_DIR}' 文件夹。", BIN_DIR)
         return None
    downloaded_path = download_with_retries(download_url, DOWNLOADS_DIR / Path(download_url).name, tool_name)
    if not downloaded_path:
         print_error(f"{tool_name} 下载失败。")
         user_action_required(f"请手动下载 '{expected_exe_name}' 并将其放入 '{BIN_DIR}' 文件夹。", BIN_DIR)
         return None

    # 4. Extract or Move
    final_exe_path = None
    temp_extract_dir = DOWNLOADS_DIR / f"{tool_name}_extracted_{int(time.time())}"
    is_archive = downloaded_path.suffix in ['.zip', '.gz'] or downloaded_path.name.endswith('.tar.gz') # More robust tar.gz check

    if is_archive:
        success, _ = extract_archive(downloaded_path, temp_extract_dir)
        if success:
             final_exe_path = find_and_move_executable(temp_extract_dir, expected_exe_pattern, BIN_DIR)
             # Clean extraction dir on success
             try: shutil.rmtree(temp_extract_dir); 
             except Exception: pass
             # Clean archive on success
             try: downloaded_path.unlink(); 
             except Exception: pass
        else:
             print_error(f"解压 {downloaded_path.name} 失败。")
             user_action_required(f"请手动从 '{downloaded_path}' 解压，找到 '{expected_exe_name}'，并将其放入 '{BIN_DIR}'。", DOWNLOADS_DIR)
             # Don't delete failed extraction/archive
    else: # Assume direct executable/binary
         dest_path = BIN_DIR / expected_exe_name
         try:
             shutil.move(str(downloaded_path), str(dest_path))
             print_success(f"已将下载的文件移动到: {dest_path}")
             if platform.system() != "Windows": # Set executable
                 try: dest_path.chmod(dest_path.stat().st_mode | stat.S_IXUSR | stat.S_IRGRP| stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
                 except Exception as chmod_e: print_warning(f"设置执行权限失败: {chmod_e}")
             final_exe_path = str(dest_path.resolve())
             # Clean archive (which is the exe itself here) is done by move
         except Exception as e:
             print_error(f"移动下载的 {expected_exe_name} 到 {BIN_DIR} 时出错: {e}")
             user_action_required(f"请手动将 '{downloaded_path.name}' 移动到 '{BIN_DIR}' 并重命名为 '{expected_exe_name}'。", DOWNLOADS_DIR)

    # 5. Final Verification
    if final_exe_path:
        print_info(f"验证 {tool_name} ({final_exe_path})...")
        test_cmd = [final_exe_path, "-version"] if tool_name in ["ffmpeg", "mkcert"] else None
        if test_cmd:
             result = run_command(test_cmd, capture_output=True, timeout=10)
             if result and isinstance(result, subprocess.CompletedProcess) and result.returncode == 0:
                 print_success(f"{tool_name} 设置并验证成功！")
                 os.environ['PATH'] = str(BIN_DIR.resolve()) + os.pathsep + os.environ.get('PATH', '') # Update session PATH
                 return final_exe_path # Success!
             else:
                 print_error(f"运行 '{' '.join(test_cmd)}' 失败。工具可能已损坏或不兼容。")
                 user_action_required(f"请检查或替换 '{BIN_DIR / expected_exe_name}' 文件。", BIN_DIR)
                 return None # Verification failed
        else: # No test command defined, assume success if moved
             print_success(f"{tool_name} 已放置到 {final_exe_path} (无自动验证)。")
             os.environ['PATH'] = str(BIN_DIR.resolve()) + os.pathsep + os.environ.get('PATH', '')
             return final_exe_path
    else:
         # Setup failed earlier (download, extract, move etc.)
         print_error(f"{tool_name} 自动设置失败。")
         # The specific user_action message was printed where it failed.
         return None # Explicitly return None on failure

# --- 主程序 ---
def main():
    print_header("直播聊天 AI 代理 - 全自动配置向导 (实验版)")
    # ... (Intro text) ...
    print("此脚本将尽最大努力自动完成所有设置，包括检查、下载依赖和配置。")
    print("请跟随提示操作。如果遇到问题，脚本会提供详细的手动操作指引。")
    print("----------------------------------------------------------------------")
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"后端目录: {BACKEND_DIR}")
    print(f"本地工具目录: {BIN_DIR}")
    print("----------------------------------------------------------------------\n")
    time.sleep(1) # Pause for user to read paths

    # --- 0. 环境预检查 ---
    print_step(0, "环境预检查")
    if not check_network(): # Check network first
        if not ask_yes_no("无网络连接，是否仍要继续（仅配置，不下载）?", default='no'):
            sys.exit(1)
    check_python_version()
    check_and_setup_venv()
    if not check_and_install_requirements():
        print_error("Python 依赖库未能成功安装。脚本无法继续。")
        sys.exit(1)

    # --- 1. 工具依赖设置 ---
    print_step(1, "核心工具设置 (FFmpeg, mkcert)")
    ffmpeg_path = setup_tool("ffmpeg", FFMPEG_EXPECTED_EXE, FFMPEG_INTERNAL_PATH_PATTERN, download_urls=FFMPEG_URLS)
    mkcert_path = setup_tool("mkcert", MKCERT_EXPECTED_EXE, re.compile(MKCERT_EXPECTED_EXE, re.IGNORECASE),
                              github_repo=MKCERT_REPO, github_version=MKCERT_VERSION_TARGET,
                              github_asset_name_pattern={
                                                            k: re.escape(Path(v).name)  # 提取出下载链接中的真实文件名，并转义成正则
                                                            for k, v in MKCERT_FALLBACK_URLS.items()
                                                        },
                              github_fallback_urls=MKCERT_FALLBACK_URLS)

    # --- 1b. mkcert CA 安装 ---
    mkcert_ca_installed = False
    needs_ca_check = False # Assume CA check only needed if we intend to use mkcert locally later
    # We'll perform the check/install attempt *before* asking about SSL mode
    if mkcert_path:
        print_step("1b", "mkcert 本地证书颁发机构 (CA) 设置")
        print_info("mkcert 需要安装一个本地 CA 到系统信任库，以便浏览器信任其颁发的证书。")
        if ask_yes_no("是否尝试自动检查/安装 mkcert CA (通常仅需运行一次)?", default='yes'):
            needs_ca_check = True
            print_warning("此步骤可能需要 **管理员权限**。")
            print_warning("请注意屏幕上是否弹出 **UAC 提示 (Windows)** 或要求 **输入密码 (macOS/Linux)**，并根据提示操作。")
            time.sleep(2) # Give user time to read warning
            cmd = [mkcert_path, "-install"]
            result = run_command(cmd, display_output=True, timeout=120) # Longer timeout for potential UAC prompt
            if result is not None and isinstance(result, subprocess.CompletedProcess) and result.returncode == 0:
                 output = result.stdout.lower() + "\n" + result.stderr.lower() if result.stderr else "" # Combine outputs
                 # Look for positive confirmation or already installed messages
                 if "ca installed" in output or "already installed" in output or "安装成功" in output or "已安装" in output or "certificate authority" in output or "added" in output:
                      print_success("mkcert CA 安装/验证成功！")
                      mkcert_ca_installed = True
                 else: # Command succeeded but output is ambiguous
                      print_warning("'mkcert -install' 命令已执行，但无法完全确认 CA 状态。假定成功。")
                      mkcert_ca_installed = True # Optimistic assumption
            else: # Command failed or didn't run
                 print_error("'mkcert -install' 未能成功执行。")
                 print_warning("如果后续使用本地 HTTPS (localhost) 时浏览器提示证书不受信任，")
                 user_action_required(f"请手动以 **管理员身份** 运行: `\"{mkcert_path}\" -install`", BIN_DIR)
        else:
             print_info("跳过 mkcert CA 自动安装/检查。")

    # --- 2. 创建/加载 .env ---
    print_step(2, "创建/加载 .env 配置文件")
    # ... (Same logic: choose lang, copy template, load config) ...
    chosen_template = None; config = {}
    if ENV_FILE.exists():
        print_info(f"`{ENV_FILE}` 文件已存在。加载现有配置。"); config = load_env(ENV_FILE)
        try: # Guess template for comment style
            with open(ENV_FILE, 'r', encoding='utf-8') as f: content = f.read()
            if "LLM (Language Model) Configuration" in content: chosen_template = ENV_EXAMPLE_EN
            elif "LLM（语言模型）配置" in content: chosen_template = ENV_EXAMPLE_ZH
            else: chosen_template = ENV_EXAMPLE_ZH
        except Exception: chosen_template = ENV_EXAMPLE_ZH
    else:
        lang_choice = ask_choice("选择配置文件注释语言:", ["中文 (zh-CN)", "English (en)"], default="中文 (zh-CN)")
        chosen_template = ENV_EXAMPLE_ZH if lang_choice.startswith("中文") else ENV_EXAMPLE_EN
        try: shutil.copy(chosen_template, ENV_FILE); print_success(f"已将 `{chosen_template.name}` 复制为 `{ENV_FILE}`."); config = load_env(ENV_FILE)
        except Exception as e: print_error(f"创建/复制 `{ENV_FILE}` 失败: {e}"); sys.exit(1)

    # --- 3. 核心服务器设置 (SSL 逻辑简化) ---
    print_step(3, "核心服务器设置")
    config['SERVER_HOST'] = ask_choice("服务器监听地址:", ['0.0.0.0', '127.0.0.1'], default=config.get('SERVER_HOST', '0.0.0.0'))
    config['SERVER_PORT'] = ask_integer("服务器监听端口:", default=int(config.get('SERVER_PORT', 8181)), min_val=1, max_val=65535)

    # SSL Decision Tree
    enable_ssl_default = config.get('SERVER_ENABLE_SSL','true').lower() == 'true' # Default to true if not set
    use_ssl = ask_yes_no("是否启用 HTTPS (SSL/TLS)? (强烈推荐)", default='yes' if enable_ssl_default else 'no')
    config['SERVER_ENABLE_SSL'] = use_ssl
    config['SSL_CERT_PATH'] = "" # Reset paths
    config['SSL_KEY_PATH'] = ""
    config['SERVER_DOMAIN'] = config.get('SERVER_DOMAIN','') # Keep domain if already set

    if use_ssl:
        is_local_host = config['SERVER_HOST'] == '127.0.0.1'
        auto_cert_generated = False
        if is_local_host and mkcert_path: # Localhost + mkcert available
             if mkcert_ca_installed: # Ideal case
                 print_info("本地模式，且 mkcert CA 已就绪。")
                 if ask_yes_no("是否自动生成 localhost 证书 (推荐)?", default='yes'):
                     cmd = [mkcert_path, "localhost"]; result = run_command(cmd, cwd=BACKEND_DIR)
                     cert_file = BACKEND_DIR / "localhost.pem"; key_file = BACKEND_DIR / "localhost-key.pem"
                     if result and isinstance(result, subprocess.CompletedProcess) and result.returncode == 0 and cert_file.exists() and key_file.exists():
                         print_success("成功生成 localhost 证书！"); config['SSL_CERT_PATH'] = str(cert_file.resolve()); config['SSL_KEY_PATH'] = str(key_file.resolve()); auto_cert_generated = True
                     else: print_error("mkcert 生成失败。请检查权限或手动生成。")
             else: # CA not installed, maybe generate untrusted cert?
                 print_warning("mkcert CA 未成功安装/验证。生成的证书浏览器可能不信任。")
                 if ask_yes_no("是否仍要尝试生成 (可能不被信任的) localhost 证书?", default='no'):
                     cmd = [mkcert_path, "localhost"]; result = run_command(cmd, cwd=BACKEND_DIR)
                     # ... (check result, set paths if generated) ...
                     cert_file = BACKEND_DIR / "localhost.pem"; key_file = BACKEND_DIR / "localhost-key.pem"
                     if result and isinstance(result, subprocess.CompletedProcess) and result.returncode == 0 and cert_file.exists() and key_file.exists():
                         print_success("证书已生成(可能不被信任)。"); config['SSL_CERT_PATH'] = str(cert_file.resolve()); config['SSL_KEY_PATH'] = str(key_file.resolve()); auto_cert_generated = True
                     else: print_error("生成失败。")

        # Manual path input if not local, mkcert unavailable, or auto-gen failed/skipped
        if not auto_cert_generated:
             print_info("需要手动指定 SSL 证书和密钥文件路径。")
             if config['SERVER_HOST'] != '127.0.0.1':
                 print_info(" (服务器部署请先使用 Certbot 等工具获取。)")
                 print_info("   例如: sudo certbot certonly --standalone -d your.domain.com")
                 config['SERVER_DOMAIN'] = ask_string("请输入您的域名 (可选，用于提示)", default=config.get('SERVER_DOMAIN',''))
             default_cert = str(BACKEND_DIR / "localhost.pem") if is_local_host else config.get('SSL_CERT_PATH','')
             default_key = str(BACKEND_DIR / "localhost-key.pem") if is_local_host else config.get('SSL_KEY_PATH','')
             print_info("请提供 .pem 或 .crt 格式的证书文件和 .key 或 .pem 格式的私钥文件。")
             config['SSL_CERT_PATH'] = ask_path("证书文件路径", default=default_cert, check_exists=True, must_exist=False, is_file=True)
             config['SSL_KEY_PATH'] = ask_path("私钥文件路径", default=default_key, check_exists=True, must_exist=False, is_file=True)

        # Final check
        if not config.get('SSL_CERT_PATH') or not config.get('SSL_KEY_PATH'):
             print_error("启用 HTTPS 但未有效设置证书/密钥路径！服务器将无法启动。")
             print_info(f"请编辑 '{ENV_FILE.resolve()}' 并填写 SSL_CERT_PATH 和 SSL_KEY_PATH。")

    # --- 4. LLM 配置 ---
    print_step(4, "LLM (大语言模型) 配置")
    print_info("提示：推荐使用 claude-3-7-sonnet-20250219")
    llm_provider = ask_choice("请选择您要使用的大模型服务平台:", [
        "OpenAI",
        "Azure OpenAI",
        "API2D (OpenAI代理服务)",
        "OpenRouter (聚合 Claude/Gemini 等)",
        "Claude (Anthropic)",
        "Gemini (Google AI)",
        "DeepSeek (国产 GPT 类模型)",
        "Groq (极速模型)",
        "自建或其他兼容 OpenAI API 的平台"
    ], default=config.get('LLM_PROVIDER', 'OpenAI'))
    config['LLM_PROVIDER'] = llm_provider
    
    if llm_provider == "OpenAI":
        config['LLM_API_URL'] = "https://api.openai.com/v1"
        if ask_yes_no("需要打开 OpenAI API 密钥页面吗?", default='yes'):
            webbrowser.open("https://platform.openai.com/api-keys")
        print_info("提示：为保护您的密钥安全，输入时不会显示内容。")
        config['LLM_API_KEY'] = ask_string("请输入 OpenAI API 密钥", default=config.get('LLM_API_KEY'), required=True, secret=True)
        config['LLM_API_MODEL'] = ask_string("要使用的模型名称 (例如 gpt-4o)", default=config.get('LLM_API_MODEL', 'gpt-4o'))

    elif llm_provider == "Azure OpenAI":
        config['LLM_API_URL'] = ask_string("请输入 Azure OpenAI API 端点 (以 https:// 开头)", default=config.get('LLM_API_URL'), required=True)
        if ask_yes_no("需要打开 Azure OpenAI 密钥页面吗?", default='yes'):
            webbrowser.open("https://portal.azure.com/")
        print_info("提示：为保护您的密钥安全，输入时不会显示内容。")
        config['LLM_API_KEY'] = ask_string("请输入 Azure OpenAI API 密钥", default=config.get('LLM_API_KEY'), required=True, secret=True)
        config['LLM_API_MODEL'] = ask_string("模型名称 (如 gpt-4、gpt-35-turbo)", default=config.get('LLM_API_MODEL', 'gpt-4'))

    elif llm_provider == "API2D (OpenAI代理服务)":
        config['LLM_API_URL'] = "https://openai.api2d.net/v1"
        if ask_yes_no("需要打开 API2D 密钥页面吗?", default='yes'):
            webbrowser.open("https://api2d.com/account/api")
        print_info("提示：为保护您的密钥安全，输入时不会显示内容。")
        config['LLM_API_KEY'] = ask_string("请输入 API2D API Key", default=config.get('LLM_API_KEY'), required=True, secret=True)
        config['LLM_API_MODEL'] = ask_string("模型名称 (如 gpt-4、gpt-3.5-turbo)", default=config.get('LLM_API_MODEL', 'gpt-4'))

    elif llm_provider == "OpenRouter (聚合 Claude/Gemini 等)":
        config['LLM_API_URL'] = "https://openrouter.ai/api/v1"
        if ask_yes_no("需要打开 OpenRouter 密钥页面吗?", default='yes'):
            webbrowser.open("https://openrouter.ai/keys")
        print_info("提示：为保护您的密钥安全，输入时不会显示内容。")
        config['LLM_API_KEY'] = ask_string("请输入 OpenRouter API Key", default=config.get('LLM_API_KEY'), required=True, secret=True)
        config['LLM_API_MODEL'] = ask_string("模型名称 (如 openai/gpt-4、google/gemini-pro)", default=config.get('LLM_API_MODEL', 'openai/gpt-4'))

    elif llm_provider == "Claude (Anthropic)":
        config['LLM_API_URL'] = "https://api.anthropic.com/v1"
        if ask_yes_no("需要打开 Claude API 密钥页面吗?", default='yes'):
            webbrowser.open("https://console.anthropic.com/settings/keys")
        print_info("提示：为保护您的密钥安全，输入时不会显示内容。")
        config['LLM_API_KEY'] = ask_string("请输入 Claude API Key", default=config.get('LLM_API_KEY'), required=True, secret=True)
        config['LLM_API_MODEL'] = ask_choice("请选择 Claude 模型", ["claude-3-opus-20240229", "claude-3-sonnet-20240229"], default="claude-3-sonnet-20240229")

    elif llm_provider == "Gemini (Google AI)":
        config['LLM_API_URL'] = "https://generativelanguage.googleapis.com/v1beta"
        if ask_yes_no("需要打开 Gemini 密钥页面吗?", default='yes'):
            webbrowser.open("https://makersuite.google.com/app/apikey")
        print_info("提示：为保护您的密钥安全，输入时不会显示内容。")
        config['LLM_API_KEY'] = ask_string("请输入 Gemini API Key", default=config.get('LLM_API_KEY'), required=True, secret=True)
        config['LLM_API_MODEL'] = ask_choice("请选择 Gemini 模型", ["gemini-pro", "gemini-1.5-pro-latest"], default="gemini-pro")

    elif llm_provider == "DeepSeek (中国产 GPT 类模型)":
        config['LLM_API_URL'] = "https://api.deepseek.com/v1"
        if ask_yes_no("需要打开 DeepSeek 密钥页面吗?", default='yes'):
            webbrowser.open("https://platform.deepseek.com/console/apikeys")
        print_info("提示：为保护您的密钥安全，输入时不会显示内容。")
        config['LLM_API_KEY'] = ask_string("请输入 DeepSeek API Key", default=config.get('LLM_API_KEY'), required=True, secret=True)
        config['LLM_API_MODEL'] = ask_choice("请选择模型", ["deepseek-chat", "deepseek-coder"], default="deepseek-chat")

    elif llm_provider == "Groq (极速模型)":
        config['LLM_API_URL'] = "https://api.groq.com/openai/v1"
        if ask_yes_no("需要打开 Groq 密钥页面吗?", default='yes'):
            webbrowser.open("https://console.groq.com/keys")
        print_info("提示：为保护您的密钥安全，输入时不会显示内容。")
        config['LLM_API_KEY'] = ask_string("请输入 Groq API Key", default=config.get('LLM_API_KEY'), required=True, secret=True)
        config['LLM_API_MODEL'] = ask_choice("请选择模型", ["llama3-70b-8192", "mixtral-8x7b-32768"], default="llama3-70b-8192")

    else:
        # 自建或通用 OpenAI API 兼容服务
        if ask_yes_no("需要打开 OpenAI API 文档页面 (了解格式)?", default='yes'):
            webbrowser.open("https://platform.openai.com/docs/api-reference")
        print_info("提示：为保护您的密钥安全，输入时不会显示内容。")
        config['LLM_API_URL'] = ask_string("输入 API 的基准 URL (例如 https://api.openai.com/v1)", default=config.get('LLM_API_URL', ''), required=True, validation_func=lambda u: (u.startswith("http"), "URL应以http开头"))
        config['LLM_API_KEY'] = ask_string("请输入 API 密钥", default=config.get('LLM_API_KEY'), required=True, secret=True)
        config['LLM_API_MODEL'] = ask_string("模型名称 (例如 gpt-3.5-turbo)", default=config.get('LLM_API_MODEL', ''))
    
    # 统一配置剩余参数（不论厂商）
    config['LLM_TOKENIZER_MODEL'] = ask_string("用于计数的 Tokenizer 模型 (输入GPT-4/GPT-4o/GPT-3.5)", default=config.get('LLM_TOKENIZER_MODEL', config.get('LLM_API_MODEL', 'gpt-4o')))
    config['LLM_MAX_RESPONSE_TOKENS'] = ask_integer("LLM 一次最多生成 Token 数", default=int(config.get('LLM_MAX_RESPONSE_TOKENS', 2000)), min_val=50)
    config['PROMPT_MAX_TOTAL_TOKENS'] = ask_integer("总提示+响应缓冲区最大 Token 数", default=int(config.get('PROMPT_MAX_TOTAL_TOKENS', 4096)), min_val=512)
    # --- 5. STT 配置 (自动设置 FFMPEG) ---
    print_step(5, "语音转文字 (STT) 配置")
    stt_provider = ask_choice("选择 STT 提供商:", ['youdao', 'whisper', 'both', 'compare'], default=config.get('STT_PROVIDER', 'youdao'))
    config['STT_PROVIDER'] = stt_provider
    if stt_provider in ['youdao', 'both']:
        if ask_yes_no("需要打开有道智云官网 (申请 Key/Secret)?", default='yes'): webbrowser.open("https://ai.youdao.com/")
        print_info(f"请选择 智能语音服务 - 短语音识别")
        config['YOUDAO_APP_KEY'] = ask_string("有道 App Key (也就是应用ID)", default=config.get('YOUDAO_APP_KEY'), required=True, secret=True)
        config['YOUDAO_APP_SECRET'] = ask_string("有道 App Secret", default=config.get('YOUDAO_APP_SECRET'), required=True, secret=True)
        # Configure FFMPEG path
        if ffmpeg_path:
            config['FFMPEG_PATH'] = ffmpeg_path
            print_success(f"已自动配置 FFMPEG_PATH 为: {ffmpeg_path}")
        else: # Auto setup failed or skipped
            print_error("FFmpeg 未能自动设置成功，但有道 STT 需要它。")
            config['FFMPEG_PATH'] = ask_path("请输入 FFmpeg 可执行文件的完整路径", default=config.get('FFMPEG_PATH', 'ffmpeg'), must_exist=True, is_file=True, ensure_executable=True)
            # Verify manually entered path
            verif_cmd = [config['FFMPEG_PATH'], '-version']
            if not run_command(verif_cmd, capture_output=True):
                 print_error(f"提供的 FFmpeg 路径 '{config['FFMPEG_PATH']}' 无法执行或无效。有道 STT 将会失败！")
    else: config['YOUDAO_APP_KEY'] = ''; config['YOUDAO_APP_SECRET'] = ''

    # --- 6. Vision / 7. Other / 8. Save Config (Same logic) ---
    print_step(6, "视觉/截图 配置 (可选)")
    # ... (Enable, provider, keys/folder logic...)
    config['VISION_ENABLE'] = ask_yes_no("启用截图处理功能?", default='yes' if config.get('VISION_ENABLE', 'false').lower() == 'true' else 'no')
    if config['VISION_ENABLE']:
        config['VISION_UPLOAD_PROVIDER'] = ask_choice("截图上传服务商:", ['cloudinary', 'none'], default=config.get('VISION_UPLOAD_PROVIDER', 'cloudinary'))
        if config['VISION_UPLOAD_PROVIDER'] == 'cloudinary': # Need Cloudinary credentials
            if ask_yes_no("需要打开 Cloudinary 官网 (注册/获取 Key)?", default='yes'): webbrowser.open("https://cloudinary.com/users/register/free")
            config['CLOUDINARY_CLOUD_NAME'] = ask_string("Cloudinary Cloud Name", default=config.get('CLOUDINARY_CLOUD_NAME'), required=True)
            config['CLOUDINARY_API_KEY'] = ask_string("Cloudinary API Key", default=config.get('CLOUDINARY_API_KEY'), required=True, secret=True)
            config['CLOUDINARY_API_SECRET'] = ask_string("Cloudinary API Secret", default=config.get('CLOUDINARY_API_SECRET'), required=True, secret=True)
            config['CLOUDINARY_UPLOAD_FOLDER'] = ask_string("Cloudinary 上传文件夹", default=config.get('CLOUDINARY_UPLOAD_FOLDER', 'live_screenshot'))
        else: # 'none' or others don't need keys here
              config['CLOUDINARY_CLOUD_NAME'] = ''; config['CLOUDINARY_API_KEY'] = ''; config['CLOUDINARY_API_SECRET'] = ''; config['CLOUDINARY_UPLOAD_FOLDER'] = ''
    else: # Vision disabled - clear all related fields
        config['VISION_ENABLE'] = False; config['VISION_UPLOAD_PROVIDER']='none'; config['CLOUDINARY_CLOUD_NAME']=''; config['CLOUDINARY_API_KEY']=''; config['CLOUDINARY_API_SECRET']=''; config['CLOUDINARY_UPLOAD_FOLDER']=''

    print_step(7, "其他设置")
    config['SERVER_TEST_MODE'] = ask_yes_no("启用测试模式 (保存调试文件到 test/)?", default='yes' if config.get('SERVER_TEST_MODE', 'false').lower() == 'true' else 'no')
    config['SYSTEM_PROMPT_PATH'] = ask_path("自定义系统提示文件路径 (可选, UTF-8 编码)", default=config.get('SYSTEM_PROMPT_PATH',''), check_exists=True, must_exist=False, is_file=True)

    print_step(8, "保存 .env 配置")
    print("以下配置将保存到 " + str(ENV_FILE.resolve())); print_separator('-')
    for key, value in sorted(config.items()): # Sort for readability
        display_value = "******" if any(k in key for k in ['KEY', 'SECRET', 'TOKEN']) and value else value
        print(f"  {key:<28} = {display_value}") # Align output
    print_separator('-')
    if ask_yes_no("确认保存?", default='yes'):
        if not save_env(ENV_FILE, config, chosen_template): print_error("保存失败!"); sys.exit(1)
    else: print("配置未保存，已退出。"); sys.exit(0)

    # --- 9. Frontend Setup Guidance ---
    print_step(9, "前端用户脚本设置指导")
    print_success("后端配置已保存！现在请设置浏览器用户脚本。")
    time.sleep(1)
    # 引导安装用户脚本管理器
    while True:
        has_tm = ask_yes_no("您的浏览器是否已安装 Tampermonkey (油猴) 或 Violentmonkey (暴力猴)?", default="yes")
        if has_tm:
            break
        print_warning("您需要先安装用户脚本管理器才能继续下一步。")
        if ask_yes_no("是否现在打开 Tampermonkey 官网?", default='yes'):
            webbrowser.open("https://www.tampermonkey.net/")
        print_info("请完成安装后返回此窗口，再输入 'y' 继续。")

    # Calculate backend URL for frontend script
    backend_proto = "https" if config.get('SERVER_ENABLE_SSL') else "http"
    backend_host = config.get('SERVER_HOST', 'localhost')
    if config.get('SERVER_ENABLE_SSL') and backend_host == '127.0.0.1': backend_host = 'localhost' # CRITICAL fix for mkcert
    backend_port = config.get('SERVER_PORT', 8181)
    api_endpoint_url = f"{backend_proto}://{backend_host}:{backend_port}/upload"

    print("\n请按以下步骤操作:")
    frontend_script_url = "https://github.com/bOOOOcG/Live_Stream_Chat_AI_Agent/raw/main/frontend/live-stream-chat-ai-agent.user.js" # Confirm this URL is correct
    print(f"1. 安装用户脚本。点击下方链接将在 Tampermonkey/Violentmonkey 中打开安装页面:")
    print(f"   脚本链接: {frontend_script_url}")
    if ask_yes_no("是否现在在浏览器中打开此链接?", default='yes'): webbrowser.open(frontend_script_url)
    print("\n2. [重要] 安装后，修改脚本设置:")
    print(f"   - 打开 Tampermonkey/Violentmonkey 的 **管理面板**。")
    print(f"   - 找到脚本 'Live Stream Chat AI Agent'，点击 **编辑** 图标。")
    print(f"   - 在脚本顶部附近找到 `// API_ENDPOINT = ...` 这一行。")
    print_action(f"请将此行修改为:\n   const API_ENDPOINT = '{api_endpoint_url}';")
    print(f"   - 点击编辑器上方的 **保存** 图标。")
    print_success("前端脚本设置指导完成。")

    # --- 10. Final Check & Run Server ---
    print_step(10, "准备启动！")
    print_success("所有配置步骤已完成！")
    # Final reminders based on config
    if config['SERVER_ENABLE_SSL'] and (not config.get('SSL_CERT_PATH') or not config.get('SSL_KEY_PATH')):
        print_error("提醒：您启用了 HTTPS 但未有效设置证书路径，服务器将启动失败！")
    if stt_provider in ['youdao', 'both'] and not config.get('FFMPEG_PATH'):
        print_error("提醒：您选择了有道 STT 但未成功配置 FFmpeg 路径，STT 功能将失败！")

    if ask_yes_no("\n是否要尝试在后台启动后端服务器?", default='yes'):
        print_info(f"尝试在后台启动: `python server.py` (在 `{BACKEND_DIR}`)...")
        try:
            # Use DETACHED_PROCESS and CREATE_NEW_PROCESS_GROUP on Windows for better independence
            # On Linux/macOS, Popen already runs in background relative to script
            flags = 0
            if platform.system() == "Windows":
                 flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            # Pass the potentially modified environment (with tools/bin in PATH)
            process_env = os.environ.copy()
            process = subprocess.Popen( [sys.executable, BACKEND_DIR / "server.py"], # Pass Path object is fine
                                        cwd=BACKEND_DIR, creationflags=flags, env=process_env,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL # Redirect output to suppress in current console
                                        )
            print_success(f"服务器进程已在后台启动 (PID: {process.pid})。")
            print_info("服务器日志将不会显示在此窗口。")
            print_info("要停止服务器:")
            if platform.system() == "Windows": print_info("  - 使用任务管理器结束 python.exe 进程。")
            else: print_info(f"  - 在终端运行 `kill {process.pid}`。")
            print_info("\n现在可以访问您的直播页面了！")
        except Exception as e:
            print_error(f"启动服务器时发生错误: {e}")
            user_action_required(f"请手动进入 `{BACKEND_DIR}` 目录并运行 `python server.py` 查看错误。", BACKEND_DIR)
    else:
        print_info("好的。请稍后手动启动服务器:")
        print(f"  cd '{BACKEND_DIR}'") # Add quotes for paths with spaces
        print(f"  python server.py")

    # --- 11. License ---
    print_step(11, "许可证信息")
    # ... (Same logic) ...
    license_path = None;
    for name in LICENSE_FILE_NAMES:
        potential_path = PROJECT_ROOT / name
        if potential_path.is_file(): license_path = potential_path; break
    if license_path and ask_yes_no(f"是否查看项目许可证 (`{license_path.name}`)?", default='no'):
         try:
             with open(license_path, 'r', encoding='utf-8') as f: print("\n--- 许可证 ---\n" + f.read() + "\n--- End ---\n")
         except Exception as e: print_warning(f"读许可证失败: {e}")
    elif not license_path: print_info("未找到许可证文件。")

    print_separator('=')
    print("配置向导完成！祝您使用愉快！")
    print_separator('=')

if __name__ == "__main__":
    # Ensure script is run from project root or tools dir relative to project root
    script_path = Path(__file__).resolve()
    if not (script_path.parent.name == "tools" and (script_path.parent.parent / "backend").is_dir()):
         print("[错误] 此脚本应位于项目根目录下的 `tools` 文件夹中，并且从项目根目录运行。")
         print(f"       当前脚本位置: {script_path}")
         print(f"       预期项目根目录: {PROJECT_ROOT}")
         sys.exit(1)

    # Create necessary local dirs immediately
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        main()
    except KeyboardInterrupt: print("\n\n操作被用户中断。")
    except SystemExit as e: pass # Allow sys.exit() to terminate gracefully
    except Exception:
        print_error("\n\n配置过程中发生未预料的严重错误:")
        import traceback
        traceback.print_exc()
        print_error("请截图此错误信息寻求帮助，或尝试解决后重新运行脚本。")
        sys.exit(1)
    # No automatic cleanup of downloads, user might need the files if setup failed.