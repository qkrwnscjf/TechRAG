from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
import logging
from logging.handlers import RotatingFileHandler

from api.routes import ingest, stream
from config import get_cors_origins

# 로그 영구 저장 및 로테이션 설정
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = RotatingFileHandler('app.log', maxBytes=10*1024*1024, backupCount=5)
file_handler.setFormatter(log_formatter)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(log_formatter)

logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 스케줄러 중복 실행 방지를 위해 백그라운드 태스크에서 제거함
    # 별도의 프로세스(python scheduler.py)로 실행해야 함
    yield

app = FastAPI(title="TechDoc Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health():
    """컨테이너 헬스체크용. 외부 의존성을 건드리지 않는 가벼운 응답만 돌려준다."""
    return {"status": "ok"}


app.include_router(ingest.router, prefix="/api")
app.include_router(stream.router, prefix="/api")

if __name__ == "__main__":
    uvicorn.run("backend.api.main:app", host="0.0.0.0", port=8000, reload=True)
