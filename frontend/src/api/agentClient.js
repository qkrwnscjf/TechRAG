const API_BASE = 'http://localhost:8000/api';

export const agentClient = {
  ingestDoc: async (url) => {
    const res = await fetch(`${API_BASE}/ingest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
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
      es = new EventSource(`${API_BASE}/stream?q=${encodeURIComponent(question)}`);
      
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
      
      es.addEventListener('error', (e) => {
        es.close();
        if (retryCount < MAX_RETRIES) {
          retryCount++;
          console.warn(`SSE connection lost. Retrying... (${retryCount}/${MAX_RETRIES})`);
          setTimeout(connect, 1000 * retryCount); // 백오프 재연결
        } else {
          onError && onError(e);
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
