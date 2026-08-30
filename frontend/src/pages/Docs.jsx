import { useState, useEffect } from 'react';
import { agentClient } from '../api/agentClient';

function Docs() {
  const [ingestUrl, setIngestUrl] = useState('');
  const [isIngesting, setIsIngesting] = useState(false);
  const [ingestMessage, setIngestMessage] = useState({ text: '', type: '' });
  const [docsList, setDocsList] = useState([]);
  const [isFetchingDocs, setIsFetchingDocs] = useState(false);

  // 수집 필터. 버려야 할 경로는 레포마다 다르므로 화면에서 지정할 수 있게 한다.
  // 비워두면 백엔드가 "저장된 필터 -> 전역 설정" 순으로 알아서 정한다.
  const [showFilters, setShowFilters] = useState(false);
  const [includeExt, setIncludeExt] = useState('');
  const [excludePaths, setExcludePaths] = useState('');

  // 미리보기 결과. 넣기 전에 무엇이 들어갈지 보여준다.
  const [preview, setPreview] = useState(null);
  const [isPreviewing, setIsPreviewing] = useState(false);

  // 청크당 실측 처리 속도(초). 수집 시간을 미리 어림하는 데 쓴다.
  const SEC_PER_CHUNK = 0.45;

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
      setPreview(await agentClient.previewDoc(ingestUrl.trim(), filterArgs()));
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
      text: preview
        ? `${preview.chunks.toLocaleString()}개 청크를 임베딩하고 있습니다. 약 ${Math.max(1, Math.round(preview.chunks * SEC_PER_CHUNK / 60))}분 걸립니다.`
        : '문서를 분석해 벡터 DB에 저장하고 있습니다.',
      type: 'info',
    });

    try {
      const res = await agentClient.ingestDoc(ingestUrl.trim(), filterArgs());
      setIngestMessage({
        text: res.message || '수집을 마쳤습니다.',
        // 일부 배치만 들어간 partial 을 성공으로 보이게 하면 색인이 온전하다고 오해한다.
        type: res.status === 'error' ? 'error' : res.status === 'partial' ? 'warn' : 'success',
      });
      if (res.status !== 'error') {
        setIngestUrl('');
        setPreview(null);
      }
      fetchDocs();
    } catch {
      setIngestMessage({ text: '수집에 실패했습니다. 백엔드 로그를 확인하세요.', type: 'error' });
    } finally {
      setIsIngesting(false);
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
          <h3 className="text-lg font-semibold text-foreground mb-4">문서 수집</h3>

          <div className="flex gap-3">
            <input
              type="text"
              className="input flex-1"
              placeholder="예: https://github.com/vllm-project/vllm"
              value={ingestUrl}
              onChange={(e) => { setIngestUrl(e.target.value); setPreview(null); }}
              onKeyDown={(e) => e.key === 'Enter' && handlePreview()}
              disabled={isIngesting}
            />
            <button
              className="btn btn-secondary"
              onClick={handlePreview}
              disabled={isPreviewing || isIngesting || !ingestUrl.trim()}
              style={{ minWidth: '120px' }}
            >
              {isPreviewing ? '확인 중...' : '미리보기'}
            </button>
            <button
              className="btn btn-primary"
              onClick={handleIngest}
              disabled={isIngesting || !ingestUrl.trim() || preview?.chunks === 0}
              style={{ minWidth: '120px' }}
            >
              {isIngesting ? '수집 중...' : '수집'}
            </button>
          </div>

          <button
            className="text-sm text-muted mt-3"
            style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
            onClick={() => setShowFilters((v) => !v)}
          >
            {showFilters ? '▾' : '▸'} 수집 필터 {showFilters ? '' : '(선택)'}
          </button>

          {showFilters && (
            <div className="flex flex-col gap-3 mt-3 p-4 rounded-lg"
                 style={{ background: 'var(--muted)', border: '1px solid var(--border)' }}>
              <p className="text-sm text-muted" style={{ lineHeight: '1.6' }}>
                버려야 할 경로는 레포마다 다릅니다. 비워두면 이 문서가 이전에 쓴 필터,
                그것도 없으면 서버 기본값을 사용합니다.
              </p>
              <label className="text-sm text-muted">
                수집할 확장자
                <input
                  type="text" className="input mt-1" placeholder=".md,.mdx"
                  value={includeExt} onChange={(e) => setIncludeExt(e.target.value)}
                  disabled={isIngesting}
                />
              </label>
              <label className="text-sm text-muted">
                제외할 경로 조각
                <input
                  type="text" className="input mt-1"
                  placeholder="api-ref,release-notes,tests/"
                  value={excludePaths} onChange={(e) => setExcludePaths(e.target.value)}
                  disabled={isIngesting}
                />
              </label>
            </div>
          )}

          {preview && (
            <div className="mt-4 p-4 rounded-lg"
                 style={{ background: 'var(--muted)', border: '1px solid var(--border)' }}>
              <div className="flex flex-wrap gap-6 mb-4">
                {[
                  ['파일', preview.files.toLocaleString()],
                  ['청크', preview.chunks.toLocaleString()],
                  ['예상 소요', preview.chunks === 0 ? '-' : `${Math.max(1, Math.round(preview.chunks * SEC_PER_CHUNK / 60))}분`],
                  ['브랜치', preview.branch],
                ].map(([label, value]) => (
                  <div key={label} className="flex flex-col">
                    <span className="text-sm text-muted">{label}</span>
                    <span className="text-xl font-semibold text-foreground">{value}</span>
                  </div>
                ))}
              </div>

              {preview.chunks === 0 && (
                <p className="text-sm mb-3" style={{ color: '#fbbf24' }}>
                  필터에 걸리는 문서가 없습니다. 확장자나 제외 경로를 확인하세요.
                  이대로 수집하면 실패합니다.
                </p>
              )}

              {preview.chunks > 4000 && (
                <p className="text-sm mb-3" style={{ color: '#fbbf24' }}>
                  청크가 많습니다. 제외 경로를 추가해 줄이는 것을 권합니다 —
                  자동 생성 API 레퍼런스, 릴리스 노트, 테스트 픽스처가 섞였을 수 있습니다.
                </p>
              )}

              <p className="text-sm text-muted mb-2">가장 큰 문서 — 실제 기술 문서인지 확인하세요</p>
              <ul className="flex flex-col gap-2">
                {(preview.largest_files || []).slice(0, 5).map((f) => (
                  <li key={f.path} className="text-sm">
                    <span className="font-mono text-muted">
                      {f.chars.toLocaleString()}자
                    </span>{' '}
                    <span className="text-foreground">{f.path}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {ingestMessage.text && (
            <p
              className="text-sm mt-3"
              style={{
                color: ingestMessage.type === 'error' ? '#f87171'
                     : ingestMessage.type === 'warn' ? '#fbbf24'
                     : 'var(--accent)',
              }}
            >
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
