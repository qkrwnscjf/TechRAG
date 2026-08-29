// NOTE: 현재 어디에서도 import 되지 않는 미사용 훅이다 (Docs.jsx 는 agentClient 를 직접 사용).
import { useState, useEffect, useCallback } from 'react';
import { agentClient } from '../api/agentClient';

export function useDocs() {
  const [docs, setDocs] = useState([]);
  const [isLoading, setIsLoading] = useState(false);

  const fetchDocs = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await agentClient.getDocs();
      setDocs(data);
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const addDoc = async (url) => {
    setIsLoading(true);
    try {
      await agentClient.ingestDoc(url);
      await fetchDocs();
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoading(false);
    }
  };

  const deleteDoc = async (url) => {
    setIsLoading(true);
    try {
      await agentClient.deleteDoc(url);
      await fetchDocs();
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    // 마운트 시 목록을 불러온다. 데이터 페칭은 효과에서 하는 것이 맞고,
    // 이 규칙은 동기 setState 만 문제 삼으므로 이 호출에서만 해제한다.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchDocs();
  }, [fetchDocs]);

  return { docs, addDoc, deleteDoc, isLoading, fetchDocs };
}
