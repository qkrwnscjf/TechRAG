// 상대경로가 기본값이다.
//  - 개발: vite.config.js 의 server.proxy 가 /api -> localhost:8000 으로 넘긴다.
//  - 운영: frontend/nginx.conf 의 location /api/ 가 backend-api:8000 으로 넘긴다.
// 둘 다 동일 출처가 되므로 CORS 설정에 의존하지 않는다.
// 백엔드를 다른 호스트에 띄울 때만 VITE_API_BASE 로 덮어쓴다.
const API_BASE = import.meta.env.VITE_API_BASE || '/api';

// 대화 세션 식별자.
// 백엔드는 이 값을 LangGraph 체크포인터의 thread_id 로 쓴다. 보내지 않으면 모든 방문자가
// 같은 기본 thread_id 를 공유해 서로의 대화 맥락이 섞인다.
// 브라우저마다 한 번 만들어 localStorage 에 보관한다.
const SESSION_KEY = 'techdoc_thread_id';

function getThreadId() {
  const fresh = () =>
    (globalThis.crypto?.randomUUID?.() ??
      `s_${Date.now()}_${Math.random().toString(36).slice(2)}`);
  try {
    let id = localStorage.getItem(SESSION_KEY);
    if (!id) {
      id = fresh();
      localStorage.setItem(SESSION_KEY, id);
    }
    return id;
  } catch {
    // 프라이빗 모드 등 localStorage 를 못 쓰는 환경 - 탭 수명 동안만 유효한 값을 쓴다.
    return fresh();
  }
}

export function resetSession() {
  try { localStorage.removeItem(SESSION_KEY); } catch { /* 무시 */ }
}

export const agentClient = {
  // 수집 전 미리보기. 얕은 클론과 청킹까지만 하고 임베딩은 하지 않으므로 몇 초면 끝난다.
  // 문서를 다른 곳으로 이관해 README 만 남은 레포나, 테스트 픽스처·자동생성 문서가
  // 대부분인 레포를 그대로 적재하는 사고를 막기 위한 것이다.
  previewDoc: async (url, { includeExt, excludePaths } = {}) => {
    const params = new URLSearchParams({ url });
    if (includeExt) params.set('include_ext', includeExt);
    if (excludePaths) params.set('exclude_paths', excludePaths);
    const res = await fetch(`${API_BASE}/ingest/preview?${params}`);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `미리보기 실패 (HTTP ${res.status})`);
    }
    return res.json();
  },

  ingestDoc: async (url, { includeExt, excludePaths } = {}) => {
    const res = await fetch(`${API_BASE}/ingest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url,
        // 값이 없으면 보내지 않는다. 백엔드가 "저장된 필터 -> 전역 설정" 순으로 처리한다.
        ...(includeExt ? { include_ext: includeExt } : {}),
        ...(excludePaths ? { exclude_paths: excludePaths } : {}),
      })
    });
    return res.json();
  },
  
  getDocs: async () => {
    const res = await fetch(`${API_BASE}/docs`);
    return res.json();
  },
  
  deleteDoc: async (url) => {
    const res = await fetch(`${API_BASE}/docs?url=${encodeURIComponent(url)}`, {
      method: 'DELETE'
    });
    return res.json();
  },
  
  streamQuestion: (question, callbacks) => {
    const { onTrace, onChunk, onToken, onSources, onDone, onError } = callbacks;
    let retryCount = 0;
    const MAX_RETRIES = 3;
    let es = null;

    const connect = () => {
      const threadId = getThreadId();
      es = new EventSource(
        `${API_BASE}/stream?q=${encodeURIComponent(question)}&thread_id=${encodeURIComponent(threadId)}`
      );
      
      es.addEventListener('trace', (e) => {
        onTrace && onTrace(JSON.parse(e.data));
      });
      
      es.addEventListener('chunk', (e) => {
        onChunk && onChunk(JSON.parse(e.data));
      });
      
      es.addEventListener('token', (e) => {
        onToken && onToken(JSON.parse(e.data));
      });
      
      es.addEventListener('sources', (e) => {
        onSources && onSources(JSON.parse(e.data));
      });
      
      es.addEventListener('done', () => {
        onDone && onDone();
        es.close();
      });
      
      // EventSource 는 두 가지를 같은 'error' 이벤트로 전달한다.
      //   1) 서버가 명시적으로 보낸 `event: error` (e.data 에 메시지가 있다)
      //   2) 네트워크 연결 끊김 (e.data 가 없다)
      // 이걸 구분하지 않으면 서버가 보낸 에러에도 재연결을 시도하게 되는데,
      // 그러면 같은 질문이 다시 실행되어 실패 원인(예: API 할당량 초과)을 더 악화시킨다.
      es.addEventListener('error', (e) => {
        if (e.data) {
          let message = '알 수 없는 오류가 발생했습니다.';
          try {
            message = JSON.parse(e.data).message || message;
          } catch {
            message = String(e.data);
          }
          es.close();
          onError && onError(message);   // 재연결하지 않는다
          return;
        }

        es.close();
        if (retryCount < MAX_RETRIES) {
          retryCount++;
          console.warn(`SSE connection lost. Retrying... (${retryCount}/${MAX_RETRIES})`);
          setTimeout(connect, 1000 * retryCount); // 백오프 재연결
        } else {
          onError && onError('서버에 연결할 수 없습니다. 백엔드가 실행 중인지 확인하세요.');
        }
      });
    };
    
    connect();
    
    return {
      close: () => {
        if (es) es.close();
      }
    };
  }
};
