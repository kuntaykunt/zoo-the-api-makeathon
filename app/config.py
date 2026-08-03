import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
    QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-vl-max")
    
    ZOO_API_KEY = os.getenv("ZOO_API_KEY", "")
    ZOO_BASE_URL = os.getenv("ZOO_BASE_URL", "https://api.zoo.dev")
    
    PORT = int(os.getenv("PORT", 8000))
    HOST = os.getenv("HOST", "0.0.0.0")

config = Config()
