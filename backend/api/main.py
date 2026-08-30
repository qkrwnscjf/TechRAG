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
    # 스케줄러는 여기서 띄우지 않는다. 워커가 여러 개면 잡이 중복 실행되므로
    # 별도 프로세스(python scheduler.py)로 돌린다.
    #
    # 임베딩 모델은 기동 시 미리 올린다.
    # 싱글턴이 지연 초기화(get_vector_store_manager)로 바뀌면서, 그냥 두면 첫 질의가
    # 모델 로드(약 30초)를 떠안게 된다. API 서버는 어차피 모델이 필요하므로 여기서 끝낸다.
    # 반대로 scheduler.py 는 이 워밍업을 하지 않아 잡이 돌기 전까지 메모리를 쓰지 않는다.
    try:
        import asyncio
        from store.vectorstore import get_vector_store_manager
        logging.info("Warming up embedding model...")
        await asyncio.to_thread(get_vector_store_manager)
        logging.info("Embedding model ready.")
    except Exception as e:
        # 워밍업 실패로 서버가 죽지는 않게 한다. 첫 질의 때 다시 시도된다.
        logging.error("Embedding warm-up failed (will retry on first request): %s", e)
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
