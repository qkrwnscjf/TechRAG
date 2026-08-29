# TechDoc Agent

개발 문서를 스스로 최신화하고, 자신의 검색 결과를 스스로 검증하는 RAG 챗봇입니다.

기술 문서는 계속 바뀝니다. 한 번 색인하고 끝내면 곧 낡은 답을 내놓습니다.
그래서 이 프로젝트는 **문서를 주기적으로 다시 읽어 벡터 DB를 갱신하는 파이프라인**과,
**검색 결과가 질문에 맞는지 스스로 채점하고 필요하면 질문을 고쳐 다시 검색하는 에이전트**를
하나로 묶었습니다.

## 사용 스택

| 영역 | 선택 |
|---|---|
| LLM | Google Gemini 2.5 Flash (Vision 포함) |
| Embedding | BAAI/bge-m3 (HuggingFace, 로컬 추론) |
| Vector DB | Pinecone Serverless (Hybrid: Dense + Sparse BM25) |
| Reranker (선택) | BAAI/bge-reranker-v2-m3 Cross-Encoder |
| Agent | LangGraph & LangChain (순환형 State Machine) |
| Backend | FastAPI, SQLite |
| Automation | APScheduler (독립 프로세스) |
| Frontend | React + Vite, EventSource(SSE) |
| Deployment | Docker Compose, Nginx |
| Observability | LangSmith |

> UI 출처: https://www.designprompts.dev/ 프롬포트 참조

---

# 아키텍처

## 전체 구조

서로 독립적인 두 개의 파이프라인으로 나뉩니다. 하나는 지식을 채우고, 하나는 지식을 꺼냅니다.

```
[수집]  URL ──▶ 로더 ──▶ 해시 검사 ──▶ 청킹 ──▶ 임베딩 ──▶ Pinecone
                                 │
                                 └─ 변경 없으면 여기서 중단 (비용 절약)

[질의]  질문 ──▶ LangGraph 에이전트 ──▶ Pinecone 검색 ──▶ 답변 (SSE 스트리밍)
```

두 파이프라인은 **프로세스도 분리**되어 있습니다. API 서버가 여러 워커로 뜨면 스케줄러가
중복 실행되므로, 수집 스케줄러는 별도 프로세스(`scheduler.py`)로 띄웁니다.

## 1. 질의 파이프라인 — 순환형 에이전트

일반적인 RAG는 `검색 → 생성` 한 방향입니다. 검색이 엉뚱한 문서를 가져와도 그대로 답을 만듭니다.
이 프로젝트는 **자기 검증 루프**를 넣어 그 실패를 막습니다.

```
contextualize ──▶ router ──▶ retriever ──▶ grader
                                 ▲            │
                                 │            ├─(관련 문서 없음, 재작성 2회 미만)
                                 │            │        │
                                 └── question_rewriter ┘
                                              │
                                              └─(관련 문서 있음 또는 재작성 2회 도달)
                                                       │
                                                       ▼
                                                   generator ──▶ END
```

| 노드 | 역할 |
|---|---|
| `contextualize` | "방금 그거 다시 설명해줘" 같은 후속 질문을 대화 이력으로 독립 문장으로 복원 |
| `router` | 문서 검색 / 웹 검색 분기. 최신성 키워드는 규칙으로 판별 |
| `retriever` | Pinecone 하이브리드 검색 또는 DuckDuckGo |
| `grader` | 검색된 문서가 질문에 답이 되는지 채점. 전체 문서를 한 번의 호출로 묶어 판정 |
| `question_rewriter` | 관련 문서가 없으면 질문을 다른 각도로 재작성해 재검색 |
| `generator` | 최종 답변 생성. 토큰이 만들어지는 즉시 SSE 로 전송 |

**무한 루프 방지**: 재작성이 2회를 넘으면 관련 문서가 없어도 강제로 생성 단계로 넘어갑니다.
없는 답을 지어내는 대신 "모르겠다"고 답하고 끝냅니다.

**대화 기억**: LangGraph 체크포인터(`AsyncSqliteSaver`)가 대화를 SQLite 에 영속화합니다.
SSE 로 응답을 흘리려면 그래프를 비동기로 실행해야 하므로 체크포인터도 비동기 구현을 씁니다.

## 2. 수집 파이프라인 — 변경분만 다시 읽는다

```
load_from_url ──▶ SHA-256 해시 ──▶ SQLite 대조 ──▶ 청킹 ──▶ Pinecone upsert ──▶ 해시 기록
                                        │
                                        └─ 해시 동일하면 스킵
```

**입력 형식별 로더 분기**

