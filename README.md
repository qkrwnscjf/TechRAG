# TechDoc Agent

## 프로젝트 개요
TechDoc Agent는 개발자를 위한 클라우드 네이티브 기반 자율형 RAG 챗봇 시스템임.
스케줄러가 스스로 문서를 크롤링하고 지문(Hash)을 분석하여 Pinecone 벡터 DB를 최신화하는 100% 무인 데이터 자동화 파이프라인을 갖춤.

## 사용 스택

### Backend & AI
- LLM: Google Gemini 2.5 Flash
- Embedding: HuggingFace (BAAI/bge-m3)
- Vector DB: Pinecone
- Agent Framework: LangGraph & LangChain
- Automation: APScheduler & SQLite
- Web Framework: FastAPI

### Frontend
- Framework: React + Vite + react-router-dom
- Styling: Vanilla CSS
- Integration: EventSource API 및 지수 백오프 재연결
- UI 출처: 초기 제공된 UI 프롬프트 및 커스텀 글래스모피즘 디자인 시스템 참고

## 핵심 아키텍처 및 구현 기능

### 1. 무인 데이터 자동화 파이프라인
- 명부 추적: 입력된 URL과 전체 텍스트의 고유 지문(SHA-256)을 로컬 SQLite에 영구 기록.
- 스마트 해시 스킵: 매일 새벽 3시 APScheduler가 문서를 긁어와 기존 지문과 일치하면 Pinecone 업데이트를 건너뜀(API 비용 절감).
- 실시간 에러 관제: 크롤링 중 에러 발생 시 Slack 웹훅 알림 발송.

### 2. 자율 반성 RAG 에이전트
검색 -> 문서 평가(Grader) -> 질문 재작성(Rewriter) -> 최종 답변(Generator)의 다단계 추론 루프를 거쳐 할루시네이션 원천 차단.

### 3. 장애 복원력
Pinecone 통신이나 Gemini API 호출 실패 시, Tenacity를 활용해 자동으로 재시도하도록 설계.

## 추후 구현 계획
1. 대화 맥락 기억: 과거 맥락 기반의 대화 기능(SQLite 메모리 누적) 추가.
2. 관리자 페이지 보안: /docs 엔드포인트 접근 차단을 위한 인증 로직 추가.
3. 클라우드 배포: Vercel(Frontend) 및 Render(Backend)로 이전하여 상용 서비스화.
4. 딥 크롤링: 사이트맵이나 재귀적 방식의 문서 자동 탐색 엔진 도입.

## 실행 가이드

### 1. 백엔드 세팅
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 환경 변수 설정
루트 디렉토리에 `.env` 파일 생성 후 필수 키 입력.
```env
GEMINI_API_KEY=your_gemini_api_key_here
PINECONE_API_KEY=your_pinecone_api_key_here
PINECONE_INDEX_NAME=your_pinecone_index_name
SLACK_WEBHOOK_URL=your_slack_webhook_url_here
```

### 3. 서버 구동
백엔드 서버 실행 (새벽 3시 스케줄러 자동 동작):
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

프론트엔드 구동:
```bash
cd frontend
npm install
npm run dev
```

브라우저에서 http://localhost:5173 접속.
