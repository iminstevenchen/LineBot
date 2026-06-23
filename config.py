import os
import configparser
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_ROOT, '.env'))

# LINE Bot 金鑰：優先從環境變數讀（Render 部署用），fallback 到 config.ini（本地開發用）
_cfg = configparser.ConfigParser()
_cfg.read(os.path.join(_ROOT, 'config.ini'))

LINE_CHANNEL_ACCESS_TOKEN = (
    os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
    or _cfg.get('line-bot', 'channel_access_token', fallback='')
)
LINE_CHANNEL_SECRET = (
    os.getenv('LINE_CHANNEL_SECRET')
    or _cfg.get('line-bot', 'channel_secret', fallback='')
)

# 資料庫（從 .env 讀取）
DATABASE_URL = os.getenv('DATABASE_URL', '')

# 連線池大小
DB_POOL_MIN = 1
DB_POOL_MAX = 5

# Groq
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
GROQ_MODEL   = 'llama-3.3-70b-versatile'

# RAG API（隊友的 AnythingLLM，留空則使用 Mock RAG）
RAG_API_URL = os.getenv('RAG_API_URL', '')
