# backend/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# SQLite 및 컴파일에 필요한 필수 OS 패키지 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 코드 복사
COPY . .

# SQLite DB와 메모리 체크포인트가 저장될 데이터 폴더 생성
RUN mkdir -p /app/data

EXPOSE 8000

# 기본 실행은 FastAPI 서버 구동
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
