# TechDoc Agent

## 📌 프로젝트 개요 (Overview)
TechDoc Agent는 개발자를 위한 **클라우드 네이티브 기반 자율형 RAG(Retrieval-Augmented Generation) 챗봇 시스템**입니다. 
단순한 일회성 검색을 넘어, 백그라운드에서 스케줄러가 스스로 문서를 크롤링하고 지문(Hash)을 분석하여 Pinecone(벡터 DB)을 최신화하는 **100% 무인 데이터 자동화 파이프라인**을 갖추고 있습니다.

## 🛠 사용 스택 (Tech Stack)

### Backend & AI (API Layer)
- **LLM**: Google **Gemini 2.5 Flash** (강력하고 빠른 생성형 AI 모델)
- **Embedding**: HuggingFace (`BAAI/bge-m3`) - 고성능 오픈소스 다국어 임베딩
- **Vector DB**: **Pinecone** (클라우드 네이티브 벡터 스토어)
- **Agent Framework**: LangGraph (StateGraph 기반 자율 반성 로직) & LangChain
- **Automation**: `APScheduler` (무인 스케줄링) & `SQLite` (문서 추적 명부)
- **Web Framework**: FastAPI (SSE 실시간 스트리밍 지원)

### Frontend (UI/UX Layer)
- **Framework**: React + Vite + `react-router-dom` (SPA 아키텍처)
- **Styling**: Vanilla CSS (글래스모피즘 & 스페이스 다크 테마 적용)
- **Integration**: EventSource API (스트리밍 타이핑 효과) 및 지수 백오프(Exponential Backoff) 재연결

## 🚀 핵심 아키텍처 및 구현 기능

### 1. 무인 데이터 자동화 파이프라인 (Automated Ingestion)
- **명부 추적 (Source Tracker)**: `/docs`에서 입력된 URL과 전체 텍스트의 고유 지문(`SHA-256 Hash`)을 로컬 SQLite(`documents.db`)에 영구 기록합니다.
- **스마트 해시 스킵 (Smart Hash Skip)**: 매일 새벽 3시 `APScheduler`가 문서를 다시 긁어왔을 때, 기존 지문과 100% 일치하면 Pinecone 업데이트를 건너뛰어(Skip) API 연산 비용을 아낍니다.
- **실시간 에러 관제 (Slack Alerting)**: 크롤링 중 웹사이트 폐쇄(404) 등의 에러가 발생하면 멈추지 않고 즉시 관리자의 **Slack 채널로 웹훅(Webhook) 알림**을 발송합니다.

### 2. 자율 반성 RAG 에이전트 (Self-Reflective RAG)
단순 검색에 의존하지 않고 LangGraph를 활용해 **검색 ➡️ 문서 평가(Grader) ➡️ 질문 재작성(Rewriter) ➡️ 최종 답변(Generator)**의 다단계 심화 추론 루프를 거쳐 할루시네이션(거짓 정보)을 원천 차단합니다.

### 3. 장애 복원력 (Resilience)
네트워크 불안정으로 인해 Pinecone 통신이나 Gemini API 호출이 실패하더라도, `Tenacity`를 활용해 자동으로 N회 재시도(Retry)하여 시스템이 뻗지 않도록 튼튼하게 설계되었습니다.

---

## 🔮 추후 구현 계획 (Future Work)

1. **대화 맥락 기억 (Conversation Memory)**: 단발성 질문을 넘어 "아까 네가 작성해준 코드 다시 보여줘"와 같은 과거 맥락 기반의 대화 기능(SQLite 메모리 누적) 탑재 예정.
2. **관리자 페이지 보안 (Auth)**: `/docs` 엔드포인트 무단 접근 및 데이터 삭제 방지를 위한 JWT 또는 PIN 코드 기반의 보안 잠금장치 추가.
3. **클라우드 실전 배포 (Cloud Deployment)**: 현재 로컬 환경에서 구동되는 서버를 Vercel(Frontend) 및 Render/Fly.io(Backend)로 이전하여 누구나 접근 가능한 상용 서비스화 예정.
4. **딥 크롤링 (Deep Crawling)**: 단일 URL을 넘어 사이트맵(Sitemap)이나 재귀적(Recursive) 방식의 문서 싹쓸이 자동 탐색 엔진 도입.

---

## 💻 실행 가이드 (How to Run)

### 1. 백엔드 세팅
```bash
cd backend
python -m venv venv
source venv/bin/activate  # (Windows: venv\Scripts\activate)
pip install -r requirements.txt
```

### 2. 환경 변수 설정 (`.env`)
루트 디렉토리에 `.env` 파일을 만들고 아래 필수 키들을 입력하세요.
```env
GEMINI_API_KEY=your_gemini_api_key_here
PINECONE_API_KEY=your_pinecone_api_key_here
PINECONE_INDEX_NAME=your_pinecone_index_name
SLACK_WEBHOOK_URL=your_slack_webhook_url_here  # 에러 알림용 (선택)
```

### 3. 서버 구동
백엔드 서버 켜기 (새벽 3시 스케줄러 자동 동작):
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

새 터미널에서 프론트엔드 구동:
```bash
cd frontend
npm install
npm run dev
```

브라우저에서 `http://localhost:5173` 으로 접속하세요!
