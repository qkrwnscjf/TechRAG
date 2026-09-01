import { useCallback, useRef, useState } from 'react';
import { agentClient } from '../api/agentClient';

/**
 * 대화 전체를 턴 배열로 들고 있는다.
 *
 * 이전 구현은 질문마다 trace/answer/sources 를 비우고 최신 하나만 유지했다.
 * 그런데 백엔드는 thread_id 로 대화를 기억하고 contextualize 노드가 "그거" 같은
 * 대명사를 앞선 질문으로 풀어낸다. 화면이 이전 턴을 지워버리면 그 기능이
 * 동작해도 사용자는 확인할 방법이 없다.
 *
 * EventSource 는 state 가 아니라 ref 로 들고 있다. state 로 두면 askQuestion 이
 * eventSource 를 의존성으로 갖게 되어 매 렌더마다 새 함수가 만들어진다.
 */
export function useAgentStream() {
  const [turns, setTurns] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const esRef = useRef(null);
  const seqRef = useRef(0);

  // 스트림 이벤트는 항상 마지막 턴에 쌓인다.
  const patchLast = useCallback((fn) => {
    setTurns((prev) => {
      if (prev.length === 0) return prev;
      const next = prev.slice();
      next[next.length - 1] = fn(next[next.length - 1]);
      return next;
    });
  }, []);

  const askQuestion = useCallback((question) => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }

    seqRef.current += 1;
    setTurns((prev) => [
      ...prev,
      {
        id: seqRef.current,
        question,
        trace: [],
        answer: '',
        sources: [],
        error: null,
        done: false,
        startedAt: Date.now(),
      },
    ]);
    setIsStreaming(true);

    esRef.current = agentClient.streamQuestion(question, {
      onTrace: (data) => patchLast((t) => ({ ...t, trace: [...t.trace, data] })),
      onToken: (data) => patchLast((t) => ({ ...t, answer: t.answer + data.text })),
      onSources: (data) => patchLast((t) => ({ ...t, sources: data.sources || [] })),
      onDone: () => {
        patchLast((t) => ({ ...t, done: true, elapsed: Date.now() - t.startedAt }));
        setIsStreaming(false);
      },
      onError: (message) => {
        patchLast((t) => ({
          ...t,
          error: typeof message === 'string' ? message : 'Request failed.',
          done: true,
          elapsed: Date.now() - t.startedAt,
        }));
        setIsStreaming(false);
      },
    });
  }, [patchLast]);

  const stopStream = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    patchLast((t) => ({ ...t, done: true, elapsed: Date.now() - t.startedAt }));
    setIsStreaming(false);
  }, [patchLast]);

  return { turns, isStreaming, askQuestion, stopStream };
}