| 입력 | 처리 |
|---|---|
| GitHub 레포 | `GitLoader` 로 클론 후 문서 확장자만 추출 (`.md`, `.mdx`, `.rst`, `.txt`) |
| PDF | `PyMuPDFLoader` (페이지 단위) |
| 웹페이지 | `WebBaseLoader` + 본문 이미지 Vision 분석 |
| 주피터 노트북 | JSON 을 파싱해 markdown/code 셀만 추출 (실행 출력은 제거) |

노트북을 원문 그대로 넣으면 실행 결과의 base64 이미지와 트레이스백이 청크를 가득 채워
색인을 오염시킵니다. 그래서 `outputs` 를 버리고 설명과 코드만 남깁니다.
(기본 수집 대상에서는 제외되어 있으며 `GITHUB_INCLUDE_EXT` 로 켤 수 있습니다.)

**청킹**: `RecursiveCharacterTextSplitter`. 일반 텍스트는 500자, 코드 펜스가 포함된 문서는
800자로 나눕니다. 코드는 잘게 쪼개면 문맥이 끊기기 때문입니다.

**벡터 ID 규칙**: `{source_url}_{chunk_index}` 이며 `chunk_index` 는 **수집 배치 전체에서
유일한 일련번호**입니다. GitHub 레포(파일 여러 개)나 PDF(페이지 여러 개)처럼 하나의 URL 에
여러 문서가 딸린 경우, 문서마다 번호를 0부터 다시 매기면 ID 가 충돌해 청크가 서로를 덮어씁니다.

**갱신 방식**: 같은 URL 을 다시 수집하면 기존 벡터를 **전부 지우고 새로 넣습니다**(부분 갱신 아님).
Pinecone Serverless 는 메타데이터 필터 삭제를 지원하지 않으므로, ID prefix 로 대상을 나열해
ID 기반으로 삭제합니다.

## 3. 멀티모달 — 다이어그램을 텍스트로

아키텍처 그림은 정보 밀도가 높지만 벡터 검색으로는 잡히지 않습니다.
웹페이지를 수집할 때 본문의 `<img>` 를 찾아 Gemini Vision 으로 설명문을 만들고
본문 끝에 붙여 함께 임베딩합니다. 그림 안의 내용이 검색 가능해집니다.

비용을 위해 문서당 최대 3개만 분석하고, 5KB 미만 아이콘과 `.svg`/`.gif` 는 건너뜁니다.

## 4. 저장소 — SQLite 두 개, 역할이 다름

| 파일 | 역할 |
|---|---|
| `backend/data/checkpoints.sqlite` | LangGraph 체크포인터. 대화 이력 |
| `backend/data/documents.db` | 수집 장부. URL → 청크 수, 콘텐츠 해시, 시각 |

두 번째가 "변경분만 다시 읽는다"를 가능하게 하는 핵심입니다. Docker 에서는 두 백엔드
컨테이너가 같은 볼륨을 공유해 일관성을 유지합니다.

## 5. 스트리밍

LangGraph 를 `updates` 와 `messages` 두 모드로 동시에 구독합니다.

- `updates` → 노드가 끝날 때마다 **에이전트의 사고 과정**(어디로 라우팅했는지, 문서 몇 개를
  채택했는지)을 `trace` 이벤트로 전송
- `messages` → LLM 이 **토큰을 만드는 즉시** `token` 이벤트로 전송

사용자는 답을 기다리는 동안 에이전트가 무엇을 하고 있는지 볼 수 있습니다.

## 6. 복원력

| 상황 | 대응 |
|---|---|
| Pinecone/Gemini 통신 실패 | Tenacity 지수 백오프 재시도 3회 |
| SSE 연결 끊김 | 프론트엔드 백오프 재연결 (서버가 보낸 에러는 재시도하지 않음) |
| 수집 실패 | Slack 웹훅 알림 |
| 인덱스 메트릭 불일치 | 자동 삭제 대신 명확한 에러로 중단 (환경변수로만 재생성 허용) |

## 알려진 한계

**하이브리드 검색의 sparse 절반이 제 역할을 못 합니다.** `BM25Encoder().default()` 는
영어 코퍼스로 사전 학습된 IDF 파라미터를 쓰기 때문에 한국어 문서에서는 기여가 거의 없습니다.
제대로 쓰려면 실제 코퍼스로 학습한 파라미터를 색인 시점과 질의 시점에 동일하게 유지하는
영속화 계층이 필요합니다. 향후 과제로 남겨두었습니다.

---

# 실행 가이드

## 환경 변수

`backend/.env` 파일을 만들고 채웁니다.

