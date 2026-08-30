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

# torch 를 CPU 전용 휠로 먼저 설치한다.
# 리눅스에서 그냥 `pip install torch` 를 하면 CUDA 빌드가 딸려오는데
# (nvidia_cudnn 445MB, cusparselt 221MB, nccl 206MB 등), 이 컨테이너는 CPU 로만
# 추론하므로 전부 쓰이지 않는 용량이다. 이미지가 9.5GB 까지 부풀었다.
# 아래에서 torch 가 이미 충족되므로 requirements.txt 설치 시 재다운로드되지 않는다.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

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
