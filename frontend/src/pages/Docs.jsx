import { useState, useEffect } from 'react';
import { agentClient } from '../api/agentClient';

// 청크당 실측 처리 속도(초). 수집 시간을 미리 어림하는 데 쓴다.
const SEC_PER_CHUNK = 0.45;
const estimateMinutes = (chunks) => Math.max(1, Math.round((chunks * SEC_PER_CHUNK) / 60));

function Docs() {
  const [ingestUrl, setIngestUrl] = useState('');
  const [isIngesting, setIsIngesting] = useState(false);
  const [ingestMessage, setIngestMessage] = useState({ text: '', type: '' });
  const [docsList, setDocsList] = useState([]);
  const [isFetchingDocs, setIsFetchingDocs] = useState(false);

  // 수집 필터. 버려야 할 경로는 레포마다 다르므로 화면에서 지정할 수 있게 한다.
  // 비워두면 백엔드가 "저장된 필터 -> 전역 설정" 순으로 알아서 정한다.
  const [includeExt, setIncludeExt] = useState('');
  const [excludePaths, setExcludePaths] = useState('');

  // 미리보기 결과. 넣기 전에 무엇이 들어갈지 보여준다.
  const [preview, setPreview] = useState(null);
  const [isPreviewing, setIsPreviewing] = useState(false);

  const fetchDocs = async () => {
    setIsFetchingDocs(true);
    try {
      setDocsList((await agentClient.getDocs()) || []);
    } catch (e) {
      console.error(e);
    } finally {
      setIsFetchingDocs(false);
    }
  };

  useEffect(() => {
    // 마운트 시 목록을 불러온다. 데이터 페칭은 효과에서 하는 것이 맞고,
    // 이 규칙은 동기 setState 만 문제 삼으므로 이 호출에서만 해제한다.
    // eslint-disable-next-line react-hooks/set-state-in-effect
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

  const filterArgs = () => ({
    includeExt: includeExt.trim() || undefined,
    excludePaths: excludePaths.trim() || undefined,
  });

  const handlePreview = async () => {
    if (!ingestUrl.trim() || isPreviewing || isIngesting) return;
    setIsPreviewing(true);
    setPreview(null);
    setIngestMessage({ text: '', type: '' });
    try {
      const res = await agentClient.previewDoc(ingestUrl.trim(), filterArgs());
      setPreview(res);
      // GitHub 레포가 아니면 미리보기는 없지만 수집은 정상 동작한다.
      // 에러로 보이면 되는 기능을 안 되는 것으로 오해하므로 안내로 띄운다.
      if (res && res.preview_supported === false) {
        setIngestMessage({ text: res.message, type: 'info' });
      }
    } catch (e) {
      setIngestMessage({ text: e.message, type: 'error' });
    } finally {
      setIsPreviewing(false);
    }
  };

  const handleIngest = async () => {
    if (!ingestUrl.trim() || isIngesting) return;
    setIsIngesting(true);
    setIngestMessage({
      text: preview?.chunks > 0
        ? `Embedding ${preview.chunks.toLocaleString()} chunks. This takes about ${estimateMinutes(preview.chunks)} min.`
        : 'Analyzing the document and writing it to the vector store.',
      type: 'info',
    });

    try {
      const res = await agentClient.ingestDoc(ingestUrl.trim(), filterArgs());
      setIngestMessage({
        text: res.message || 'Ingest complete.',
        // 일부 배치만 들어간 partial 을 성공으로 보이게 하면 색인이 온전하다고 오해한다.
        type: res.status === 'error' ? 'error' : res.status === 'partial' ? 'warn' : 'success',
      });
      if (res.status !== 'error') {
        setIngestUrl('');
        setPreview(null);
      }
      fetchDocs();
    } catch {
      setIngestMessage({ text: 'Ingest failed. Check the backend logs.', type: 'error' });
    } finally {
      setIsIngesting(false);
    }
  };

  const totalChunks = docsList.reduce((sum, d) => sum + (d.chunk_count || 0), 0);

  return (
    <div className="section-spacing animate-in fade-in duration-500">
      <div className="page-head">
        <h1 className="page-title font-bold">
          Document <span className="text-accent">Management</span>
        </h1>
        <p className="page-lead">
          Control the knowledge base. Preview what a source would contribute before
          spending time on embeddings, then ingest or remove it.
        </p>
      </div>

      <div className="page-body stack-6">
        {/* ---------- 문서 추가 ---------- */}
        <section className="panel">
          <div className="panel-head">
            <h2 className="panel-title">Add a document</h2>
          </div>

          <div className="panel-body stack-4">
            <div className="ingest-row">
              <input
                type="text"
                className="input"
                placeholder="e.g., https://github.com/vllm-project/vllm"
                value={ingestUrl}
                onChange={(e) => { setIngestUrl(e.target.value); setPreview(null); }}
                onKeyDown={(e) => e.key === 'Enter' && handlePreview()}
                disabled={isIngesting}
                aria-label="Source URL"
              />
              <button
                className="btn btn-secondary"
                onClick={handlePreview}
                disabled={isPreviewing || isIngesting || !ingestUrl.trim()}
              >
                {isPreviewing ? 'Checking…' : 'Preview'}
              </button>
              <button
                className="btn btn-primary"
                onClick={handleIngest}
                disabled={isIngesting || !ingestUrl.trim() || preview?.chunks === 0}
              >
                {isIngesting ? 'Ingesting…' : 'Ingest'}
              </button>
            </div>

            <details className="disclosure">
              <summary>Ingest filters</summary>
              <div className="note stack-3" style={{ marginTop: 'var(--space-3)' }}>
                <p className="text-sm text-muted">
                  Which paths are noise differs per repository. Leave these empty to reuse the
                  filters this document was last ingested with, falling back to the server defaults.
                </p>
                <label className="field-label">
                  Include extensions
                  <input
                    type="text" className="input" placeholder=".md,.mdx"
                    value={includeExt} onChange={(e) => setIncludeExt(e.target.value)}
                    disabled={isIngesting}
                  />
                </label>
                <label className="field-label">
                  Exclude path fragments
                  <input
                    type="text" className="input" placeholder="api-ref,release-notes,tests/"
                    value={excludePaths} onChange={(e) => setExcludePaths(e.target.value)}
                    disabled={isIngesting}
                  />
                </label>
              </div>
            </details>

            {preview?.preview_supported && (
              <div className="note stack-4">
                <div className="stat-grid">
                  {[
                    ['Files', preview.files.toLocaleString()],
                    ['Chunks', preview.chunks.toLocaleString()],
                    ['Est. time', preview.chunks === 0 ? '—' : `${estimateMinutes(preview.chunks)} min`],
                    ['Branch', preview.branch],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <span className="stat-label">{label}</span>
                      <span className="stat-value">{value}</span>
                    </div>
                  ))}
                </div>

                {preview.chunks === 0 && (
                  <p className="text-sm msg-warn">
                    No documents match these filters. Check the extensions and exclude paths —
                    ingesting as-is will fail.
                  </p>
                )}

                {preview.chunks > 4000 && (
                  <p className="text-sm msg-warn">
                    That is a lot of chunks. Consider adding exclude paths — generated API
                    reference, release notes or test fixtures may have slipped in.
                  </p>
                )}

                <div>
                  <span className="eyebrow">Largest documents</span>
                  <ul className="stack-2" style={{ marginTop: 'var(--space-2)' }}>
                    {(preview.largest_files || []).slice(0, 5).map((f) => (
                      <li key={f.path} className="text-sm">
                        <span className="font-mono text-muted">{f.chars.toLocaleString()} chars</span>{' '}
                        <span className="text-foreground">{f.path}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            {ingestMessage.text && (
              <p className={`text-sm msg-${ingestMessage.type || 'info'}`}>{ingestMessage.text}</p>
            )}
          </div>
        </section>

        {/* ---------- 색인된 문서 ---------- */}
        <section className="panel">
          <div className="panel-head">
            <h2 className="panel-title">
              Indexed documents <span className="count-pill">{docsList.length}</span>
            </h2>
            <button
              className="btn btn-secondary btn-sm"
              onClick={fetchDocs}
              disabled={isFetchingDocs}
            >
              {isFetchingDocs ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>

          <div className="panel-body">
            {docsList.length === 0 ? (
              <div className="empty">
                <p className="empty-title">Nothing indexed yet</p>
                <p className="empty-sub">
                  Paste a GitHub repository, a web page or a PDF above to get started.
                </p>
              </div>
            ) : (
              <>
                <ul className="doc-list">
                  {docsList.map((doc, idx) => (
                    <li key={idx} className="doc-item flex justify-between items-center">
                      <div className="doc-main">
                        <span className="doc-url" title={doc.url}>{doc.url}</span>
                        <span className="doc-meta">
                          {doc.chunk_count.toLocaleString()} chunks ·{' '}
                          {new Date(doc.loaded_at).toLocaleString()}
                        </span>
                      </div>
                      <button
                        className="btn btn-danger btn-sm"
                        onClick={() => handleDeleteDoc(doc.url)}
                      >
                        Delete
                      </button>
                    </li>
                  ))}
                </ul>
                <p className="text-sm text-muted" style={{ marginTop: 'var(--space-4)' }}>
                  {totalChunks.toLocaleString()} chunks indexed across {docsList.length} sources.
                </p>
              </>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

export default Docs;