```env
# --- 필수 ---
GOOGLE_API_KEY=your_gemini_api_key
PINECONE_API_KEY=your_pinecone_api_key
PINECONE_INDEX_NAME=techdoc

# --- 선택: 수집 실패 알림 ---
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# --- 선택: GitHub 레포 수집 시 rate limit 완화 ---
GITHUB_TOKEN=your_github_token

# --- 선택: 임베딩 디바이스 (cpu | mps | cuda | auto) ---
EMBEDDING_DEVICE=cpu

# --- 선택: 수집 대상 ---
GITHUB_INCLUDE_EXT=.md,.mdx,.rst,.txt        # .ipynb 를 추가하면 노트북도 수집
GITHUB_MD_EXCLUDE=node_modules,dist,build,.github,venv,site-packages,CHANGELOG

# --- 선택: LLM 호출 예산 ---
ROUTER_USE_LLM=false           # true 면 라우팅에 LLM 을 1회 더 사용
HISTORY_WINDOW=6               # contextualize 에 넘길 최근 메시지 수

# --- 선택: 리랭커 (기본 비활성) ---
RERANKER_ENABLED=false
RERANKER_DEVICE=cpu
RERANKER_CANDIDATES=10
RETRIEVER_TOP_K=4

# --- 선택: CORS (프론트를 다른 출처에서 띄울 때만) ---
CORS_ORIGINS=http://localhost,http://localhost:5173

# --- 선택: LangSmith ---
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_api_key
LANGCHAIN_PROJECT=TechDoc-Agent
```

> LLM 키의 환경변수 이름은 `GOOGLE_API_KEY` 입니다 (`backend/config.py` 기준).

> Gemini 무료 티어에는 분당·일일 호출 한도가 있습니다. 이 에이전트는 질문 하나에
> LLM 을 2~3회 호출하므로, 연속 대화를 하려면 결제 활성화를 권장합니다.

> 기존 Pinecone 인덱스의 메트릭이 `cosine` 이면 하이브리드 검색을 쓸 수 없습니다.
> 이 경우 서버는 인덱스를 지우는 대신 에러를 내고 멈춥니다.
> 삭제 후 `dotproduct` 로 재생성하려면 `PINECONE_ALLOW_INDEX_RECREATE=true` 를 설정하세요.
> **기존 벡터가 모두 사라지므로 문서 재수집이 필요합니다.**

## 로컬 실행

API 서버와 스케줄러는 **반드시 분리해서** 띄웁니다. 터미널 3개를 사용합니다.

```bash
# 최초 1회
python -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

```bash
# 터미널 1 — API 서버
source venv/bin/activate && cd backend
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# 터미널 2 — 야간 수집 스케줄러 (매일 03:00)
source venv/bin/activate && cd backend
python scheduler.py

# 터미널 3 — 프론트엔드
cd frontend && npm install && npm run dev
```

Vite 개발 서버가 `/api` 요청을 `localhost:8000` 으로 프록시하므로 CORS 설정이 필요 없습니다.

> 첫 실행 시 임베딩 모델(BAAI/bge-m3, 약 4.3GB)을 내려받습니다.

## Docker 실행

```bash
docker compose up -d --build
```

백엔드 API · 스케줄러 · 프론트엔드(Nginx) 세 컨테이너가 함께 뜹니다.
완료 후 `http://localhost` 로 접속하세요. API 경로는 Nginx 가 프록시합니다.

- `backend-data` 볼륨 — SQLite 두 개를 백엔드 컨테이너가 공유
- `hf-cache` 볼륨 — 임베딩 모델 가중치 공유. 없으면 컨테이너마다, 재빌드마다 4.3GB 를 다시 받습니다

---

# API

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/api/stream?q=<질문>&thread_id=<세션ID>` | SSE 스트리밍 응답 |
| `POST` | `/api/ingest` | 문서 수집 (`{"url": "..."}`) |
| `GET` | `/api/docs` | 수집된 문서 목록 |
| `DELETE` | `/api/docs?url=<URL>` | 문서 삭제 (Pinecone 벡터 + SQLite 기록) |
| `GET` | `/api/health` | 헬스체크 |

**SSE 이벤트**

| 이벤트 | 내용 |
|---|---|
| `trace` | 노드 실행 로그 (라우팅 결정, 채택 문서 수 등) |
| `chunk` | 검색된 문서 |
| `token` | 생성 토큰 |
| `sources` | 출처 URL |
| `done` / `error` | 종료 / 오류 |

프론트엔드는 브라우저마다 세션 ID 를 만들어 `localStorage` 에 보관하고 `thread_id` 로
전달합니다. 방문자별로 대화 맥락이 분리됩니다.
