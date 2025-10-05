from fastapi import FastAPI, HTTPException, Request, File, UploadFile, Form, Depends, Header
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import uuid
import time
import json
import os
import warnings
import sqlite3
import re
import html
import logging
import sys
import hmac
import hashlib
from dotenv import load_dotenv
from typing import Dict, List, Optional, Any, Generator
from pydantic import BaseModel

# 加载 .env 文件中的环境变量
load_dotenv()

# 配置日志
def setup_logging():
    """设置日志配置"""
    # 创建日志目录
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 配置日志格式
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    
    # 配置根日志记录器
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler(f'{log_dir}/qwen_fastapi.py.log', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # 创建专用日志记录器
    logger = logging.getLogger('qwen_fastapi.py')
    logger.setLevel(logging.DEBUG)
    
    return logger

# 初始化日志
logger = setup_logging()

# ==================== 配置区域 ====================
# 获取Cookie信息
QWEN_COOKIES = os.environ.get("QWEN_COOKIES", "")

class CookieManager:
    """Cookie管理器 - 简化版本"""

    # 关键Cookie参数列表
    ESSENTIAL_PARAMS = [
        'cnaui', 'aui', 'sca', 'xlly_s', '_gcl_au', 'cna',  # 长期参数
        'token', '_bl_uid', 'x-ap',  # 中期参数
        'acw_tc', 'atpsida', 'tfstk', 'ssxmod_itna'  # 短期参数
    ]

    def __init__(self, cookie_string=""):
        self.cookies = self._parse_cookies(cookie_string)

    def _parse_cookies(self, cookie_string):
        """解析Cookie字符串为字典"""
        cookies = {}
        if cookie_string:
            for item in cookie_string.split(';'):
                if '=' in item:
                    key, value = item.strip().split('=', 1)
                    cookies[key] = value
        return cookies

    def get_cookie_status(self):
        """检查Cookie状态 - 简化版本"""
        critical_params = ['cnaui', 'aui', 'token']
        missing_critical = [p for p in critical_params if p not in self.cookies]

        return {
            'healthy': len(missing_critical) == 0,
            'missing_critical': missing_critical
        }

    def get_essential_cookies(self):
        """获取所有存在的关键Cookie参数"""
        return {k: v for k, v in self.cookies.items() if k in self.ESSENTIAL_PARAMS}

    def to_cookie_string(self, cookies_dict=None):
        """转换为Cookie字符串"""
        if cookies_dict is None:
            cookies_dict = self.get_essential_cookies()
        return '; '.join([f"{k}={v}" for k, v in cookies_dict.items()])

    def extract_token(self):
        """提取token"""
        return self.cookies.get('token', '')

# 初始化Cookie管理器
cookie_manager = CookieManager(QWEN_COOKIES)

# 自动从Cookie中提取token，或使用单独设置的QWEN_AUTH_TOKEN
QWEN_AUTH_TOKEN = os.environ.get("QWEN_AUTH_TOKEN")

if not QWEN_AUTH_TOKEN:
    extracted_token = cookie_manager.extract_token()
    if extracted_token:
        QWEN_AUTH_TOKEN = extracted_token
        logger.debug("✅ 从QWEN_COOKIES中自动提取到token")

        # 检查Cookie状态
        status = cookie_manager.get_cookie_status()
        if not status['healthy']:
            logger.debug(f"⚠️  缺少关键Cookie参数: {', '.join(status['missing_critical'])}")
    else:
        QWEN_AUTH_TOKEN = ""
        logger.debug("❌ 警告: 未找到token，请检查QWEN_COOKIES配置")

IS_DELETE = 0  # 是否在会话结束后自动删除会话
PORT = 8000  # FastAPI默认端口
DEBUG_STATUS = True  # 开启debug模式以便观察上传过程
DATABASE_PATH = "db/chat_history.db"  # 数据库文件路径

# ==================== API鉴权配置 ====================
# 从环境变量读取有效token列表
VALID_TOKENS_STR = os.environ.get("VALID_TOKENS", "")
VALID_TOKENS = []
if VALID_TOKENS_STR:
    try:
        # 支持JSON格式: ["token1", "token2"]
        VALID_TOKENS = json.loads(VALID_TOKENS_STR)
        logger.info(f"✅ 已加载 {len(VALID_TOKENS)} 个有效API Token")
    except json.JSONDecodeError:
        # 如果不是JSON格式，尝试按逗号分隔
        VALID_TOKENS = [token.strip() for token in VALID_TOKENS_STR.split(',') if token.strip()]
        logger.info(f"✅ 已加载 {len(VALID_TOKENS)} 个有效API Token (逗号分隔)")
else:
    logger.warning("⚠️  未配置VALID_TOKENS，API将不进行鉴权验证")

def verify_auth_token(authorization: str = Header(None)):
    """验证 Authorization Header 中的 Bearer Token

    Args:
        authorization: Authorization header，格式为 "Bearer <token>"

    Returns:
        验证通过的token字符串

    Raises:
        HTTPException: 鉴权失败时抛出401或403异常
    """
    # 如果未配置VALID_TOKENS，则跳过鉴权
    if not VALID_TOKENS:
        return None

    if not authorization:
        logger.warning("🔒 鉴权失败: 缺少Authorization Header")
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization Header. Please provide a valid Bearer token."
        )

    # 解析Bearer token
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        logger.warning(f"🔒 鉴权失败: 无效的Authorization Scheme: {scheme}")
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization Scheme. Expected 'Bearer <token>'"
        )

    # 验证token是否在有效列表中
    if token not in VALID_TOKENS:
        logger.warning(f"🔒 鉴权失败: 无效或过期的token: {token[:10]}...")
        raise HTTPException(
            status_code=403,
            detail="Invalid or Expired Token. Access denied."
        )

    logger.debug(f"✅ 鉴权成功: token {token[:10]}...")
    return token
# ==================== API鉴权配置结束 ====================

# 模型映射，基于实际返回的模型列表（model.txt）
MODEL_MAP = {
    # 基于 model.txt 中实际存在的模型ID进行映射
    "qwen": "qwen3-max",                        # 默认旗舰模型
    "qwen3": "qwen3-max",                       # Qwen3 默认模型
    "qwen3-coder": "qwen3-coder-plus",          # 代码专用模型
    "qwen3-vl": "qwen3-vl-plus",               # 视觉语言模型
    "qwen3-omni": "qwen3-omni-flash",          # 多模态模型
    "qwen-max": "qwen-max-latest",              # 稳定旗舰模型
    "qwen-plus": "qwen-plus-2025-09-11",        # Plus 模型（最新版本）
    "qwen-turbo": "qwen-turbo-2025-02-11",      # 快速模型
    "qwq": "qwq-32b",                           # 推理专用模型
    "qvq": "qvq-72b-preview-0310",             # 视觉推理模型
    
    # Qwen2.5 系列模型映射
    "qwen2.5": "qwen2.5-72b-instruct",         # Qwen2.5 默认模型
    "qwen2.5-coder": "qwen2.5-coder-32b-instruct", # Qwen2.5 代码模型
    "qwen2.5-vl": "qwen2.5-vl-32b-instruct",   # Qwen2.5 视觉模型
    "qwen2.5-omni": "qwen2.5-omni-7b",         # Qwen2.5 多模态模型
    "qwen2.5-14b": "qwen2.5-14b-instruct-1m",  # Qwen2.5 14B 长上下文
    "qwen2.5-72b": "qwen2.5-72b-instruct",     # Qwen2.5 72B 模型
    
    # Qwen3 系列特定规格模型
    "qwen3-235b": "qwen3-235b-a22b",           # Qwen3 235B 参数模型
    "qwen3-30b": "qwen3-30b-a3b",              # Qwen3 30B 参数模型
    "qwen3-coder-30b": "qwen3-coder-30b-a3b-instruct", # Qwen3 30B 代码模型
    
    # 历史版本兼容
    "qwen-plus-old": "qwen-plus-2025-01-25",   # 旧版本 Plus 模型
    
    # OpenAI 常见模型映射到 Qwen 对应能力模型（严格基于实际存在的模型）
    "gpt-3.5-turbo": "qwen-turbo-2025-02-11",  # 快速高效
    "gpt-4": "qwen-plus-2025-09-11",           # 复杂任务
    "gpt-4-turbo": "qwen3-max",                # 最强大
}
# =================================================

warnings.filterwarnings("ignore", message=".*development server.*")

def debug_log(message):
    """根据DEBUG_STATUS决定是否输出debug信息"""
    if DEBUG_STATUS:
        logger.debug(f"[DEBUG] {message}")

def remove_tool(text):
    # 使用正则表达式匹配 <tool_use>...</tool_use>，包括跨行内容
    pattern = r'<tool_use>.*?</tool_use>'
    # flags=re.DOTALL 使得 . 可以匹配换行符
    cleaned_text = re.sub(pattern, '', text, flags=re.DOTALL)
    return cleaned_text

def determine_filetype(filename: str, content_type: str = None) -> str:
    """
    根据文件名和Content-Type确定Qwen API的filetype参数
    返回: "image", "video", 或 "file"
    """
    file_ext = os.path.splitext(filename)[1].lower() if filename else ""

    # 图片类型
    if (content_type and content_type.startswith('image/')):
        return "image"

    # 视频类型
    video_extensions = ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv', '.m4v', '.3gp', '.m2ts', '.qt']
    if (content_type and content_type.startswith('video/')) or file_ext in video_extensions:
        return "video"

    # 其他所有文件类型统一为 "file"
    return "file"

def determine_content_type(filename: str, provided_content_type: str = None) -> str:
    """
    根据文件名扩展名确定详细的Content-Type
    如果提供了content_type则作为后备返回值
    """
    if not filename:
        return provided_content_type or "application/octet-stream"

    file_ext = os.path.splitext(filename)[1].lower()

    # 图片格式
    image_types = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.gif': 'image/gif',
        '.webp': 'image/webp', '.bmp': 'image/bmp',
        '.tiff': 'image/tiff'
    }
    if file_ext in image_types:
        return image_types[file_ext]

    # 视频格式
    video_types = {
        '.mp4': 'video/mp4', '.avi': 'video/x-msvideo',
        '.mov': 'video/quicktime', '.qt': 'video/quicktime',
        '.wmv': 'video/x-ms-wmv', '.flv': 'video/x-flv',
        '.webm': 'video/webm', '.mkv': 'video/x-matroska',
        '.m4v': 'video/x-m4v', '.3gp': 'video/3gpp',
        '.m2ts': 'video/mp2t'
    }
    if file_ext in video_types:
        return video_types[file_ext]

    # 文档格式
    document_types = {
        '.pdf': 'application/pdf',
        '.doc': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.xls': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.ppt': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    }
    if file_ext in document_types:
        return document_types[file_ext]

    # 文本格式
    text_types = {
        '.txt': 'text/plain', '.md': 'text/markdown',
        '.csv': 'text/csv', '.json': 'application/json',
        '.xml': 'application/xml', '.yaml': 'application/x-yaml',
        '.yml': 'application/x-yaml'
    }
    if file_ext in text_types:
        return text_types[file_ext]

    # 使用提供的content_type或默认值
    return provided_content_type or "application/octet-stream"

