import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    MAX_CONTENT_LENGTH = 5000
    DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "app.db")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    CUSTOM_API_KEY = os.environ.get("CUSTOM_API_KEY")
    CUSTOM_BASE_URL = os.environ.get("CUSTOM_BASE_URL", "https://api.hcnsec.cn/v1")
    CUSTOM_MODEL = os.environ.get("CUSTOM_MODEL", "Qwen3.8-Flash-Next")
