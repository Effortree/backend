# config.py
from dotenv import load_dotenv
import os

# .env 로드 (프로젝트 시작 시 1회)
load_dotenv()

# 환경변수 읽기
MONGO_URL = os.getenv("MONGO_URL")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")