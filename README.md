<div align="center">

# TechDoc Agent

**기술 문서를 검색해 답하고, 자신의 검색 결과를 스스로 검증하는 RAG 챗봇**

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?logo=langchain&logoColor=white)
![React](https://img.shields.io/badge/React-61DAFB?logo=react&logoColor=black)
![Pinecone](https://img.shields.io/badge/Pinecone-000000?logo=pinecone&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)

</div>

<!-- 스크린샷을 넣으려면 docs/screenshot.png 에 두고 아래 줄의 주석을 해제하세요.
![screenshot](docs/screenshot.png)
-->

---

일반적인 RAG 는 `검색 → 생성` 한 방향입니다. 검색이 엉뚱한 문서를 가져와도
모델은 그 문서를 **성실하게 요약합니다.** 근거가 틀렸다는 걸 알 방법이 없기 때문입니다.

이 프로젝트는 그 지점에 **검증 단계와 되돌아가는 경로**를 넣었습니다.

```
검색 → 채점 → (관련 없음) → 질문 재작성 → 재검색 → 생성
                                              ↑ 최대 2회, 그래도 없으면 "모르겠다"
```

### 이 프로젝트의 핵심 3가지

| | |
|---|---|
| **자기 검증 루프** | 검색 결과를 채점하고, 틀렸으면 질문을 고쳐 다시 검색 |
| **LLM 호출 최적화** | 질문당 채점 호출을 **4회 → 1회**로 압축 (배치 채점) |
| **측정 기반 의사결정** | 개선 8건 시도 → **6건을 데이터로 기각**하고 되돌림 |

<br>

## 목차

[1. 개요](#1-개요) · [2. 구현 목적](#2-구현-목적) · [3. 사용 스택](#3-사용-스택) · [4. 아키텍처](#4-아키텍처-설명) · [5. 개선사항](#5-개선사항) · [6. 한계](#6-한계) · [7. 사용 방법](#7-clone-후-사용-방식)

---

## 1. 개요

GitHub 레포·PDF·웹페이지의 기술 문서를 수집해 색인하고, 자연어 질문에 **근거를 들어** 답합니다.

답변은 토큰이 만들어지는 즉시 흐르고, 그 위에 에이전트가 지금 무엇을 하는지 함께 표시됩니다.

### 일반 RAG 와 다른 점 2가지

**① 검색 결과를 그대로 믿지 않습니다**

가져온 문서가 질문에 답이 되는지 채점합니다. 아니면 질문을 다른 각도로 고쳐 다시 검색합니다.
그래도 근거가 없으면 **지어내지 않고 "모르겠다"고 답합니다.**

**② 넣기 전에 무엇이 들어갈지 보여줍니다**

레포에는 문서 외에 테스트 픽스처·자동 생성 API 레퍼런스·마케팅 문구가 섞여 있습니다.
그대로 색인하면 검색이 그 문구를 물어옵니다.
`GET /api/ingest/preview` 로 **임베딩 전에** 대상 파일 수·청크 수를 확인할 수 있습니다.

---

## 2. 구현 목적

> **기술 문서 질의응답에서 환각(hallucination)을 프롬프트가 아니라 구조로 막는다.**

"모르면 모른다고 하라"는 지시만으로는 부족합니다.
**검색 단계가 이미 틀린 문서를 건네주면, 모델은 그 틀린 문서를 성실하게 요약합니다.**

그래서 검색과 생성 사이에 검증 단계를 두고, 실패했을 때 되돌아가는 경로를 만들었습니다.

### 설계 원칙 2가지

| 원칙 | 의미 |
|---|---|
| **자기 검증** | 검색 → 채점 → 재작성 → 재검색. 근거 없으면 명시적 포기 |
| **측정 후 채택** | 개선은 정량 측정으로 검증하고, 효과 없으면 **되돌린다** |

두 번째 원칙 때문에 시도한 개선의 **75%가 기각**됐습니다. → [6.5 측정해서 기각한 것들](#65-측정해서-기각한-것들)

---

## 3. 사용 스택

| 영역 | 선택 | 선택 이유 |
|---|---|---|
| **LLM** | Google Gemini 2.5 Flash (Vision 포함) | 멀티모달 — 다이어그램 설명문화에 사용 |
| **Embedding** | BAAI/bge-m3 (로컬, 1024차원) | 한·영 교차언어 검색 지원 |
| **Vector DB** | Pinecone Serverless | 관리형 — 인프라 운영 부담 없음 |
| **Reranker** (선택) | BAAI/bge-reranker-v2-m3 | 정확도 +7.4%p — 단 GPU 필요 |
| **Agent** | LangGraph & LangChain | **순환 그래프**가 필요 (재작성 루프) |
| **Backend** | FastAPI, SQLite | 비동기 SSE + 의존성 없는 영속화 |
| **Frontend** | React + Vite, EventSource | 토큰 단위 스트리밍 수신 |
| **Deployment** | Docker Compose, Nginx | 단일 명령 재현 |
| **Observability** | LangSmith (선택) | 노드별 추적 |

> LangGraph 를 고른 이유는 **순환 구조** 때문입니다.
> 일반적인 체인(DAG)으로는 "채점 실패 → 이전 단계로 되돌아가기"를 표현할 수 없습니다.

> UI 출처: https://www.designprompts.dev/ 프롬프트 참조

---

## 4. 아키텍처 설명

### 4.1 두 개의 독립 파이프라인

```
[수집]  URL ──▶ 로더 ──▶ 해시 검사 ──▶ 청킹 ──▶ 임베딩 ──▶ Pinecone
                            │
                            └─ 변경 없으면 여기서 중단

[질의]  질문 ──▶ LangGraph 에이전트 ──▶ Pinecone 검색 ──▶ 답변 (SSE 스트리밍)
```

수집은 `POST /api/ingest` 로 **명시적으로** 실행합니다. 스케줄러는 없습니다.

### 4.2 질의 파이프라인 — 순환형 에이전트

```
contextualize ──▶ retriever ──▶ grader
                      ▲            │
                      │            ├─(관련 문서 없음, 재작성 2회 미만)
                      │            │            │
                      └── question_rewriter ────┘
                                                │
                                   (관련 문서 있음 또는 재작성 2회 도달)
                                                │
                                                ▼
                                            generator ──▶ END
```

| 노드 | 역할 |
|---|---|
| `contextualize` | "방금 그거 다시 설명해줘" → 독립 문장으로 복원 |
| `retriever` | Pinecone dense 검색 |
| `grader` | 문서가 질문에 답이 되는지 채점 — **전체를 1회 호출로** 묶어 판정 |
| `question_rewriter` | 관련 문서가 없으면 질문을 다른 각도로 재작성 |
| `generator` | 답변 생성. 토큰이 만들어지는 즉시 SSE 전송 |

**무한 루프 방지** — 재작성 2회를 넘으면 관련 문서가 없어도 생성 단계로 넘어갑니다.
없는 답을 지어내는 대신 "모르겠다"고 답하고 끝냅니다.

<details>
<summary><b>대화 기억 · 검색 범위</b></summary>

<br>

LangGraph 체크포인터(`AsyncSqliteSaver`)가 대화를 SQLite 에 영속화합니다.
SSE 로 응답을 흘리려면 그래프를 비동기로 실행해야 하므로 체크포인터도 비동기 구현을 씁니다.

프롬프트가 무한히 커지지 않도록 최근 `HISTORY_WINDOW` 개 메시지만 넘깁니다.

검색은 **색인된 문서만** 사용합니다. 웹 검색 경로는 없습니다.

</details>

### 4.3 수집 파이프라인 — 변경분만 다시 읽는다

```
load_from_url ──▶ SHA-256 해시 ──▶ SQLite 대조 ──▶ 청킹 ──▶ upsert ──▶ 해시 기록
                                       │
                                       └─ 해시 동일하면 스킵
```

| 입력 | 처리 |
|---|---|
| GitHub 레포 | `--depth 1` 얕은 클론 후 문서 확장자만 추출 |
| PDF | `PyMuPDFLoader` (페이지 단위) |
| 웹페이지 | `WebBaseLoader` + 본문 이미지 Vision 분석 |
| 주피터 노트북 | markdown/code 셀만 추출 (실행 출력 제거) |

**청킹** — 일반 텍스트 500자, 코드 펜스 포함 문서 800자.

<details>
<summary><b>깊이 보기 — 벡터 ID 충돌, 부분 실패 처리, 문서별 필터</b></summary>

<br>

**벡터 ID 규칙**

`{source_url}_{chunk_index}` 이며 `chunk_index` 는 **수집 배치 전체에서 유일한 일련번호**입니다.

GitHub 레포(파일 여러 개)나 PDF(페이지 여러 개)처럼 하나의 URL 에 여러 문서가 딸린 경우,
문서마다 번호를 0부터 다시 매기면 ID 가 충돌해 청크가 서로를 덮어씁니다.

**갱신 방식**

같은 URL 을 다시 수집하면 기존 벡터를 전부 지우고 새로 넣습니다(부분 갱신 아님).
Pinecone Serverless 는 메타데이터 필터 삭제를 지원하지 않으므로 ID prefix 로 나열해 삭제합니다.

**적재 방식 — 64청크 배치별 독립 처리**

전체를 한 번에 넘기면 중간에 한 번 실패했을 때 앞서 끝낸 작업까지 버립니다.
배치별로 나누면 실패한 배치만 재시도하면 되고, 실패 원인도 로그에 남습니다.

일부 배치가 끝내 실패하면 결과가 `partial` 이 되고 **콘텐츠 해시를 기록하지 않습니다.**
해시를 남기면 다음 수집이 "변경 없음"으로 건너뛰어 **불완전한 색인이 영구히 남기 때문**입니다.

**수집 필터는 문서마다 따로 저장됩니다**

버려야 할 경로는 레포마다 다릅니다 (vLLM 은 `rust/`·`fixtures/`, Prefect 는 `api-ref/`·`plans/`).

필터가 전역 설정 하나뿐이면, 다른 레포를 넣으려고 설정을 바꾼 뒤 기존 문서를
**바뀐 필터로** 재수집해 색인을 조용히 망가뜨립니다.

| 순위 | 필터 출처 | 언제 |
|---|---|---|
| 1 | 요청 본문의 `include_ext` / `exclude_paths` | 새 레포를 넣을 때 |
| 2 | 그 문서가 이전에 사용한 필터 | 같은 URL 재수집 |
| 3 | 전역 설정 (`.env`) | 위 둘이 없을 때 |

덕분에 레포를 추가할 때 `.env` 를 고칠 필요가 없습니다.

**노트북 처리**

원문 그대로 넣으면 실행 결과의 base64 이미지와 트레이스백이 청크를 채워 색인을 오염시킵니다.
그래서 `outputs` 를 버리고 설명과 코드만 남깁니다.
기본 대상에서 제외되어 있으며 `GITHUB_INCLUDE_EXT` 에 `.ipynb` 를 추가하면 켜집니다.

</details>

### 4.4 멀티모달 — 다이어그램을 텍스트로

아키텍처 그림은 정보 밀도가 높지만 **벡터 검색으로는 잡히지 않습니다.**

웹페이지 수집 시 본문의 `<img>` 를 Gemini Vision 으로 설명문화해 본문 끝에 붙여
함께 임베딩합니다. 그림 안의 내용이 검색 가능해집니다.

비용을 위해 문서당 최대 3개, 5KB 미만 아이콘과 `.svg`/`.gif` 는 제외합니다.

### 4.5 스트리밍

LangGraph 를 두 모드로 **동시 구독**합니다.

| 모드 | 전송 내용 |
|---|---|
| `updates` | 노드가 끝날 때마다 진행 상황 (`trace` 이벤트) |
| `messages` | LLM 이 토큰을 만드는 즉시 (`token` 이벤트) |

사용자는 답을 기다리는 동안 에이전트가 무엇을 하고 있는지 볼 수 있습니다.

<details>
<summary><b>저장소 · 복원력 · API 레퍼런스</b></summary>

<br>

**SQLite 두 개, 역할이 다름**

| 파일 | 역할 |
|---|---|
| `checkpoints.sqlite` | LangGraph 체크포인터. 대화 이력 |
| `documents.db` | 수집 장부. URL → 청크 수, 해시, 필터, 시각 |

두 번째가 "변경분만 다시 읽는다"를 가능하게 하는 핵심입니다.

**복원력**

| 상황 | 대응 |
|---|---|
| 적재 배치 실패 | 해당 배치만 재시도. 앞선 배치는 보존 |
| 일부 배치 최종 실패 | `partial` + 해시 미기록 → 다음 실행에서 재시도 |
| Gemini 통신 실패 | 클라이언트 레벨 재시도 3회 |
| SSE 연결 끊김 | 백오프 재연결 (서버가 보낸 에러는 재시도 안 함) |

**API**

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/api/stream?q=&thread_id=` | SSE 스트리밍 응답 |
| `POST` | `/api/ingest` | 수집. `status`: `ok`/`partial`/`error` |
| `GET` | `/api/ingest/preview?url=` | 수집 전 미리보기 (임베딩 없음) |
| `GET` | `/api/docs` | 수집된 문서 목록 |
| `DELETE` | `/api/docs?url=` | 문서 삭제 (벡터 + 기록) |
| `GET` | `/api/health` | 헬스체크 |

```jsonc
POST /api/ingest
{
  "url": "https://github.com/vllm-project/vllm",
  "include_ext": ".md,.mdx",                    // 생략 시 저장된 필터 → 전역 설정
  "exclude_paths": "rust/,fixtures/,api-ref"    // 경로에 이 조각이 있으면 건너뜀
}
```

**SSE 이벤트** — `trace` / `chunk` / `token` / `sources` / `done` / `error`

프론트엔드는 브라우저마다 세션 ID 를 만들어 `localStorage` 에 보관하고 `thread_id` 로
전달합니다. 방문자별로 대화 맥락이 분리됩니다.

</details>

---

## 5. 개선사항

> 모든 항목은 **실측 후** 채택했습니다.

### 한눈에 보기

| 항목 | Before | After |
|---|---|---|
| **질문당 채점 호출** | 4회 | **1회** |
| **contextualize LLM 호출** | 100% | **60%** (규칙으로 선처리) |
| **정답 문서 포함률** | 90.7% | **92.6%** |
| **부정확한 출처 중복 출력** | 5/5 | **0/5** |

### 5.1 LLM 호출 최적화

LLM 호출은 응답 지연과 비용에 직결됩니다. 노드를 늘려 정확도를 얻는 구조이므로,
**질문당 호출 수를 줄이는 것이 가장 효과가 큽니다.**

| 조치 | 효과 |
|---|---|
| 문서별 채점 → 전체를 묶어 **1회 배치 채점** | 질문당 4회 → **1회** |
| 후속 질문 판별을 규칙으로 선처리 (지시대명사·생략 표현) | contextualize 호출 **-40%** |
| 규칙 기반 분기로 라우팅 LLM 제거 | 질문당 **-1회** |

현재 질문 하나에 LLM 을 **2~7회** 호출합니다.
검색이 한 번에 통과하면 2~3회, 재작성·재검색이 두 번 일어나면 최대 7회입니다.

### 5.2 검색 품질

| 조치 | 효과 |
|---|---|
| `retriever_top_k` 4 → 5 | 정답 문서 포함률 90.7% → **92.6%** |
| 임베딩 정규화 | `dotproduct == cosine` 성립 → 인덱스 재생성 불필요 |
| 임베딩 모델 **revision 고정** | 색인이 조용히 깨지는 경로 차단 |

> **세 번째가 특히 중요합니다.** 모델 버전을 고정하지 않으면 캐시 무효화 시 새 가중치를
> 받아오고, 이미 색인된 벡터와 새 질의 벡터가 **서로 다른 공간**에 놓입니다.
> 예외가 발생하지 않고 정확도만 조용히 떨어져 발견이 매우 어렵습니다.

### 5.3 응답 품질·속도

| 조치 | 효과 |
|---|---|
| 답변에 출처 목록을 붙이라는 지시 제거 | 부정확한 중복 출력 **5/5 → 0/5** |
| `generator` 를 `astream()` 으로 호출 | 토큰 단위 실시간 스트리밍 |
| 재작성 결과 후처리 | 재작성문이 검색 질의를 오염시키는 문제 해결 |

첫 항목은 UI 가 이미 출처 칩을 렌더링하는데 모델이 `Sources: * Paged Attention` 같은
목록을 덧붙이던 문제입니다. **파일명도 URL 도 아닌 값**이라 중복이자 오류였습니다.

### 5.4 수집 안정성

| 조치 | 효과 |
|---|---|
| 64청크 배치별 독립 적재 | 부분 실패 시 앞선 배치 보존 |
| 실패 시 해시 미기록 | 불완전한 색인이 영구화되지 않음 |
| 문서별 필터 저장 | 레포 추가가 기존 색인을 망가뜨리지 않음 |
| 수집 전 미리보기 | 잘못된 레포를 몇 분씩 색인하는 사고 방지 |

<details>
<summary><b>하이브리드 검색을 걷어낸 이유</b></summary>

<br>

초기에는 Dense + Sparse(BM25) 하이브리드를 썼으나 **Dense 단독과 차이가 없었습니다.**

`BM25Encoder().default()` 가 영어 코퍼스로 사전 학습된 IDF 를 쓰기 때문에
한국어 문서에서는 기여가 없었습니다.

게다가 코드 블록만 있는 청크는 영어 토크나이저가 토큰을 잡지 못해 **빈 희소 벡터**가 되고,
Pinecone 이 이를 거부해 적재 실패의 원인이 되기도 했습니다.

**이득이 0인데 실패 모드만 추가하는 구성**이라 제거했습니다.

</details>

---

## 6. 한계

### 6.1 CPU 추론 — 리랭커를 켤 수 없음

리랭커는 구현되어 있고 효과도 실측됐습니다.

| | |
|---|---|
| Recall@1 | **+7.4%p** (실재) |
| CPU 지연 | **최대 18.3초/질문** ← 여기서 막힘 |

사전에 정한 채택 기준(지연 +7초 이하)을 **2.6배 초과**해 기본 비활성입니다.
GPU 환경이라면 `RERANKER_ENABLED=true` 로 켜는 것을 권장합니다.

### 6.2 이중언어 요구와 BM25 의 충돌

남은 검색 실패의 원인은 일관됩니다.

> `@task` 같은 표현이 조밀하게 반복되는 **예제 문서**가,
> 개념을 서술하는 문서를 dense 임베딩상 더 가깝게 보이게 만든다.

dense 검색의 교과서적 약점이고 교과서적 해법은 BM25 하이브리드입니다.
그러나 **BM25 는 교차언어 능력이 없어**, 한국어 질문으로 영어 문서를 찾는 이 시스템의
핵심 요구와 구조적으로 충돌합니다. 절충안이 없습니다.

### 6.3 재색인 비용

```
7,700청크 × 0.381초 ≈ 50분 (이론)   실측 76~92분
```

증분 재색인이 없어 **청킹 실험을 반복하기 어렵습니다.**

### 6.4 검색 범위

- **웹 검색 없음** — 색인된 문서에만 근거합니다. 최신 정보는 답하지 못합니다.
- **주피터 노트북 기본 제외** — 포함 시 수집량이 10배 가까이 늘어납니다
  (langgraph 레포 기준 109청크 → 약 1,050청크).

### 6.5 측정해서 기각한 것들

**시도 8건 중 6건이 데이터로 기각됐습니다.** 같은 시도를 반복하지 않기 위해 남깁니다.

| 시도 | 기각 사유 |
|---|---|
| BM25 하이브리드 | 한국어 Recall@1 **14.8%** — 교차언어 능력 없음 |
| 소스 메타데이터 필터 | **0.0%p** — 임베딩이 이미 도메인을 100% 분리 |
| 리랭커 상시 적용 | Recall@1 +7.4%p, 그러나 CPU **18.3초** |
| 인접 청크 확장 | 정답이 **21~33청크** 떨어져 있어 닿지 않음 |
| 코드펜스 청크 크기 분기 제거 | 판별 구간에서 **차이 0**, 청크 수만 +57% |
| `retriever_top_k` 8 로 확대 | k=5 와 k=8 결과가 **동일** |
| 후보 30개 + 채점기 재정렬 | 정답 생존 **2/4**, 채점 지연 14.8초 |

---

## 7. clone 후 사용 방식

### 빠른 시작

```bash
git clone <이 저장소> && cd techdoc-agent

# backend/.env 를 만들고 API 키 2개를 채웁니다 (→ 7.2)
docker compose up -d --build
```

→ **http://localhost** 접속 → **Docs** 탭에서 문서 수집 → **Chat** 탭에서 질문

### 7.1 사전 준비

| 필요한 것 | 발급처 |
|---|---|
| Gemini API 키 | https://aistudio.google.com/apikey |
| Pinecone API 키 | https://app.pinecone.io |
| GitHub 토큰 (선택) | rate limit 완화용 |

### 7.2 환경 변수

`backend/.env` 파일을 만들고 채웁니다.

```env
# --- 필수 ---
GOOGLE_API_KEY=your_gemini_api_key
PINECONE_API_KEY=your_pinecone_api_key
PINECONE_INDEX_NAME=techdoc

# --- 선택 ---
GITHUB_TOKEN=your_github_token
EMBEDDING_DEVICE=cpu                  # cpu | mps | cuda | auto

# 수집 대상
GITHUB_INCLUDE_EXT=.md,.mdx,.rst,.txt
GITHUB_MD_EXCLUDE=node_modules,dist,build,.github,venv,site-packages,CHANGELOG

# 검색 / 리랭커
RETRIEVER_TOP_K=5
RERANKER_ENABLED=false                # GPU 환경이면 true 권장
RERANKER_DEVICE=cpu
RERANKER_CANDIDATES=10

# 대화 이력
HISTORY_WINDOW=6                      # contextualize 에 넘길 최근 메시지 수

# CORS (프론트를 다른 출처에서 띄울 때만)
CORS_ORIGINS=http://localhost,http://localhost:5173

# LangSmith
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_api_key
LANGCHAIN_PROJECT=TechDoc-Agent
```

> LLM 키의 환경변수 이름은 **`GOOGLE_API_KEY`** 입니다 (`backend/config.py` 기준).

> Pinecone 인덱스가 없으면 `dotproduct` · 1024차원으로 자동 생성합니다.
> 임베딩을 정규화해서 넣으므로 `dotproduct` 와 `cosine` 결과가 같습니다.

### 7.3 실행 — Docker (권장)

```bash
docker compose up -d --build
```

`backend-api`(8000) 와 `frontend`(Nginx, 80) 두 컨테이너가 뜹니다.
**http://localhost** 로 접속하세요. API 경로는 Nginx 가 프록시합니다.

| 볼륨 | 용도 |
|---|---|
| `backend-data` | SQLite 두 개 (대화 이력 · 수집 장부) |
| `hf-cache` | 임베딩 모델 가중치(약 4.3GB). 없으면 재빌드마다 다시 받음 |

실측 메모리: `backend-api` **830MB**, `frontend` 8MB → **Docker 메모리 3GB 이상 할당**

### 7.4 실행 — 로컬 개발

<details>
<summary><b>터미널 2개로 실행하기</b></summary>

<br>

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

# 터미널 2 — 프론트엔드
cd frontend && npm install && npm run dev
```

Vite 개발 서버가 `/api` 요청을 `localhost:8000` 으로 프록시하므로 CORS 설정이 필요 없습니다.

> 첫 실행 시 임베딩 모델(BAAI/bge-m3)을 내려받습니다. 네트워크에 따라 수 분 걸립니다.

</details>

### 7.5 문서 수집

UI 의 **Docs** 탭에서 진행합니다.

1. 레포 URL 입력 → **Preview** — 대상 파일 수·청크 수를 **임베딩 없이** 확인
2. 청크 수가 예상과 다르면 `exclude_paths` 로 노이즈 경로를 걸러냅니다
3. **Ingest** 로 실제 수집 — 예상 시간은 `청크 수 × 약 0.4초`

<details>
<summary><b>CLI 로 수집하기</b></summary>

<br>

```bash
# 미리보기
curl "http://localhost:8000/api/ingest/preview?url=https://github.com/vllm-project/vllm"

# 수집
curl -X POST http://localhost:8000/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"url":"https://github.com/vllm-project/vllm","exclude_paths":"rust/,fixtures/"}'
```

</details>

### 7.6 질문

**Chat** 탭에서 질문합니다.
답변이 토큰 단위로 흐르고, 그 위에 에이전트의 진행 상황이 표시됩니다.
답변 아래에는 근거로 사용한 문서가 **출처 칩**으로 나타납니다.

### 7.7 종료

```bash
docker compose down          # 볼륨 보존
docker compose down -v       # 색인 캐시·대화 이력까지 삭제
```
