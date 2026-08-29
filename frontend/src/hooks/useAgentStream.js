import { useState, useCallback } from 'react';
import { agentClient } from '../api/agentClient';

export function useAgentStream() {
  const [trace, setTrace] = useState([]);
  const [chunks, setChunks] = useState([]);
  const [answer, setAnswer] = useState('');
  const [sources, setSources] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState(null);
  const [eventSource, setEventSource] = useState(null);

  const askQuestion = useCallback((question) => {
    setTrace([]);
    setChunks([]);
    setAnswer('');
    setSources([]);
    setError(null);
    setIsStreaming(true);
    
    if (eventSource) {
      eventSource.close();
    }

    const es = agentClient.streamQuestion(question, {
      onTrace: (data) => setTrace(prev => [...prev, data]),
      onChunk: (data) => setChunks(prev => [...prev, data]),
      onToken: (data) => setAnswer(prev => prev + data.text),
      onSources: (data) => setSources(data.sources),
      onDone: () => setIsStreaming(false),
      onError: (message) => {
        setError(typeof message === 'string' ? message : '오류가 발생했습니다.');
        setIsStreaming(false);
      }
    });

    setEventSource(es);
  }, [eventSource]);

  const stopStream = useCallback(() => {
    if (eventSource) {
      eventSource.close();
      setIsStreaming(false);
    }
  }, [eventSource]);

  return { trace, chunks, answer, sources, isStreaming, error, askQuestion, stopStream };
}