class ChatHistoryManager:
    """管理聊天历史记录的本地存储"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    chat_id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at INTEGER,
                    updated_at INTEGER,
                    chat_type TEXT,
                    current_response_id TEXT,
                    last_assistant_content TEXT
                )
            ''')
            conn.commit()
            debug_log("数据库初始化完成")
        finally:
            conn.close()
    
    def update_session(self, chat_id: str, title: str, created_at: int, updated_at: int, 
                      chat_type: str, current_response_id: str, last_assistant_content: str):
        """更新或插入会话记录"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO chat_sessions 
                (chat_id, title, created_at, updated_at, chat_type, current_response_id, 
                 last_assistant_content)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (chat_id, title, created_at, updated_at, chat_type, current_response_id,
                  remove_tool(last_assistant_content)))
            conn.commit()
            debug_log(f"更新会话记录: {chat_id}")
        finally:
            conn.close()
    
    def get_session_by_last_content(self, content: str):
        """根据最新AI回复内容查找会话"""
        normalized_content = self.normalize_text(content)
        debug_log(f"查找会话，标准化内容: {normalized_content[:100]}...")
        
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT chat_id, current_response_id, last_assistant_content
                FROM chat_sessions 
                WHERE last_assistant_content IS NOT NULL
            ''')
            results = cursor.fetchall()
            
            debug_log(f"数据库中共有 {len(results)} 条会话记录")
            
            for row in results:
                chat_id, current_response_id, stored_content = row
                normalized_stored = self.normalize_text(stored_content)
                debug_log(f"比较会话 {chat_id}...")
                
                if normalized_content == normalized_stored:
                    debug_log(f"匹配成功！会话ID: {chat_id}")
                    return {
                        'chat_id': chat_id,
                        'current_response_id': current_response_id
                    }
            
            debug_log("未找到匹配的会话")
            return None
        finally:
            conn.close()
    
    def delete_session(self, chat_id: str):
        """删除会话记录"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM chat_sessions WHERE chat_id = ?', (chat_id,))
            conn.commit()
            debug_log(f"删除会话记录: {chat_id}")
        finally:
            conn.close()
    
    def clear_all_sessions(self):
        """清空所有会话记录"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM chat_sessions')
            conn.commit()
            debug_log("清空所有会话记录")
        finally:
            conn.close()
    
    def normalize_text(self, text: str) -> str:
        """标准化文本，处理转义字符、空白符等"""
        if not text:
            return ""
        
        # HTML解码
        text = html.unescape(text)
        # 去除多余空白字符
        text = re.sub(r'\s+', ' ', text.strip())
        # 去除常见的markdown符号
        text = re.sub(r'[*_`~]', '', text)
        # 去除emoji（简单处理）
        text = re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF✨🌟]', '', text)
        
        return text

class QwenClient:
    """
    用于与 chat.qwen.ai API 交互的客户端。
    封装了创建对话、发送消息、接收流式响应及删除对话的逻辑。
    """
    def __init__(self, auth_token: str, cookies: str = "", base_url: str = "https://chat.qwen.ai"):
        self.auth_token = auth_token
        self.cookies = cookies
        self.base_url = base_url
        self.session = requests.Session()
        self.history_manager = ChatHistoryManager(DATABASE_PATH)
        
        # 初始化智能Cookie管理器
        self.cookie_manager = CookieManager(cookies)
        
        # 使用优化后的Cookie设置
        essential_cookies = self.cookie_manager.get_essential_cookies()
        if essential_cookies:
            self.session.cookies.update(essential_cookies)
            logger.debug(f"✅ 已加载 {len(essential_cookies)} 个关键Cookie参数")
        
        # 定期检查Cookie状态
        self._last_cookie_check = time.time()
        
        # 初始化时设置基本请求头，模拟真实浏览器环境
        self.session.headers.update({
            "accept": "application/json",
            "accept-language": "zh-CN,zh;q=0.9",
            "content-type": "application/json; charset=UTF-8",
            "source": "web",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "bx-v": "2.5.31",
            "bx-umidtoken": "T2gAcn1glXMhITXikmXs0OiYrFufhNZzPNYm5sbNWFmnuLgP8Ow4muZZWWKLkXctGU8=",
            "bx-ua": "231!pap3gkmUoC3+j3rAf43qmN4jUq/YvqY2leOxacSC80vTPuB9lMZY9mRWFzrwLEVl7FnY1roS2IxpF9PC+tT6OPC/V1abyEyFxAEaUkxrQ0vccA/tzKw3glZGZSmZh59aXfU4Y5MMXwxnTVZ+/jC4BeXFncDsBa28ZBehEUtIQXxk0ipMY2r/FgC6Na/HA+Uj9Qp+qujynhFxWF7CugwWdsBgD+B34gRr+MNep4Dqk+8t67MMbpXQHJlCok+++4mWYi++6Pamo76GFxBDj+ITHFtd3m4G4R7CN5sgbbtPQepaUgeliRgmWUMcw/rzjJisKKIE3oFnHj5npIyP4H0w2xFthQbQuC/1LAQ2Iq+lrvL6xCS3CI5Giy2exk4LwMJdsmiTpm03B1Cjib62vLA2gk0bsHCo9KykoTD41HO/oqAKDPx5erm9boNvAlKSz6OxdcQ19KSRz/rfuwb8IKhL0zcjcFhl3",
            "timezone": "Mon Sep 29 2025 09:52:39 GMT+0800",
        })
        self.user_info = None
        self.models_info = None
        self.user_settings = None
        self._initialize()
        # 启动时同步历史记录
        self.sync_history_from_cloud()

    def _initialize(self):
        """初始化客户端，获取用户信息、模型列表和用户设置"""
        self._update_auth_header()
        
        # 检查token是否为空或明显无效
        if not self.auth_token or self.auth_token.strip() == "":
            logger.debug("警告: QWEN_AUTH_TOKEN 为空，请在 .env 文件中设置有效的token")
            # 设置默认值以避免后续错误
            self.user_info = {}
            self.models_info = {}
            self.user_settings = {}
            return
            
        try:
            # 获取用户信息
            user_info_res = self.session.get(f"{self.base_url}/api/v1/auths/")
            
            user_info_res.raise_for_status()
            
            # 检查响应是否为HTML（说明被重定向到登录页面）
            if user_info_res.text.strip().startswith('<!doctype') or user_info_res.text.strip().startswith('<html'):
                raise ValueError("API返回HTML页面，token可能无效或已过期")
            
            # 检查响应是否为空或无效
            if not user_info_res.text.strip():
                raise ValueError("API返回空响应，可能token无效")
                
            self.user_info = user_info_res.json()

            # 获取模型列表
            models_res = self.session.get(f"{self.base_url}/api/models")
            models_res.raise_for_status()
            self.models_info = {model['id']: model for model in models_res.json()['data']}

            # 获取用户设置
            settings_res = self.session.get(f"{self.base_url}/api/v2/users/user/settings")
            settings_res.raise_for_status()
            self.user_settings = settings_res.json()['data']
            
            logger.debug("客户端初始化成功")

        except (requests.exceptions.RequestException, ValueError, KeyError) as e:
            logger.debug(f"客户端初始化失败: {e}")
            logger.debug("请检查 QWEN_AUTH_TOKEN 是否正确设置在 .env 文件中")
            # 设置默认值以避免后续错误
            self.user_info = {}
            self.models_info = {}
            self.user_settings = {}
            # 不抛出异常，允许程序继续运行

    def _update_auth_header(self):
        """更新会话中的认证头"""
        self.session.headers.update({"authorization": f"Bearer {self.auth_token}"})
        
    def _check_cookie_health(self, force_check=False):
        """检查Cookie健康状态 - 简化版本"""
        current_time = time.time()
        # 每10分钟检查一次，或强制检查
        if not force_check and (current_time - self._last_cookie_check) < 600:
            return

        self._last_cookie_check = current_time
        status = self.cookie_manager.get_cookie_status()

        if not status['healthy']:
            logger.debug(f"⚠️  缺少关键Cookie参数: {', '.join(status['missing_critical'])}")

        return status


    def generate_smart_prompt(self, original_prompt: str, files: list) -> str:
        """根据文件类型生成智能提示语"""
        if not files:
            return original_prompt

        # 分析文件类型
        file_types = []
        file_classes = []

        for file_info in files:
            file_class = file_info.get('file_class', 'document')
            file_types.append(file_info.get('file_type', 'application/octet-stream'))
            file_classes.append(file_class)

        # 统计文件类型
        has_images = any(fc == 'vision' for fc in file_classes)
        has_videos = any(fc == 'video' for fc in file_classes)
        has_documents = any(fc == 'document' for fc in file_classes)
        has_pdf = any('pdf' in ft for ft in file_types)
        has_office = any(any(office in ft for office in ['word', 'excel', 'powerpoint', 'spreadsheet', 'presentation']) for ft in file_types)
        has_text = any(ft.startswith('text/') for ft in file_types)
        has_json = any('json' in ft for ft in file_types)
        has_xml = any('xml' in ft for ft in file_types)

        # 生成增强提示语
        enhanced_prompts = []

        if has_images:
            enhanced_prompts.append("识别图片中的内容和信息")

        if has_videos:
            enhanced_prompts.append("分析视频内容、场景信息和关键画面")

        if has_pdf:
            enhanced_prompts.append("解析PDF文档中的文本内容和结构信息")

        if has_office:
            enhanced_prompts.append("分析Office文档(Word/Excel/PowerPoint)的内容和数据")

        if has_text:
            enhanced_prompts.append("处理文本文件的内容")

        if has_json:
            enhanced_prompts.append("解析JSON数据结构和内容")

        if has_xml:
            enhanced_prompts.append("解析XML文档结构和数据")

        # 如果原始提示为空或太简单，使用智能生成的提示
        if not original_prompt or len(original_prompt.strip()) < 10:
            if enhanced_prompts:
                return f"请帮我{', '.join(enhanced_prompts)}，并提供详细分析。"
            else:
                return "请分析这些文件的内容并提供详细信息。"

        # 如果原始提示已经足够详细，保持原样
        return original_prompt

    def sync_history_from_cloud(self):
        """从云端同步历史记录到本地数据库"""
        debug_log("开始从云端同步历史记录")
        self._update_auth_header()
        
        try:
            # 清空本地记录
            self.history_manager.clear_all_sessions()
            
            page = 1
            while True:
                # 获取历史会话列表
                list_url = f"{self.base_url}/api/v2/chats/?page={page}"
                response = self.session.get(list_url)
                response.raise_for_status()
                data = response.json()
                
                if not data.get('success') or not data.get('data'):
                    break
                
                sessions = data['data']
                debug_log(f"第 {page} 页获取到 {len(sessions)} 个会话")
                
                if not sessions:
                    break
                
                # 获取每个会话的详细信息
                for session in sessions:
                    chat_id = session['id']
                    try:
                        detail_url = f"{self.base_url}/api/v2/chats/{chat_id}"
                        detail_response = self.session.get(detail_url)
                        detail_response.raise_for_status()
                        detail_data = detail_response.json()
                        
                        if not detail_data.get('success'):
                            continue
                        
                        chat_detail = detail_data['data']
                        messages = chat_detail.get('chat', {}).get('messages', [])
                        
                        # 提取最新的AI回复内容
                        last_assistant_content = ""
                        for msg in reversed(messages):
                            if msg.get('role') == 'assistant':
                                # 从content_list中提取内容
                                content_list = msg.get('content_list', [])
                                if content_list:
                                    last_assistant_content = content_list[-1].get('content', '')
                                else:
                                    last_assistant_content = msg.get('content', '')
                                break
                        
                        # 保存到本地数据库
                        current_response_id = chat_detail.get('currentId', '')
                        
                        self.history_manager.update_session(
                            chat_id=chat_id,
                            title=session.get('title', ''),
                            created_at=session.get('created_at', 0),
                            updated_at=session.get('updated_at', 0),
                            chat_type=session.get('chat_type', ''),
                            current_response_id=current_response_id,
                            last_assistant_content=last_assistant_content
                        )
                        
                    except Exception as e:
                        debug_log(f"获取会话 {chat_id} 详细信息失败: {e}")
                        continue
                
                page += 1
                
            debug_log("历史记录同步完成")
            
        except Exception as e:
            debug_log(f"同步历史记录失败: {e}")

    def _get_qwen_model_id(self, openai_model: str) -> str:
        """将 OpenAI 模型名称映射到 Qwen 模型 ID"""
        # 如果直接匹配到 key，则使用映射值；否则尝试看模型 ID 是否直接存在于 Qwen 模型列表中；最后回退到默认模型
        mapped_id = MODEL_MAP.get(openai_model)
        if mapped_id and mapped_id in self.models_info:
            return mapped_id
        elif openai_model in self.models_info:
            return openai_model # OpenAI 模型名恰好与 Qwen ID 相同
        else:
            logger.debug(f"模型 '{openai_model}' 未找到或未映射，使用默认模型 'qwen3-235b-a22b'")
            return "qwen3-235b-a22b" # 最可靠的回退选项

    def create_chat(self, model_id: str, title: str = "新对话") -> str:
        """创建一个新的对话"""
        self._update_auth_header() # 确保 token 是最新的
        url = f"{self.base_url}/api/v2/chats/new"
        payload = {
            "title": title,
            "models": [model_id],
            "chat_mode": "normal",
            "chat_type": "t2t", # Text to Text
            "timestamp": int(time.time() * 1000)
        }
        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            chat_id = response.json()['data']['id']
            debug_log(f"成功创建对话: {chat_id}")
            return chat_id
        except requests.exceptions.RequestException as e:
            debug_log(f"创建对话失败: {e}")
            raise

    def delete_chat(self, chat_id: str):
        """删除一个对话"""
        self._update_auth_header() # 确保 token 是最新的
        url = f"{self.base_url}/api/v2/chats/{chat_id}"
        
        try:
            response = self.session.delete(url)
            response.raise_for_status()
            res_data = response.json()
            if res_data.get('success', False):
                debug_log(f"成功删除对话: {chat_id}")
                # 同时删除本地记录
                self.history_manager.delete_session(chat_id)
                return True
            else:
                debug_log(f"删除对话 {chat_id} 返回 success=False: {res_data}")
                return False
        except requests.exceptions.RequestException as e:
            debug_log(f"删除对话失败 {chat_id}: {e}")
            return False
        except json.JSONDecodeError:
            debug_log(f"删除对话时无法解析 JSON 响应 {chat_id}")
            return False

    def find_matching_session(self, messages: list):
        """根据消息历史查找匹配的会话"""
        debug_log("开始查找匹配的会话")
        
        # 检查是否有AI回复历史
        last_assistant_message = None
        for msg in reversed(messages):
            if msg.get('role') == 'assistant':
                last_assistant_message = msg
                break
        
        if not last_assistant_message:
            debug_log("请求中没有AI回复历史，将创建新会话")
            return None
        
        last_content = last_assistant_message.get('content', '')
        if not last_content:
            debug_log("最新AI回复内容为空，将创建新会话")
            return None
        
        debug_log("查找匹配...")
        
        # 查找匹配的会话
        matched_session = self.history_manager.get_session_by_last_content(last_content)
        
        if matched_session:
            debug_log(f"找到匹配的会话: {matched_session['chat_id']}")
            return matched_session
        else:
            debug_log("未找到匹配的会话，将创建新会话")
            return None

    def update_session_after_chat(self, chat_id: str, title: str, messages: list, 
                                  current_response_id: str, assistant_content: str):
        """聊天结束后更新会话记录"""
        debug_log(f"更新会话记录: {chat_id}")
        
        current_time = int(time.time())
        
        self.history_manager.update_session(
            chat_id=chat_id,
            title=title,
            created_at=current_time,
            updated_at=current_time,
            chat_type="t2t",
            current_response_id=current_response_id,
            last_assistant_content=assistant_content
        )

    async def chat_completions(self, openai_request: dict):
        """
        执行聊天补全，模拟 OpenAI API。
        返回流式生成器或非流式 JSON 响应。
        """
        # 检查Cookie健康状态
        self._check_cookie_health()
        
        # 检查token是否有效
        if not self.user_info or not self.models_info:
            error_msg = "QWEN_AUTH_TOKEN 无效或未设置，无法处理聊天请求。请在 .env 文件中设置有效的token。"
            logger.debug(f"错误: {error_msg}")
            
            # 提供Cookie诊断信息
            cookie_status = self.cookie_manager.get_cookie_status()
            if cookie_status['missing_critical']:
                error_msg += f" 缺少关键Cookie参数: {', '.join(cookie_status['missing_critical'])}"
            
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "message": error_msg,
                        "type": "authentication_error",
                        "param": None,
                        "code": "invalid_api_key"
                    }
                }
            )
        
        self._update_auth_header() # 确保 token 是最新的
        
        # 解析 OpenAI 请求
        model = openai_request.get("model", "qwen3")
        messages = openai_request.get("messages", [])
        stream = openai_request.get("stream", False)
        # 解析新增参数
        enable_thinking = openai_request.get("enable_thinking", True) # 默认启用思考
        thinking_budget = openai_request.get("thinking_budget", None) # 默认不指定

        # 映射模型
        qwen_model_id = self._get_qwen_model_id(model)

        debug_log(f"收到聊天请求，消息数量: {len(messages)}, 模型: {qwen_model_id}")

        # 查找匹配的现有会话
        matched_session = self.find_matching_session(messages)
        
        chat_id = None
        parent_id = None
        user_input = ""
        
        if matched_session:
            # 使用现有会话进行增量聊天
            chat_id = matched_session['chat_id']
            parent_id = matched_session['current_response_id']
            
            # 只取最新的用户消息
            for msg in reversed(messages):
                if msg.get('role') == 'user':
                    user_input = msg.get('content', '')
                    break
            
            debug_log(f"使用现有会话 {chat_id}，parent_id: {parent_id}")
            
        else:
            # 创建新会话，拼接所有消息
            formatted_history = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])
            if messages and messages[0]['role'] != "system":
                formatted_history = "system:\n\n" + formatted_history
            user_input = formatted_history
            
            chat_id = self.create_chat(qwen_model_id, title=f"OpenAI_API_对话_{int(time.time())}")
            parent_id = None
            
            debug_log(f"创建新会话 {chat_id}")

        try:
            # 准备请求负载
            timestamp_ms = int(time.time() * 1000)
            
            # 构建 feature_config
            feature_config = {
                "output_schema": "phase"
            }
            if enable_thinking:
                feature_config["thinking_enabled"] = True
                # 如果提供了 thinking_budget 则使用，否则尝试从用户设置获取
                if thinking_budget is not None:
                    feature_config["thinking_budget"] = thinking_budget
                else:
                    # 尝试从用户设置中获取默认的 thinking_budget
                    default_budget = self.user_settings.get('model_config', {}).get(qwen_model_id, {}).get('thinking_budget')
                    if default_budget:
                        feature_config["thinking_budget"] = default_budget
            else:
                feature_config["thinking_enabled"] = False

            payload = {
                "stream": True, # 始终使用流式以获取实时数据
                "incremental_output": True,
                "chat_id": chat_id,
                "chat_mode": "normal",
                "model": qwen_model_id,
                "parent_id": parent_id,
                "messages": [{
                    "fid": str(uuid.uuid4()),
                    "parentId": parent_id,
                    "childrenIds": [str(uuid.uuid4())],
                    "role": "user",
                    "content": user_input,
                    "user_action": "chat",
                    "files": [],
                    "timestamp": timestamp_ms,
                    "models": [qwen_model_id],
                    "chat_type": "t2t",
                    "feature_config": feature_config,
                    "extra": {"meta": {"subChatType": "t2t"}},
                    "sub_chat_type": "t2t",
                    "parent_id": parent_id
                }],
                "timestamp": timestamp_ms
            }

            # 添加必要的头
            headers = {
                "x-accel-buffering": "no" # 对于流式响应很重要
            }

            url = f"{self.base_url}/api/v2/chat/completions?chat_id={chat_id}"
            
            if stream:
                # 流式请求
                async def generate():
                    try:
                        # 使用流式请求，并确保会话能正确处理连接
                        with self.session.post(url, json=payload, headers=headers, stream=True) as r:
                            r.raise_for_status()
                            finish_reason = "stop"
                            reasoning_text = ""  # 用于累积 thinking 阶段的内容
                            assistant_content = ""  # 用于累积assistant回复内容
                            has_sent_content = False # 标记是否已经开始发送 answer 内容
                            current_response_id = None  # 当前回复ID

                            for line in r.iter_lines(decode_unicode=True):
                                # 检查标准的 SSE 前缀
                                if line.startswith("data: "):
                                    data_str = line[6:]  # 移除 'data: '
                                    if data_str.strip() == "[DONE]":
                                        # 发送最终的 done 消息块，包含 finish_reason
                                        final_chunk = {
                                            "id": f"chatcmpl-{chat_id[:10]}",
                                            "object": "chat.completion.chunk",
                                            "created": int(time.time()),
                                            "model": model,
                                            "choices": [{
                                                "index": 0,
                                                "delta": {}, 
                                                "finish_reason": finish_reason
                                            }]
                                        }
                                        yield f"data: {json.dumps(final_chunk)}\n\n"
                                        yield "data: [DONE]\n\n"
                                        break
                                    try:
                                        data = json.loads(data_str)
                                        
                                        # 提取response_id
                                        if "response.created" in data:
                                            current_response_id = data["response.created"].get("response_id")
                                            debug_log(f"获取到response_id: {current_response_id}")
                                        
                                        # 处理 choices 数据
                                        if "choices" in data and len(data["choices"]) > 0:
                                            choice = data["choices"][0]
                                            delta = choice.get("delta", {})
                                            
                                            # --- 重构逻辑：清晰区分 think 和 answer 阶段 ---
                                            phase = delta.get("phase")
                                            status = delta.get("status")
                                            content = delta.get("content", "")

                                            # 1. 处理 "think" 阶段
                                            if phase == "think":
                                                if status != "finished":
                                                    reasoning_text += content
                                                # 注意：think 阶段的内容不直接发送，只累积

                                            # 2. 处理 "answer" 阶段 或 无明确 phase 的内容 (兼容性)
                                            elif phase == "answer" or (phase is None and content):
                                                # 一旦进入 answer 阶段或有内容，标记为已开始
                                                has_sent_content = True 
                                                assistant_content += content  # 累积assistant回复
                                                
                                                # 构造包含 content 的流式块
                                                openai_chunk = {
                                                    "id": f"chatcmpl-{chat_id[:10]}",
                                                    "object": "chat.completion.chunk",
                                                    "created": int(time.time()),
                                                    "model": model,
                                                    "choices": [{
                                                        "index": 0,
                                                        "delta": {"content": content},
                                                        "finish_reason": None # answer 阶段进行中不设 finish_reason
                                                    }]
                                                }
                                                # 如果累积了 reasoning_text，则在第一个 answer 块中附带
                                                if reasoning_text:
                                                     openai_chunk["choices"][0]["delta"]["reasoning_content"] = reasoning_text
                                                     reasoning_text = "" # 发送后清空

                                                yield f"data: {json.dumps(openai_chunk)}\n\n"

                                            # 3. 处理结束信号 (通常在 answer 阶段的最后一个块)
                                            if status == "finished":
                                                finish_reason = delta.get("finish_reason", "stop")

                                    except json.JSONDecodeError:
                                        continue
                    except requests.exceptions.RequestException as e:
                        debug_log(f"流式请求失败: {e}")
                        # 发送一个错误块
                        error_chunk = {
                            "id": f"chatcmpl-error",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model,
                            "choices": [{
                                "index": 0,
                                "delta": {"content": f"Error during streaming: {str(e)}"},
                                "finish_reason": "error"
                            }]
                        }
                        yield f"data: {json.dumps(error_chunk)}\n\n"
                    finally:
                        # 聊天结束后更新会话记录
                        if assistant_content and current_response_id:
                            # 构建完整的消息历史
                            updated_messages = messages.copy()
                            updated_messages.append({
                                "role": "assistant",
                                "content": assistant_content
                            })
                            
                            self.update_session_after_chat(
                                chat_id=chat_id,
                                title=f"OpenAI_API_对话_{int(time.time())}",
                                messages=updated_messages,
                                current_response_id=current_response_id,
                                assistant_content=assistant_content
                            )

                return generate()

            else:
                # 非流式请求: 聚合流式响应
                response_text = ""  # 用于聚合最终回复
                reasoning_text = "" # 用于聚合 thinking 阶段的内容
                finish_reason = "stop"
                usage_data = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                current_response_id = None
                
                try:
                    with self.session.post(url, json=payload, headers=headers, stream=True) as r:
                        r.raise_for_status()
                        for line in r.iter_lines(decode_unicode=True):
                            # 检查完整的 SSE 前缀
                            if line.startswith("data: "): 
                                data_str = line[6:] # 移除 'data: '
                                if data_str.strip() == "[DONE]":
                                    break
                                try:
                                    data = json.loads(data_str)
                                    
                                    # 提取response_id
                                    if "response.created" in data:
                                        current_response_id = data["response.created"].get("response_id")
                                    
                                    # 处理 choices 数据来构建最终回复
                                    if "choices" in data and len(data["choices"]) > 0:
                                        delta = data["choices"][0].get("delta", {})
                                        
                                        # 累积 "think" 阶段的内容
                                        if delta.get("phase") == "think":
                                            if delta.get("status") != "finished":
                                                reasoning_text += delta.get("content", "")
                                        
                                        # 只聚合 "answer" 阶段的内容
                                        if delta.get("phase") == "answer":
                                            if delta.get("status") != "finished":
                                                response_text += delta.get("content", "")
                                        
                                        # 收集最后一次的 usage 信息
                                        if "usage" in data:
                                            qwen_usage = data["usage"]
                                            usage_data = {
                                                "prompt_tokens": qwen_usage.get("input_tokens", 0),
                                                "completion_tokens": qwen_usage.get("output_tokens", 0),
                                                "total_tokens": qwen_usage.get("total_tokens", 0),
                                            }
                                    
                                    # 检查是否是结束信号
                                    if "choices" in data and len(data["choices"]) > 0:
                                        delta = data["choices"][0].get("delta", {})
                                        if delta.get("status") == "finished":
                                            finish_reason = delta.get("finish_reason", "stop")
                                        
                                except json.JSONDecodeError:
                                    # 忽略无法解析的行
                                    continue
                    
                    # 聊天结束后更新会话记录
                    if response_text and current_response_id:
                        # 构建完整的消息历史
                        updated_messages = messages.copy()
                        updated_messages.append({
                            "role": "assistant",
                            "content": response_text
                        })
                        
                        self.update_session_after_chat(
                            chat_id=chat_id,
                            title=f"OpenAI_API_对话_{int(time.time())}",
                            messages=updated_messages,
                            current_response_id=current_response_id,
                            assistant_content=response_text
                        )
                    
                    # 构造非流式的 OpenAI 响应
                    openai_response = {
                        "id": f"chatcmpl-{chat_id[:10]}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": response_text
                            },
                            "finish_reason": finish_reason
                        }],
                        "usage": usage_data
                    }
                    
                    # 在非流式响应中添加 reasoning_content
                    if reasoning_text:
                        openai_response["choices"][0]["message"]["reasoning_content"] = reasoning_text
                    
                    return openai_response
                finally:
                    pass  # 不再自动删除会话

        except requests.exceptions.RequestException as e:
            debug_log(f"聊天补全失败: {e}")
            # 返回 OpenAI 格式的错误
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "message": f"内部服务器错误: {str(e)}",
                        "type": "server_error",
                        "param": None,
                        "code": None
                    }
                }
            )

    async def get_sts_token(self, filename: str, filesize: int, filetype: str = "image"):
        """获取OSS临时授权Token"""
        self._update_auth_header()
        
        url = f"{self.base_url}/api/v2/files/getstsToken"
        payload = {
            "filename": filename,
            "filesize": filesize,
            "filetype": filetype
        }
        
        try:
            debug_log(f"请求STS Token: {payload}")
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            
            # 检查响应内容类型
            if 'application/json' not in response.headers.get('content-type', ''):
                debug_log(f"STS响应非JSON格式: {response.headers.get('content-type')}")
                debug_log(f"响应内容: {response.text[:500]}")
                raise ValueError("API返回非JSON响应")
            
            result = response.json()
            debug_log(f"STS Token响应: {result}")
            
            # 检查响应是否成功
            if not result.get("success", False):
                error_msg = result.get("message", "未知错误")
                debug_log(f"STS Token获取失败: {error_msg}")
                raise ValueError(f"API返回错误: {error_msg}")
            
            debug_log(f"获取STS Token成功: {filename}")
            return result
        except requests.exceptions.RequestException as e:
            debug_log(f"获取STS Token网络错误: {e}")
            if hasattr(e, 'response') and e.response:
                debug_log(f"错误响应状态码: {e.response.status_code}")
                debug_log(f"错误响应内容: {e.response.text[:500]}")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "message": f"获取上传授权失败: {str(e)}",
                        "type": "server_error",
                        "param": None,
                        "code": None
                    }
                }
            )
        except (ValueError, json.JSONDecodeError) as e:
            debug_log(f"获取STS Token解析错误: {e}")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "message": f"获取上传授权失败: {str(e)}",
                        "type": "server_error",
                        "param": None,
                        "code": None
                    }
                }
            )

    async def multimodal_chat_completions(self, multimodal_request: dict):
        """
        执行多模态聊天补全，完全按照 chaturl2.txt 的格式实现
        """
        # 检查Cookie健康状态
        self._check_cookie_health()

        # 检查token是否有效
        if not self.user_info or not self.models_info:
            error_msg = "QWEN_AUTH_TOKEN 无效或未设置，无法处理多模态聊天请求。"
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "message": error_msg,
                        "type": "authentication_error",
                        "param": None,
                        "code": "invalid_api_key"
                    }
                }
            )

        self._update_auth_header()

        # 解析请求参数
        model = multimodal_request.get("model", "qwen3-vl-plus")
        messages = multimodal_request.get("messages", [])
        stream = multimodal_request.get("stream", False)
        enable_thinking = multimodal_request.get("enable_thinking", False)  # 多模态默认关闭思考
        thinking_budget = multimodal_request.get("thinking_budget", None)

        # 映射模型
        qwen_model_id = self._get_qwen_model_id(model)
        debug_log(f"收到多模态聊天请求，消息数量: {len(messages)}, 模型: {qwen_model_id}")

        # 查找匹配的现有会话
        matched_session = self.find_matching_session(messages)

        chat_id = None
        parent_id = None
        user_content = ""
        files = []

        if matched_session:
            # 使用现有会话
            chat_id = matched_session['chat_id']
            parent_id = matched_session['current_response_id']
            debug_log(f"使用现有会话 {chat_id}，parent_id: {parent_id}")
        else:
            # 创建新会话
            chat_id = self.create_chat(qwen_model_id, title=f"多模态对话_{int(time.time())}")
            parent_id = None
            debug_log(f"创建新的多模态会话 {chat_id}")

        # 处理最新的用户消息（支持多模态）
        for msg in reversed(messages):
            if msg.get('role') == 'user':
                # 处理多模态消息内容
                if isinstance(msg.get('content'), str):
                    # 纯文本消息
                    user_content = msg.get('content', '')
                elif isinstance(msg.get('content'), list):
                    # 多模态消息
                    text_parts = []
                    for content_part in msg.get('content', []):
                        if content_part.get("type") == "text":
                            text_parts.append(content_part.get("text", ""))
                        elif content_part.get("type") in ["image_url", "video_url"]:
                            # ✅ 优先使用传入的完整文件信息（如果有）
                            if "file_info" in content_part:
                                file_info = content_part["file_info"]
                                files.append(file_info)
                                debug_log(f"使用完整文件信息: {file_info.get('name', 'unknown')} (大小: {file_info.get('size', 0)} bytes)")
                            else:
                                # 降级：从URL解析文件信息（向后兼容）
                                if content_part.get("type") == "image_url":
                                    file_url = content_part.get("image_url", {}).get("url", "")
                                else:  # video_url
                                    file_url = content_part.get("video_url", {}).get("url", "")

                                if file_url:
                                    file_info = self.parse_file_info_from_url(file_url)
                                    if file_info:
                                        files.append(file_info)
                                        debug_log(f"从URL解析文件: {file_info.get('name', 'unknown')} (类型: {file_info.get('file_class', 'unknown')})")
                                    else:
                                        debug_log(f"无法解析文件URL: {file_url}")

                    user_content = " ".join(text_parts) if text_parts else ""

                    # 智能提示语生成：根据文件类型调整用户内容
                    if user_content and files:
                        user_content = self.generate_smart_prompt(user_content, files)

                break

        try:
            # 构建符合 Qwen API 格式的请求负载
            timestamp_ms = int(time.time() * 1000)

            # 构建 feature_config
            feature_config = {
                "output_schema": "phase"
            }
            if enable_thinking:
                feature_config["thinking_enabled"] = True
                if thinking_budget is not None:
                    feature_config["thinking_budget"] = thinking_budget
            else:
                feature_config["thinking_enabled"] = False

            # 生成必要的ID
            fid = str(uuid.uuid4())
            child_id = str(uuid.uuid4())

            # 构建完整的消息对象（完全按照 chaturl2.txt 格式）
            message_obj = {
                "fid": fid,
                "parentId": parent_id,
                "childrenIds": [child_id],
                "role": "user",
                "content": user_content,
                "user_action": "chat",
                "files": files,  # 关键：使用真正的文件数组而不是空数组
                "timestamp": timestamp_ms,
                "models": [qwen_model_id],
                "chat_type": "t2t",
                "feature_config": feature_config,
                "extra": {"meta": {"subChatType": "t2t"}},
                "sub_chat_type": "t2t",
                "parent_id": parent_id
            }

            # 构建完整的请求负载（完全按照 chaturl2.txt 格式）
            payload = {
                "stream": True,  # 始终使用流式以获取实时数据
                "incremental_output": True,  # 关键字段
                "chat_id": chat_id,
                "chat_mode": "normal",
                "model": qwen_model_id,
                "parent_id": parent_id,
                "messages": [message_obj],
                "timestamp": timestamp_ms
            }

            # 添加必要的头
            headers = {
                "x-accel-buffering": "no"  # 对于流式响应很重要
            }

            url = f"{self.base_url}/api/v2/chat/completions?chat_id={chat_id}"
            debug_log(f"发送多模态请求到: {url}")
            debug_log(f"请求负载包含 {len(files)} 个文件")

            if stream:
                # 流式请求
                async def generate():
                    try:
                        with self.session.post(url, json=payload, headers=headers, stream=True) as r:
                            r.raise_for_status()
                            finish_reason = "stop"
                            reasoning_text = ""
                            assistant_content = ""
                            has_sent_content = False
                            current_response_id = None

                            for line in r.iter_lines(decode_unicode=True):
                                if line.startswith("data: "):
                                    data_str = line[6:]
                                    if data_str.strip() == "[DONE]":
                                        # 发送最终的 done 消息块
                                        final_chunk = {
                                            "id": f"chatcmpl-{chat_id[:10]}",
                                            "object": "chat.completion.chunk",
                                            "created": int(time.time()),
                                            "model": model,
                                            "choices": [{
                                                "index": 0,
                                                "delta": {},
                                                "finish_reason": finish_reason
                                            }]
                                        }
                                        yield f"data: {json.dumps(final_chunk)}\n\n"
                                        yield "data: [DONE]\n\n"
                                        break

                                    try:
                                        data = json.loads(data_str)

                                        # 提取response_id
                                        if "response.created" in data:
                                            current_response_id = data["response.created"].get("response_id")
                                            debug_log(f"获取到response_id: {current_response_id}")

                                        # 处理 choices 数据
                                        if "choices" in data and len(data["choices"]) > 0:
                                            choice = data["choices"][0]
                                            delta = choice.get("delta", {})

                                            phase = delta.get("phase")
                                            status = delta.get("status")
                                            content = delta.get("content", "")

                                            # 处理 "think" 阶段
                                            if phase == "think":
                                                if status != "finished":
                                                    reasoning_text += content

                                            # 处理 "answer" 阶段
                                            elif phase == "answer" or (phase is None and content):
                                                has_sent_content = True
                                                assistant_content += content

                                                # 构造流式块
                                                openai_chunk = {
                                                    "id": f"chatcmpl-{chat_id[:10]}",
                                                    "object": "chat.completion.chunk",
                                                    "created": int(time.time()),
                                                    "model": model,
                                                    "choices": [{
                                                        "index": 0,
                                                        "delta": {"content": content},
                                                        "finish_reason": None
                                                    }]
                                                }

                                                # 在第一个块中附带推理内容
                                                if reasoning_text:
                                                    openai_chunk["choices"][0]["delta"]["reasoning_content"] = reasoning_text
                                                    reasoning_text = ""

                                                yield f"data: {json.dumps(openai_chunk)}\n\n"

                                            # 处理结束信号
                                            if status == "finished":
                                                finish_reason = delta.get("finish_reason", "stop")

                                    except json.JSONDecodeError:
                                        continue

                    except requests.exceptions.RequestException as e:
                        debug_log(f"多模态流式请求失败: {e}")
                        error_chunk = {
                            "id": f"chatcmpl-error",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model,
                            "choices": [{
                                "index": 0,
                                "delta": {"content": f"Error during streaming: {str(e)}"},
                                "finish_reason": "error"
                            }]
                        }
                        yield f"data: {json.dumps(error_chunk)}\n\n"

                    finally:
                        # 更新会话记录
                        if assistant_content and current_response_id:
                            self.update_session_after_chat(
                                chat_id=chat_id,
                                title=f"多模态对话_{int(time.time())}",
                                messages=messages + [{"role": "assistant", "content": assistant_content}],
                                current_response_id=current_response_id,
                                assistant_content=assistant_content
                            )

                return generate()

            else:
                # 非流式请求
                response_text = ""
                reasoning_text = ""
                finish_reason = "stop"
                usage_data = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                current_response_id = None

                try:
                    with self.session.post(url, json=payload, headers=headers, stream=True) as r:
                        r.raise_for_status()
                        for line in r.iter_lines(decode_unicode=True):
                            if line.startswith("data: "):
                                data_str = line[6:]
                                if data_str.strip() == "[DONE]":
                                    break

                                try:
                                    data = json.loads(data_str)

                                    # 提取response_id
                                    if "response.created" in data:
                                        current_response_id = data["response.created"].get("response_id")

                                    # 处理数据
                                    if "choices" in data and len(data["choices"]) > 0:
                                        delta = data["choices"][0].get("delta", {})

                                        # 累积推理内容
                                        if delta.get("phase") == "think":
                                            if delta.get("status") != "finished":
                                                reasoning_text += delta.get("content", "")

                                        # 累积答案内容
                                        if delta.get("phase") == "answer":
                                            if delta.get("status") != "finished":
                                                response_text += delta.get("content", "")

                                        # 收集 usage 信息
                                        if "usage" in data:
                                            qwen_usage = data["usage"]
                                            usage_data = {
                                                "prompt_tokens": qwen_usage.get("input_tokens", 0),
                                                "completion_tokens": qwen_usage.get("output_tokens", 0),
                                                "total_tokens": qwen_usage.get("total_tokens", 0),
                                            }

                                        # 检查结束信号
                                        if delta.get("status") == "finished":
                                            finish_reason = delta.get("finish_reason", "stop")

                                except json.JSONDecodeError:
                                    continue

                    # 更新会话记录
                    if response_text and current_response_id:
                        self.update_session_after_chat(
                            chat_id=chat_id,
                            title=f"多模态对话_{int(time.time())}",
                            messages=messages + [{"role": "assistant", "content": response_text}],
                            current_response_id=current_response_id,
                            assistant_content=response_text
                        )

                    # 构造非流式响应
                    openai_response = {
                        "id": f"chatcmpl-{chat_id[:10]}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": response_text
                            },
                            "finish_reason": finish_reason
                        }],
                        "usage": usage_data
                    }

                    # 添加推理内容
                    if reasoning_text:
                        openai_response["choices"][0]["message"]["reasoning_content"] = reasoning_text

                    return openai_response

                finally:
                    pass

        except requests.exceptions.RequestException as e:
            debug_log(f"多模态聊天补全失败: {e}")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "message": f"多模态聊天处理失败: {str(e)}",
                        "type": "server_error",
                        "param": None,
                        "code": None
                    }
                }
            )

    def parse_file_info_from_url(self, file_url: str) -> dict:
        """从文件URL解析文件信息，支持OSS URL和多种文件格式"""
        try:
            import urllib.parse as urlparse
            from urllib.parse import parse_qs

            parsed_url = urlparse.urlparse(file_url)

            # 生成文件ID（从URL路径提取或生成）
            path = parsed_url.path
            if path.startswith('/'):
                path = path[1:]

            # 尝试从路径中提取文件ID和名称
            path_parts = path.split('/')
            file_id = str(uuid.uuid4())
            filename = "uploaded_file.txt"

            if len(path_parts) >= 2:
                # 通常格式: user_id/file_id_filename
                potential_id_filename = path_parts[-1]
                if '_' in potential_id_filename:
                    parts = potential_id_filename.split('_', 1)
                    if len(parts) == 2:
                        file_id = parts[0]
                        filename = urlparse.unquote(parts[1])

            # 解析查询参数以获取更多信息
            query_params = parse_qs(parsed_url.query)

            # 使用辅助函数确定文件类型和content type
            file_type = determine_filetype(filename, None)
            content_type = determine_content_type(filename, None)

            # 根据file_type派生show_type和file_class
            if file_type == "image":
                show_type = "image"
                file_class = "vision"
            elif file_type == "video":
                show_type = "video"
                file_class = "video"
            else:
                show_type = "file"
                file_class = "document"

            return {
                "type": file_type,
                "file": {
                    "created_at": int(time.time() * 1000),
                    "data": {},
                    "filename": filename,
                    "hash": None,
                    "id": file_id,
                    "user_id": self.user_info.get('id', 'unknown') if self.user_info else 'unknown',
                    "meta": {
                        "name": filename,
                        "size": 0,  # 无法从URL获取大小
                        "content_type": content_type
                    },
                    "update_at": int(time.time() * 1000)
                },
                "id": file_id,
                "url": file_url,
                "name": filename,
                "collection_name": "",
                "progress": 0,
                "status": "uploaded",
                "greenNet": "success",
                "size": 0,
                "error": "",
                "itemId": str(uuid.uuid4()),
                "file_type": content_type,
                "showType": show_type,
                "file_class": file_class,
                "uploadTaskId": str(uuid.uuid4())
            }

        except Exception as e:
            debug_log(f"解析文件URL失败: {e}")
            # 返回基本的文件信息
            return {
                "type": "file",
                "file": {
                    "created_at": int(time.time() * 1000),
                    "data": {},
                    "filename": "file.txt",
                    "hash": None,
                    "id": str(uuid.uuid4()),
                    "user_id": self.user_info.get('id', 'unknown') if self.user_info else 'unknown',
                    "meta": {
                        "name": "file.txt",
                        "size": 0,
                        "content_type": "text/plain"
                    },
                    "update_at": int(time.time() * 1000)
                },
                "id": str(uuid.uuid4()),
                "url": file_url,
                "name": "file.txt",
                "status": "uploaded"
            }

    def upload_with_oss_post_form(self, file_content: bytes, file_path: str, content_type: str, sts_data: dict, filename: str) -> dict:
        """使用OSS POST表单上传（更可靠的方式）"""
        try:
            debug_log(f"使用OSS POST表单上传: {file_path}")
            
            import base64
            import json
            from datetime import datetime, timedelta
            import hmac
            import hashlib
            
            # 构建policy
            expire_time = datetime.utcnow() + timedelta(minutes=10)  # 10分钟过期
            expire_iso = expire_time.strftime('%Y-%m-%dT%H:%M:%S.000Z')
            
            policy_doc = {
                "expiration": expire_iso,
                "conditions": [
                    {"bucket": sts_data.get("bucketname", "qwen-webui-prod")},
                    {"key": file_path},
                    {"x-oss-security-token": sts_data["security_token"]},
                    ["eq", "$Content-Type", content_type],
                    ["content-length-range", 0, 10485760]  # 最大10MB
                ]
            }
            
            # 编码policy
            policy_encoded = base64.b64encode(json.dumps(policy_doc).encode()).decode()
            
            # 计算签名
            signature = base64.b64encode(
                hmac.new(
                    sts_data["access_key_secret"].encode(),
                    policy_encoded.encode(),
                    hashlib.sha1
                ).digest()
            ).decode()
            
            # 构建表单数据
            form_data = {
                'key': file_path,
                'policy': policy_encoded,
                'OSSAccessKeyId': sts_data["access_key_id"],
                'signature': signature,
                'x-oss-security-token': sts_data["security_token"],
                'Content-Type': content_type
            }
            
            # 准备文件
            files = {
                'file': (filename, file_content, content_type)
            }
            
            # OSS endpoint URL
            oss_endpoint = f"https://{sts_data.get('bucketname', 'qwen-webui-prod')}.{sts_data.get('endpoint', 'oss-accelerate.aliyuncs.com')}/"
            
            debug_log(f"POST表单上传到: {oss_endpoint}")
            debug_log(f"表单数据: {form_data}")
            
            # 执行POST表单上传
            response = requests.post(oss_endpoint, data=form_data, files=files)
            
            debug_log(f"OSS POST响应状态码: {response.status_code}")
            debug_log(f"OSS POST响应头: {dict(response.headers)}")
            
            if response.status_code >= 400:
                debug_log(f"OSS POST响应内容: {response.text[:500]}")
            
            if response.status_code in [200, 204]:
                debug_log("OSS POST表单上传成功！")
                # 构建访问URL
                access_url = f"https://{sts_data.get('bucketname', 'qwen-webui-prod')}.{sts_data.get('endpoint', 'oss-accelerate.aliyuncs.com')}/{file_path}"
                return {
                    "success": True,
                    "url": access_url,
                    "etag": response.headers.get("ETag", ""),
                    "request_id": response.headers.get("x-oss-request-id", "")
                }
            else:
                return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
                
        except Exception as e:
            debug_log(f"OSS POST表单上传异常: {e}")
            return {"success": False, "error": str(e)}
    

    async def upload_multipart_to_oss(self, file_content: bytes, sts_data: dict, filename: str, content_type: str) -> dict:
        """OSS分块上传实现 - 基于curlvode.txt的完整流程"""
        try:
            import hashlib
            import xml.etree.ElementTree as ET
            from datetime import datetime
            from urllib.parse import quote

            debug_log("开始OSS分块上传流程")

            # OSS基本信息
            bucket_name = sts_data.get('bucketname', 'qwen-webui-prod')
            endpoint = sts_data.get('endpoint', 'oss-accelerate.aliyuncs.com')
            file_path = sts_data.get('file_path', '')
            access_key_id = sts_data.get('access_key_id')
            access_key_secret = sts_data.get('access_key_secret')
            security_token = sts_data.get('security_token')

            if not all([access_key_id, access_key_secret, security_token, file_path]):
                return {"success": False, "error": "缺少必要的OSS凭据信息"}

            # 使用加速域名构建URL
            oss_url = f"https://{bucket_name}.{endpoint}/{quote(file_path, safe='/')}"

            # 第1步: 初始化分块上传
            debug_log("第1步: 初始化分块上传")
            init_url = f"{oss_url}?uploads="

            # 生成OSS v4签名 - 严格按照curlvode.txt格式
            def generate_oss_v4_signature(method: str, url: str, headers: dict, date_str: str):
                from urllib.parse import urlparse, parse_qs

                parsed_url = urlparse(url)

                # 1. CanonicalQueryString - 修复查询参数处理
                # 对于?uploads或?uploads=这种情况，应该生成"uploads"而不是空字符串
                if parsed_url.query:
                    # 手动解析查询字符串，保留空值参数
                    query_parts = []
                    for param in parsed_url.query.split('&'):
                        if '=' in param:
                            key, value = param.split('=', 1)
                            if value:
                                query_parts.append(f"{key}={value}")
                            else:
                                query_parts.append(key)  # ?uploads= 情况
                        else:
                            query_parts.append(param)  # ?uploads 情况
                    canonical_querystring = '&'.join(sorted(query_parts))
                else:
                    canonical_querystring = ''

                # 2. CanonicalHeaders - 必须包含所有参与签名的headers并按字母序排列
                # 注意：需要将headers键名转为小写进行匹配
                headers_lower = {k.lower(): v for k, v in headers.items()}

                canonical_headers_list = []
                signed_headers_list = []
                # 获取所有需要参与签名的headers（按字母序）
                required_headers = ['content-md5', 'content-type', 'x-oss-content-sha256', 'x-oss-date', 'x-oss-security-token', 'x-oss-user-agent']
                for header_name in sorted(required_headers):
                    if header_name in headers_lower:
                        canonical_headers_list.append(f"{header_name}:{headers_lower[header_name]}")
                        signed_headers_list.append(header_name)

                canonical_headers = '\n'.join(canonical_headers_list) + '\n'
                signed_headers = ';'.join(signed_headers_list)

                # 3. CanonicalURI - 修复URI处理（加速域名需要包含bucket名）
                # 对于加速域名 https://bucket.oss-accelerate.aliyuncs.com/path
                # CanonicalURI应该是 /bucket/path
                host = parsed_url.netloc
                path = parsed_url.path
                if 'oss-accelerate.aliyuncs.com' in host and '.' in host:
                    # 从host中提取bucket名
                    bucket = host.split('.')[0]
                    canonical_uri = f"/{bucket}{path}" if path else f"/{bucket}/"
                else:
                    canonical_uri = path or '/'

                canonical_request = f"{method}\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n\nUNSIGNED-PAYLOAD"
                debug_log(f"Canonical Request: {canonical_request}")

                # 4. String to Sign
                date_parts = date_str.split('T')
                date_scope = f"{date_parts[0]}/ap-southeast-1/oss/aliyun_v4_request"
                string_to_sign = f"OSS4-HMAC-SHA256\n{date_str}\n{date_scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"
                debug_log(f"String to Sign: {string_to_sign}")

                # 5. 计算签名
                def sign(key, msg):
                    return hmac.new(key, msg.encode() if isinstance(msg, str) else msg, hashlib.sha256).digest()
                
                # 使用正确的签名密钥生成方式
                date_key = sign(f"aliyun_v4{access_key_secret}".encode(), date_parts[0])
                region_key = sign(date_key, "ap-southeast-1")
                service_key = sign(region_key, "oss")
                signing_key = sign(service_key, "aliyun_v4_request")
                signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()

                # 6. Authorization Header - 严格按照curlvode.txt格式
                return f"OSS4-HMAC-SHA256 Credential={access_key_id}/{date_scope},Signature={signature}"

            # 初始化分块上传请求 - 完全按照curlvode.txt设置headers
            date_str = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
            init_headers = {
                'Accept': '*/*',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Connection': 'keep-alive',
                'Content-Length': '0',
                'Content-Type': content_type,
                'Origin': 'https://chat.qwen.ai',
                'Referer': 'https://chat.qwen.ai/',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'cross-site',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
                'sec-ch-ua': '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'x-oss-content-sha256': 'UNSIGNED-PAYLOAD',
                'x-oss-date': date_str,
                'x-oss-security-token': security_token,
                'x-oss-user-agent': 'aliyun-sdk-js/6.23.0 Chrome 132.0.0.0 on Windows 10 64-bit'
            }

            # 添加authorization头
            init_headers['authorization'] = generate_oss_v4_signature('POST', init_url, init_headers, date_str)

            response = requests.post(init_url, headers=init_headers)
            debug_log(f"初始化分块上传响应: {response.status_code}")

            if response.status_code != 200:
                debug_log(f"初始化分块上传失败: {response.text}")
                return {"success": False, "error": f"初始化分块上传失败: {response.status_code}"}

            # 解析upload_id
            upload_root = ET.fromstring(response.content)
            upload_id = upload_root.find('UploadId').text if upload_root.find('UploadId') is not None else None

            if not upload_id:
                return {"success": False, "error": "未能获取UploadId"}

            debug_log(f"获得UploadId: {upload_id}")

            # 第2步: 分块上传文件内容
            debug_log("第2步: 分块上传文件内容")

            chunk_size = 5 * 1024 * 1024  # 5MB per chunk
            total_size = len(file_content)
            part_number = 1
            parts = []

            for i in range(0, total_size, chunk_size):
                chunk = file_content[i:i + chunk_size]

                # 上传分块
                part_url = f"{oss_url}?partNumber={part_number}&uploadId={upload_id}"

                part_headers = {
                    'Accept': '*/*',
                    'Accept-Language': 'zh-CN,zh;q=0.9',
                    'Connection': 'keep-alive',
                    'Content-Type': content_type,
                    'Origin': 'https://chat.qwen.ai',
                    'Referer': 'https://chat.qwen.ai/',
                    'Sec-Fetch-Dest': 'empty',
                    'Sec-Fetch-Mode': 'cors',
                    'Sec-Fetch-Site': 'cross-site',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
                    'sec-ch-ua': '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                    'sec-ch-ua-mobile': '?0',
                    'sec-ch-ua-platform': '"Windows"',
                    'x-oss-content-sha256': 'UNSIGNED-PAYLOAD',
                    'x-oss-date': date_str,
                    'x-oss-security-token': security_token,
                    'x-oss-user-agent': 'aliyun-sdk-js/6.23.0 Chrome 132.0.0.0 on Windows 10 64-bit'
                }

                part_headers['authorization'] = generate_oss_v4_signature('PUT', part_url, part_headers, date_str)

                part_response = requests.put(part_url, data=chunk, headers=part_headers)
                debug_log(f"上传分块{part_number}响应: {part_response.status_code}")

                if part_response.status_code not in [200, 201]:
                    debug_log(f"分块{part_number}上传失败: {part_response.text}")
                    return {"success": False, "error": f"分块{part_number}上传失败"}

                # 获取ETag
                etag = part_response.headers.get('ETag', '').strip('"')
                parts.append({'PartNumber': part_number, 'ETag': etag})
                debug_log(f"分块{part_number}上传成功, ETag: {etag}")

                part_number += 1

            # 第3步: 完成分块上传
            debug_log("第3步: 完成分块上传")

            complete_url = f"{oss_url}?uploadId={upload_id}"

            # 构建完成上传的XML - 完全按照curlvode.txt格式
            complete_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<CompleteMultipartUpload>\n'
            for part in parts:
                complete_xml += f'<Part>\n<PartNumber>{part["PartNumber"]}</PartNumber>\n<ETag>"{part["ETag"]}"</ETag>\n</Part>\n'
            complete_xml += '</CompleteMultipartUpload>'

            # 设置完成上传的headers - 完全按照curlvode.txt
            import base64
            complete_headers = {
                'Accept': '*/*',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Connection': 'keep-alive',
                'Content-MD5': base64.b64encode(hashlib.md5(complete_xml.encode()).digest()).decode(),
                'Content-Type': 'application/xml',
                'Origin': 'https://chat.qwen.ai',
                'Referer': 'https://chat.qwen.ai/',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'cross-site',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
                'sec-ch-ua': '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'x-oss-content-sha256': 'UNSIGNED-PAYLOAD',
                'x-oss-date': date_str,
                'x-oss-security-token': security_token,
                'x-oss-user-agent': 'aliyun-sdk-js/6.23.0 Chrome 132.0.0.0 on Windows 10 64-bit'
            }

            complete_headers['authorization'] = generate_oss_v4_signature('POST', complete_url, complete_headers, date_str)

            complete_response = requests.post(complete_url, data=complete_xml, headers=complete_headers)
            debug_log(f"完成分块上传响应: {complete_response.status_code}")

            if complete_response.status_code not in [200, 201]:
                debug_log(f"完成分块上传失败: {complete_response.text}")
                return {"success": False, "error": f"完成分块上传失败: {complete_response.status_code}"}

            debug_log("OSS分块上传成功！")

            # 构建访问URL - 使用STS返回的完整签名URL
            if "file_url" in sts_data and sts_data["file_url"]:
                access_url = sts_data["file_url"]  # 使用带签名的预签名URL
            else:
                access_url = f"https://{bucket_name}.{endpoint}/{file_path}"
            
            return {
                "success": True,
                "url": access_url,
                "upload_id": upload_id,
                "parts_count": len(parts)
            }

        except Exception as e:
            debug_log(f"OSS分块上传异常: {e}")
            import traceback
            debug_log(f"异常详情: {traceback.format_exc()}")
            return {"success": False, "error": str(e)}

# Pydantic 模型定义
class Message(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str = "qwen3"
    messages: List[Message]
    stream: bool = False
    enable_thinking: bool = True
    thinking_budget: Optional[int] = None

class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str

class ModelsResponse(BaseModel):
    object: str = "list"
    data: List[ModelInfo]

# 多模态相关模型
class FileUploadRequest(BaseModel):
    filename: str
    filesize: int
    filetype: str = "image"

class STSTokenResponse(BaseModel):
    AccessKeyId: str
    AccessKeySecret: str
    SecurityToken: str
    Expiration: str
    Endpoint: str

class UploadResponse(BaseModel):
    success: bool
    url: str
    etag: str = ""
    request_id: str = ""

# 扩展Message模型以支持多模态内容
class MultiModalContent(BaseModel):
    type: str  # "text", "image_url", 或 "video_url"
    text: Optional[str] = None
    image_url: Optional[Dict[str, str]] = None
    video_url: Optional[Dict[str, str]] = None

class MultiModalMessage(BaseModel):
    role: str
    content: Any  # 可以是字符串或MultiModalContent列表

class MultiModalChatRequest(BaseModel):
    model: str = "qwen3-vl-plus"
    messages: List[MultiModalMessage]
    stream: bool = False
    enable_thinking: bool = True
    thinking_budget: Optional[int] = None

class VideoChatRequest(BaseModel):
    """一次性上传视频并开始多模态聊天的请求体（表单+JSON）。"""
    model: str = "qwen3-vl-plus"
    prompt: str
    stream: bool = True
    enable_thinking: bool = False
    thinking_budget: Optional[int] = None

# --- FastAPI 应用 ---
app = FastAPI(
    title="Qwen OpenAI API Proxy",
    description="千问 (Qwen) OpenAI API 代理",
    version="1.0.0"
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境请根据需要进行限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化客户端
qwen_client = QwenClient(auth_token=QWEN_AUTH_TOKEN, cookies=QWEN_COOKIES)

# 启动时进行全面的Cookie健康检查
logger.debug("\n🔍 启动时Cookie健康检查:")
startup_status = qwen_client._check_cookie_health(force_check=True)
if startup_status and startup_status['healthy']:
    logger.debug("✅ 所有Cookie参数状态良好")
logger.debug("=" * 50)

@app.get("/v1/models", response_model=ModelsResponse)
async def list_models():
    """列出可用模型 (模拟 OpenAI API)"""
    try:
        # 检查token是否有效
        if not qwen_client.models_info:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "message": "QWEN_AUTH_TOKEN 无效或未设置，无法获取模型列表。请在 .env 文件中设置有效的token。",
                        "type": "authentication_error",
                        "param": None,
                        "code": "invalid_api_key"
                    }
                }
            )
        
        # 从已获取的模型信息构造 OpenAI 格式列表
        openai_models = []
        for model_id, model_info in qwen_client.models_info.items():
            openai_models.append(ModelInfo(
                id=model_info['info']['id'],
                created=model_info['info']['created_at'],
                owned_by=model_info['owned_by']
            ))
        return ModelsResponse(data=openai_models)
    except Exception as e:
        logger.debug(f"列出模型时出错: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "message": f"获取模型列表失败: {e}",
                    "type": "server_error",
                    "param": None,
                    "code": None
                }
            }
        )

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, auth_token: str = Depends(verify_auth_token)):
    """处理 OpenAI 兼容的聊天补全请求"""
    openai_request = request.dict()
    
    try:
        result = await qwen_client.chat_completions(openai_request)
        if request.stream:
            # 如果是流式响应，返回 StreamingResponse
            return StreamingResponse(result, media_type='text/event-stream')
        else:
            # 如果是非流式响应，直接返回 JSON
            return result
    except HTTPException:
        # 重新抛出 HTTPException
        raise
    except Exception as e:
        debug_log(f"处理聊天补全请求时发生未预期错误: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "message": f"内部服务器错误: {str(e)}",
                    "type": "server_error",
                    "param": None,
                    "code": None
                }
            }
        )

@app.delete("/v1/chats/{chat_id}")
async def delete_chat(chat_id: str):
    """删除指定的对话"""
    try:
        success = qwen_client.delete_chat(chat_id)
        if success:
            return {"message": f"会话 {chat_id} 已删除", "success": True}
        else:
            raise HTTPException(
                status_code=400,
                detail={"message": f"删除会话 {chat_id} 失败", "success": False}
            )
    except Exception as e:
        debug_log(f"删除会话时发生错误: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "message": f"删除会话失败: {str(e)}",
                    "type": "server_error",
                    "param": None,
                    "code": None
                }
            }
        )

@app.get("/")
async def index():
    """根路径，返回 API 信息"""
    return {
        "message": "千问 (Qwen) OpenAI API 代理正在运行。",
        "docs": "https://platform.openai.com/docs/api-reference/chat"
    }

@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy"}

# 多模态相关路由
@app.post("/v2/files/getstsToken")
async def get_sts_token(request: FileUploadRequest):
    """获取OSS临时授权Token"""
    try:
        result = await qwen_client.get_sts_token(
            filename=request.filename,
            filesize=request.filesize,
            filetype=request.filetype
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        debug_log(f"获取STS Token时发生未预期错误: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "message": f"获取上传授权失败: {str(e)}",
                    "type": "server_error",
                    "param": None,
                    "code": None
                }
            }
        )

@app.post("/v1/files/upload")
async def upload_file(file: UploadFile = File(...), auth_token: str = Depends(verify_auth_token)):
    """上传文件接口（支持多种文件格式：图片、文档、表格、文本等）"""
    try:
        # 使用辅助函数确定文件类型
        filetype = determine_filetype(file.filename or "", file.content_type)
        debug_log(f"文件类型检测: {file.filename} -> Content-Type: {file.content_type} -> filetype: {filetype}")
        
        # 读取文件内容
        file_content = await file.read()
        file_size = len(file_content)
        
        # 获取STS Token
        sts_result = await qwen_client.get_sts_token(
            filename=file.filename or "uploaded_file",
            filesize=file_size,
            filetype=filetype
        )
        
        debug_log(f"STS结果: {sts_result}")
        
        # 检查STS响应结构
        if not sts_result.get("success", False):
            raise HTTPException(
                status_code=500,
                detail={"error": {"message": "获取上传授权失败：API返回失败状态", "type": "sts_error"}}
            )
        
        sts_data = sts_result.get("data")
        if not sts_data:
            raise HTTPException(
                status_code=500,
                detail={"error": {"message": "获取上传授权失败：响应数据为空", "type": "sts_error"}}
            )
        
        debug_log(f"STS数据: {sts_data}")
        
        # 检查必需的字段是否存在
        required_fields = ["access_key_id", "access_key_secret", "security_token"]
        missing_fields = [field for field in required_fields if field not in sts_data]
        if missing_fields:
            raise HTTPException(
                status_code=500,
                detail={"error": {"message": f"STS响应缺少必需字段: {', '.join(missing_fields)}", "type": "sts_error"}}
            )
        
        # 检查STS响应中的上传信息
        debug_log(f"完整STS数据: {sts_data}")

        # 使用辅助函数确定详细Content-Type
        content_type = determine_content_type(file.filename or "", file.content_type)
        debug_log(f"最终Content-Type: {content_type}")

        # 根据文件大小和类型，决定使用普通上传还是分块上传
        MULTIPART_THRESHOLD = 5 * 1024 * 1024  # 5MB
        use_multipart = filetype == "video" or file_size > MULTIPART_THRESHOLD

        debug_log(f"文件大小: {file_size} bytes, 文件类型: {filetype}, 使用分块上传: {use_multipart}")

        if use_multipart:
            debug_log("使用OSS分块上传处理大文件/视频文件")
            upload_result = await qwen_client.upload_multipart_to_oss(
                file_content,
                sts_data,
                file.filename or "uploaded_file",
                content_type
            )
        else:
            # 使用POST表单上传（已验证成功的方案）- 参考qwen_fastapi20250930.py
            debug_log("使用POST表单上传（小文件）")
            upload_result = qwen_client.upload_with_oss_post_form(
                file_content,
                sts_data["file_path"],
                content_type,
                sts_data,
                file.filename or "uploaded_file"
            )
        
        if upload_result["success"]:
            # 详细调试 STS 数据和 URL 信息
            debug_log(f"=== URL 生成调试信息 ===")
            debug_log(f"STS数据中的file_url: {sts_data.get('file_url', '未提供')}")
            debug_log(f"上传结果URL: {upload_result.get('url', '未提供')}")
            
            # 关键修复：优先使用STS响应中的预签名URL，确保外部访问权限
            # sts_data["file_url"] 包含完整的签名参数，支持外部下载和AI访问
            if "file_url" in sts_data and sts_data["file_url"]:
                file_access_url = sts_data["file_url"]  # 使用带签名的预签名URL
                debug_log(f"✅ 使用STS预签名URL（推荐）")
            else:
                file_access_url = upload_result["url"]  # 降级使用上传结果URL
                debug_log(f"⚠️  降级使用上传结果URL（可能无外部访问权限）")
            
            debug_log(f"最终文件访问URL: {file_access_url}")
            debug_log(f"URL类型: {'预签名URL(带签名)' if 'x-oss-signature' in file_access_url else '基础URL(无签名)'}")
            debug_log(f"========================")
            
            return {
                "id": sts_data.get("file_id", str(uuid.uuid4())),
                "object": "file", 
                "bytes": file_size,
                "created_at": int(time.time()),
                "filename": file.filename,
                "purpose": "multimodal",
                "url": file_access_url,  # 使用带签名的预签名URL
                "status": "uploaded",
                "filetype": filetype,  # 添加文件类型信息
                "content_type": content_type  # 添加内容类型信息
            }
        else:
            # 上传失败，直接返回错误
            error_msg = f"文件上传失败: {upload_result.get('error', '未知错误')}"
            debug_log(error_msg)
            raise HTTPException(
                status_code=500,
                detail={"error": {"message": error_msg, "type": "upload_error"}}
            )
        
    except HTTPException:
        raise
    except Exception as e:
        debug_log(f"文件上传时发生未预期错误: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "message": f"文件上传失败: {str(e)}",
                    "type": "server_error",
                    "param": None,
                    "code": None
                }
            }
        )

@app.post("/v1/chat/multimodal")
async def multimodal_chat_completions(request: MultiModalChatRequest, auth_token: str = Depends(verify_auth_token)):
    """处理多模态聊天补全请求 - 支持图片、PDF、Word、Excel、TXT等多种文件格式"""
    try:
        # 直接调用新的多模态方法，不再做转换
        openai_request = request.dict()

        result = await qwen_client.multimodal_chat_completions(openai_request)

        if request.stream:
            return StreamingResponse(result, media_type='text/event-stream')
        else:
            return result

    except HTTPException:
        raise
    except Exception as e:
        debug_log(f"处理多模态聊天补全请求时发生未预期错误: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "message": f"多模态聊天处理失败: {str(e)}",
                    "type": "server_error",
                    "param": None,
                    "code": None
                }
            }
        )

@app.post("/v1/image/upload_and_chat", dependencies=[Depends(verify_auth_token)])
async def upload_image_and_chat(
    image: UploadFile = File(...),
    model: str = Form("qwen3-vl-plus"),
    prompt: str = Form(...),
    stream: bool = Form(False),
    enable_thinking: bool = Form(False),
    thinking_budget: Optional[int] = Form(None),
    auth_token: str = Depends(verify_auth_token)
):
    """上传图片文件到OSS并基于该图片发起一次多模态聊天（一体化接口）

    Args:
        image: 图片文件（支持 JPEG、PNG、GIF、WebP 等格式）
        model: 模型名称，默认 qwen3-vl-plus
        prompt: 对话提示词
        stream: 是否使用流式响应，默认 False
        enable_thinking: 是否启用思考模式，默认 False
        thinking_budget: 思考预算（可选）

    Returns:
        流式或非流式的多模态对话响应

    Example:
        ```bash
        curl -X POST http://localhost:8000/v1/image/upload_and_chat \
          -H "Authorization: Bearer sk-your-token" \
          -F "image=@/path/to/image.jpg" \
          -F "model=qwen3-vl-plus" \
          -F "prompt=请分析这张图片的内容" \
          -F "stream=false"
        ```
    """
    try:
        # 读取图片内容
        content = await image.read()
        size = len(content)

        # 验证文件大小（建议不超过 10MB）
        max_size = 10 * 1024 * 1024  # 10MB
        if size > max_size:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "message": f"图片文件过大，最大支持 {max_size / (1024 * 1024):.0f}MB",
                        "type": "invalid_request_error",
                        "param": "image",
                        "code": "file_too_large"
                    }
                }
            )

        # 获取文件扩展名和 Content-Type
        filename = image.filename or "image.jpg"
        file_ext = os.path.splitext(filename)[1].lower()

        # 图片格式映射
        image_content_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.bmp': 'image/bmp',
            '.tiff': 'image/tiff',
            '.svg': 'image/svg+xml',
            '.ico': 'image/x-icon'
        }

        content_type = image_content_types.get(file_ext, image.content_type or 'image/jpeg')

        debug_log(f"上传图片: {filename}, 大小: {size} bytes, 类型: {content_type}")

        # 获取STS授权（filetype=image）
        sts_result = await qwen_client.get_sts_token(
            filename=filename,
            filesize=size,
            filetype="image"
        )

        if not sts_result.get("success"):
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "message": "获取上传授权失败",
                        "type": "sts_error"
                    }
                }
            )

        sts_data = sts_result.get("data", {})

        # 选择上传策略：
        # - 图片 <5MB: 使用直接 PUT 上传
        # - 图片 ≥5MB: 使用分块上传
        if size >= 5 * 1024 * 1024:  # 5MB
            debug_log(f"图片文件 ≥5MB，使用分块上传")
            upload_result = await qwen_client.upload_multipart_to_oss(
                content, sts_data, filename, content_type
            )
        else:
            debug_log(f"图片文件 <5MB，使用POST表单上传")
            upload_result = qwen_client.upload_with_oss_post_form(
                content,
                sts_data["file_path"],
                content_type,
                sts_data,
                filename
            )

        if not upload_result.get("success"):
            # 尝试备用方案
            if size >= 5 * 1024 * 1024:
                debug_log("分块上传失败，尝试POST表单上传")
                upload_result = qwen_client.upload_with_oss_post_form(
                    content,
                    sts_data["file_path"],
                    content_type,
                    sts_data,
                    filename
                )
            else:
                debug_log("直接上传失败，尝试分块上传")
                upload_result = await qwen_client.upload_multipart_to_oss(
                    content, sts_data, filename, content_type
                )

            if not upload_result.get("success"):
                raise HTTPException(
                    status_code=500,
                    detail={
                        "error": {
                            "message": upload_result.get("error", "图片上传失败"),
                            "type": "upload_error"
                        }
                    }
                )

        # 构造可访问URL（优先使用STS的预签名URL）
        file_access_url = sts_data.get("file_url") or upload_result.get("url")
        if not file_access_url:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "message": "未获取到图片访问URL",
                        "type": "upload_error"
                    }
                }
            )

        debug_log(f"图片上传成功，URL: {file_access_url[:80]}...")

        # ✅ 构造完整的文件信息对象（而不是仅传递URL）
        file_id = sts_data.get("file_id", str(uuid.uuid4()))

        # 确定文件类型和类别
        file_type = "image"  # 当前接口专用于图片
        show_type = "image"
        file_class = "vision"

        # 构造符合 Qwen API 格式的完整文件信息
        complete_file_info = {
            "type": file_type,
            "file": {
                "created_at": int(time.time() * 1000),
                "data": {},
                "filename": filename,
                "hash": None,
                "id": file_id,
                "user_id": qwen_client.user_info.get('id', 'unknown') if qwen_client.user_info else 'unknown',
                "meta": {
                    "name": filename,
                    "size": size,  # ✅ 使用真实文件大小
                    "content_type": content_type
                },
                "update_at": int(time.time() * 1000)
            },
            "id": file_id,
            "url": file_access_url,
            "name": filename,
            "collection_name": "",
            "progress": 0,
            "status": "uploaded",
            "greenNet": "success",
            "size": size,  # ✅ 使用真实文件大小
            "error": "",
            "itemId": str(uuid.uuid4()),
            "file_type": content_type,
            "showType": show_type,
            "file_class": file_class,
            "uploadTaskId": str(uuid.uuid4())
        }

        # 构造多模态消息 - 传入完整文件信息
        messages = [
            MultiModalMessage(
                role="user",
                content=[
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": file_access_url},
                        "file_info": complete_file_info  # ✅ 传入完整文件信息
                    },
                ],
            )
        ]

        chat_req = MultiModalChatRequest(
            model=model,
            messages=messages,
            stream=stream,
            enable_thinking=enable_thinking,
            thinking_budget=thinking_budget,
        )

        debug_log(f"发起多模态对话，模型: {model}, 流式: {stream}")

        result = await qwen_client.multimodal_chat_completions(chat_req.dict())

        if stream:
            return StreamingResponse(result, media_type='text/event-stream')
        else:
            return result

    except HTTPException:
        raise
    except Exception as e:
        debug_log(f"上传图片并聊天时发生错误: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "message": f"上传图片并聊天失败: {str(e)}",
                    "type": "server_error",
                    "param": None,
                    "code": None
                }
            }
        )


@app.post("/v1/video/upload_and_chat", dependencies=[Depends(verify_auth_token)])
async def upload_video_and_chat(
    video: UploadFile = File(...),
    model: str = Form("qwen3-vl-plus"),
    prompt: str = Form(...),
    stream: bool = Form(True),
    enable_thinking: bool = Form(False),
    thinking_budget: Optional[int] = Form(None),
    auth_token: str = Depends(verify_auth_token)
):
    """上传视频文件到OSS并基于该视频发起一次多模态聊天。
    - 使用与 curlvode.txt 一致的分块上传流程（视频或大文件）
    - 将生成的可访问URL作为 files 中的 video 项传给 /api/v2/chat/completions
    """
    try:
        # 读取视频内容
        content = await video.read()
        size = len(content)

        # 获取STS授权（filetype=video）
        sts_result = await qwen_client.get_sts_token(
            filename=video.filename or "video.mp4",
            filesize=size,
            filetype="video"
        )
        if not sts_result.get("success"):
            raise HTTPException(status_code=500, detail={"error": {"message": "获取上传授权失败", "type": "sts_error"}})
        sts_data = sts_result.get("data", {})

        # 选择上传策略：视频或超过5MB使用分块上传
        content_type = video.content_type or "video/mp4"
        use_multipart = True
        upload_result = await qwen_client.upload_multipart_to_oss(content, sts_data, video.filename or "video.mp4", content_type)

        if not upload_result.get("success"):
            # 回退到POST表单上传（小概率）
            upload_result = qwen_client.upload_with_oss_post_form(
                content,
                sts_data["file_path"],
                content_type,
                sts_data,
                video.filename or "video.mp4"
            )
            if not upload_result.get("success"):
                raise HTTPException(status_code=500, detail={"error": {"message": upload_result.get("error", "上传失败"), "type": "upload_error"}})

        # 构造可访问URL（优先使用STS的预签名URL）
        file_access_url = sts_data.get("file_url") or upload_result.get("url")
        if not file_access_url:
            raise HTTPException(status_code=500, detail={"error": {"message": "未获取到文件访问URL", "type": "upload_error"}})

        debug_log(f"视频上传成功，URL: {file_access_url[:80]}...")

        # ✅ 构造完整的文件信息对象（而不是仅传递URL）
        file_id = sts_data.get("file_id", str(uuid.uuid4()))
        filename = video.filename or "video.mp4"

        # 确定文件类型和类别
        file_type = "video"  # 当前接口专用于视频
        show_type = "video"
        file_class = "video"

        # 构造符合 Qwen API 格式的完整文件信息
        complete_file_info = {
            "type": file_type,
            "file": {
                "created_at": int(time.time() * 1000),
                "data": {},
                "filename": filename,
                "hash": None,
                "id": file_id,
                "user_id": qwen_client.user_info.get('id', 'unknown') if qwen_client.user_info else 'unknown',
                "meta": {
                    "name": filename,
                    "size": size,  # ✅ 使用真实文件大小
                    "content_type": content_type
                },
                "update_at": int(time.time() * 1000)
            },
            "id": file_id,
            "url": file_access_url,
            "name": filename,
            "collection_name": "",
            "progress": 0,
            "status": "uploaded",
            "greenNet": "success",
            "size": size,  # ✅ 使用真实文件大小
            "error": "",
            "itemId": str(uuid.uuid4()),
            "file_type": content_type,
            "showType": show_type,
            "file_class": file_class,
            "uploadTaskId": str(uuid.uuid4())
        }

        # 构造多模态消息 - 传入完整文件信息
        messages = [
            MultiModalMessage(
                role="user",
                content=[
                    {"type": "text", "text": prompt},
                    {
                        "type": "video_url",
                        "video_url": {"url": file_access_url},
                        "file_info": complete_file_info  # ✅ 传入完整文件信息
                    },
                ],
            )
        ]

        chat_req = MultiModalChatRequest(
            model=model,
            messages=messages,
            stream=stream,
            enable_thinking=enable_thinking,
            thinking_budget=thinking_budget,
        )

        result = await qwen_client.multimodal_chat_completions(chat_req.dict())
        return StreamingResponse(result, media_type='text/event-stream') if stream else result

    except HTTPException:
        raise
    except Exception as e:
        debug_log(f"上传视频并聊天时发生错误: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "message": f"上传视频并聊天失败: {str(e)}",
                    "type": "server_error",
                    "param": None,
                    "code": None
                }
            }
        )

if __name__ == '__main__':
    import uvicorn
    logger.debug(f"正在启动服务器于端口 {PORT}...")
    logger.debug(f"Debug模式: {'开启' if DEBUG_STATUS else '关闭'}")
    uvicorn.run(app, host='0.0.0.0', port=PORT)
