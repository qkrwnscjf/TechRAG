import React, { useState, useEffect } from 'react';
import { agentClient } from '../api/agentClient';

function Docs() {
  const [ingestUrl, setIngestUrl] = useState('');
  const [isIngesting, setIsIngesting] = useState(false);
  const [ingestMessage, setIngestMessage] = useState({ text: '', type: '' });
  const [docsList, setDocsList] = useState([]);
  const [isFetchingDocs, setIsFetchingDocs] = useState(false);

  const fetchDocs = async () => {
    setIsFetchingDocs(true);
    try {
      const data = await agentClient.getDocs();
      setDocsList(data || []);
    } catch (e) {
      console.error(e);
    } finally {
      setIsFetchingDocs(false);
    }
  };

  useEffect(() => {
    fetchDocs();
  }, []);

  const handleDeleteDoc = async (url) => {
    try {
      await agentClient.deleteDoc(url);
      fetchDocs();
    } catch (e) {
      alert('Failed to delete: ' + e.message);
    }
  };

  const handleIngest = async () => {
    if (!ingestUrl.trim() || isIngesting) return;
    setIsIngesting(true);
    setIngestMessage({ text: 'Analyzing and saving document to Vector DB...', type: 'info' });
    
    try {
      const res = await agentClient.ingestDoc(ingestUrl);
      setIngestMessage({ text: res.message || 'Document successfully ingested!', type: 'success' });
      setIngestUrl('');
      fetchDocs();
    } catch (error) {
      setIngestMessage({ text: 'Failed to ingest document. Please check backend logs.', type: 'error' });
    } finally {
      setIsIngesting(false);
      setTimeout(() => setIngestMessage({ text: '', type: '' }), 5000);
    }
  };

  return (
    <div className="container section-spacing animate-in fade-in duration-500 flex flex-col items-center">
      <div className="w-full flex flex-col text-center mb-10" style={{ maxWidth: '48rem' }}>
        <h1 className="text-4xl md:text-5xl mb-4 font-bold" style={{ letterSpacing: '-0.03em' }}>
          Document <span className="text-accent">Management</span>
        </h1>
        <p className="text-lg text-muted">
          Control the knowledge base. Ingest new documentation URLs or remove existing indexed data from Pinecone.
        </p>
      </div>
      
      <div className="card w-full text-left" style={{ maxWidth: '48rem' }}>
        {/* Ingest Section */}
        <div className="mb-8">
          <h3 className="text-lg font-semibold text-foreground mb-4">Ingest New Document</h3>
          <div className="flex gap-4">
            <input 
              type="text" 
              className="input flex-1" 
              placeholder="e.g., https://python.langchain.com/docs/get_started/introduction"
              value={ingestUrl}
              onChange={(e) => setIngestUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleIngest()}
              disabled={isIngesting}
            />
            <button 
              className="btn btn-primary" 
              onClick={handleIngest}
              disabled={isIngesting}
              style={{ minWidth: '160px' }}
            >
              {isIngesting ? 'Ingesting...' : 'Ingest Document'}
            </button>
          </div>
          {ingestMessage.text && (
            <p className={`text-sm mt-3 ${ingestMessage.type === 'error' ? 'text-red-400' : 'text-accent'}`}>
              {ingestMessage.text}
            </p>
          )}
        </div>

        {/* Document List Section */}
        <div className="pt-8" style={{ borderTop: '1px solid var(--border)' }}>
          <div className="flex justify-between items-center mb-6">
            <h3 className="text-lg font-semibold text-foreground">Indexed Documents ({docsList.length})</h3>
            <button className="btn btn-secondary text-sm" style={{ padding: '0.5rem 1rem', height: '36px' }} onClick={fetchDocs} disabled={isFetchingDocs}>
              Refresh
            </button>
          </div>
          
          {docsList.length === 0 ? (
            <div className="text-center py-12 bg-[var(--muted)] rounded-lg border" style={{ borderColor: 'var(--border)' }}>
              <p className="text-muted-foreground">No documents indexed yet.</p>
            </div>
          ) : (
            <ul className="flex flex-col gap-3 max-h-[400px] overflow-y-auto pr-2">
              {docsList.map((doc, idx) => (
                <li key={idx} className="flex justify-between items-center bg-[var(--muted)] p-4 rounded-xl border transition-all hover:border-gray-500" style={{ borderColor: 'var(--border)' }}>
                  <div className="flex flex-col overflow-hidden text-left flex-1 mr-4">
                    <span className="text-base text-foreground font-medium truncate">{doc.url}</span>
                    <span className="text-sm text-muted mt-1 font-mono">{doc.chunk_count} chunks • {new Date(doc.loaded_at).toLocaleString()}</span>
                  </div>
                  <button 
                    className="btn text-sm text-red-400 hover:text-red-300 transition-colors"
                    style={{ backgroundColor: 'rgba(248, 113, 113, 0.1)', height: '36px', padding: '0 1rem' }}
                    onClick={() => handleDeleteDoc(doc.url)}
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

export default Docs;
