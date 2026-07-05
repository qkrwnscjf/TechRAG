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
    fetchDocs();
  }, [fetchDocs]);

  return { docs, addDoc, deleteDoc, isLoading, fetchDocs };
}
