# backend/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 컴파일 도구와 git.
# git 은 GitPython(ingest/loader.py 의 Repo.clone_from)이 호출하는 실행 파일이다.
# 없으면 `from git import Repo` 가 import 단계에서 실패해 서버가 아예 뜨지 못한다.
# (로컬에는 git 이 있어 드러나지 않고 컨테이너에서만 크래시 루프로 나타난다.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 코드 복사
COPY . .

# SQLite DB와 메모리 체크포인트가 저장될 데이터 폴더 생성
RUN mkdir -p /app/data

# GitPython 이 import 시점에 git 을 못 찾아도 예외를 던지지 않게 한다(위에서 설치했으나 방어).
ENV GIT_PYTHON_REFRESH=quiet

EXPOSE 8000

# 기본 실행은 FastAPI 서버 구동
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
