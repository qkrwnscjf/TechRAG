import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    google_api_key: str
    github_token: Optional[str] = None
    pinecone_api_key: str
    pinecone_index_name: str = "techdoc"
    # 기존 인덱스의 메트릭이 cosine 일 때 삭제 후 재생성을 허용할지 여부.
    # 파괴적 작업이므로 기본값은 False (거부하고 명확한 에러 발생).
    pinecone_allow_index_recreate: bool = False

    # --- Retrieval / Reranker ---
    # 최종적으로 생성 노드에 넘길 문서 수
    # 4 -> 5. 실측: 정답 포함률 90.7% -> 92.6% (54질의 중 1건). k=8 까지 넓혀도
    # 더 들어오는 질의가 없어(5 와 8 이 동일) 5 에서 멈춘다. 남은 미포함 4건은
    # 정답이 9~28위에 있어 k 로는 닿지 않는다. (BENCHMARK Phase 33)
    retriever_top_k: int = 5
    # 리랭커를 켰을 때 검색 단계에서 뽑을 후보 수 (넓게 뽑아 리랭커로 좁힌다)
    reranker_candidates: int = 10
    # 리랭커 활성화 여부. CPU 환경에서는 질문당 3~7초가 추가되므로 기본은 비활성.
    reranker_enabled: bool = False
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_device: str = "cpu"
    reranker_max_length: int = 256
    # 원점수(logit) 하한. None 이면 순위만 보고 자르지 않는다.
    reranker_score_threshold: Optional[float] = None

    # --- LLM 호출 예산 ---
    # Gemini 무료 티어는 분당 5회, 하루 20회다. 질문당 호출 수를 줄이지 않으면
    # 연속 대화가 불가능하다. 채점은 전체 문서를 한 번에 묶어 1회로 처리한다.

    # --- 수집 필터 ---
    # GitLoader 는 레포의 .md 를 전부 긁어온다. 의존성/빌드 산출물이나 템플릿 문서가
    # 섞이면 색인의 상당 부분이 노이즈가 되고, 검색이 그만큼 흐려진다.
    # 경로에 아래 조각이 포함되면 건너뛴다(콤마 구분).
    github_md_exclude: str = "node_modules,dist,build,.github,venv,site-packages,CHANGELOG"
    # 수집 대상 확장자. 기술 문서는 .md 만 쓰지 않는다 — Docusaurus 는 .mdx,
    # Sphinx 는 .rst 를 쓴다.
    #
    # .ipynb(주피터 노트북)는 기본에서 제외했다. 변환기(loader.notebook_to_text)는
    # 완성돼 있고 정상 동작하지만, 노트북까지 포함하면 수집량이 10배 가까이 늘어난다.
    # (langgraph 레포 기준 109청크 -> 약 1,050청크) 로컬 임베딩이라 API 비용은 없으나
    # 저사양 기기에서는 수집이 수십 분 걸리고 메모리 압박이 심하다.
    # 노트북까지 필요하면 GITHUB_INCLUDE_EXT 에 .ipynb 를 추가하면 즉시 동작한다.
    github_include_ext: str = ".md,.mdx,.rst,.txt"

    # --- 대화 이력 ---
    # messages 는 operator.add 로 누적되고 체크포인터에 영구 저장된다. 제한이 없으면
    # 대화가 길어질수록 contextualize 프롬프트가 선형으로 커져 비용과 지연이 함께 늘고,
    # 결국 컨텍스트 한도를 넘는다. 최근 N개 메시지만 사용한다(사용자+AI 합산).
    history_window: int = 6

    # --- 임베딩 디바이스 ---
    # "cpu" | "mps" | "cuda" | "auto"("auto" 는 cuda -> mps -> cpu 순으로 자동 선택)
    #
    # 기본값이 cpu 인 이유 (BENCHMARK.md Phase 9 / Phase 13):
    #   질의 1건 임베딩은 mps 가 13.8배 빠르다 (2,768ms -> 201ms).
    #   그러나 8GB 통합 메모리 환경에서 대량 문서를 배치로 임베딩하면 메모리 압박이
    #   누적되어 배치당 15초가 287초로 무너진다(실측). 수집 하나가 기기를 30분 이상
    #   마비시킬 수 있다.
    #   "조금 느린 것"과 "기기가 멈추는 것"은 다른 문제이므로 안전한 쪽을 기본으로 둔다.
    #
    # 질의 지연이 중요하고 대량 수집을 하지 않는다면 EMBEDDING_DEVICE=mps 로 바꾼다.
    # GPU(cuda) 환경에서는 auto 또는 cuda 가 두 작업 모두에 유리하다.
    embedding_device: str = "cpu"

    # --- CORS ---
    # 프론트엔드는 기본적으로 동일 출처(/api)를 쓰므로 CORS가 필요 없지만,
    # 백엔드를 8000 포트로 직접 호출하는 경우를 위해 허용 출처를 열어둔다.
    # 쉼표로 구분해 CORS_ORIGINS 환경변수로 덮어쓸 수 있다.
    cors_origins: str = "http://localhost,http://localhost:3000,http://localhost:5173,http://127.0.0.1:5173"
    
    # --- LangSmith Observability ---
    langchain_tracing_v2: Optional[str] = "false"
    langchain_api_key: Optional[str] = None
    langchain_project: Optional[str] = "TechDoc-Agent"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

# LangChain/LangGraph가 백그라운드에서 추적할 수 있도록 OS 환경변수로 강제 주입
if settings.langchain_api_key and settings.langchain_tracing_v2.lower() == "true":
    os.environ["LANGCHAIN_TRACING_V2"] = settings.langchain_tracing_v2
    os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project

def get_cors_origins() -> list[str]:
    """콤마 구분 문자열을 리스트로 변환."""
    return [o.strip() for o in settings.cors_origins.split(",") if o.strip()]


def get_md_excludes() -> list[str]:
    """수집에서 제외할 경로 조각 목록."""
    return [x.strip() for x in settings.github_md_exclude.split(",") if x.strip()]


def resolve_device(preference: str = None) -> str:
    """'auto' 를 실제 디바이스 이름으로 바꾼다."""
    pref = (preference or settings.embedding_device or "auto").lower()
    if pref != "auto":
        return pref
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def get_include_exts() -> list[str]:
    """수집 대상 확장자 목록 (소문자, 점 포함)."""
    return [x.strip().lower() for x in settings.github_include_ext.split(",") if x.strip()]
