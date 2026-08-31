import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import { useAgentStream } from '../hooks/useAgentStream';

// 생성 결과는 마크다운이다. 평문으로 뿌리면 코드 블록과 목록이 뭉개져,
// 기술 문서 답변으로서 읽을 수 없게 된다.
const markdownComponents = {
  code({ inline, children, ...props }) {
    if (inline) {
      return (
        <code
          style={{
            background: 'var(--muted)',
            padding: '0.15em 0.4em',
            borderRadius: '4px',
            fontSize: '0.9em',
          }}
          {...props}
        >
          {children}
        </code>
      );
    }
    return (
      <pre
        style={{
          background: 'var(--muted)',
          border: '1px solid var(--border)',
          borderRadius: '8px',
          padding: '0.9rem 1rem',
          overflowX: 'auto',
          fontSize: '0.85rem',
          lineHeight: '1.6',
        }}
      >
        <code {...props}>{children}</code>
      </pre>
    );
  },
  a({ children, ...props }) {
    return (
      <a target="_blank" rel="noreferrer" className="text-accent hover:underline" {...props}>
        {children}
      </a>
    );
  },
  ul: (props) => <ul style={{ paddingLeft: '1.25rem', listStyle: 'disc' }} {...props} />,
  ol: (props) => <ol style={{ paddingLeft: '1.25rem', listStyle: 'decimal' }} {...props} />,
  li: (props) => <li style={{ margin: '0.25rem 0' }} {...props} />,
  p: (props) => <p style={{ margin: '0.6rem 0', lineHeight: '1.7' }} {...props} />,
};

// 백엔드가 그대로 올려보내는 원문 에러를 사용자가 읽을 수 있는 문장으로 바꾼다.
// 백엔드 메시지는 한글일 수 있으므로 패턴은 양쪽을 모두 본다.
function describeError(raw) {
  const text = String(raw || '');
  if (/429|RESOURCE_EXHAUSTED|quota/i.test(text)) {
    return {
      title: 'Gemini free-tier limit reached',
      detail:
        'The free tier allows 5 requests per minute and 20 per day. Wait a moment and retry, or come back tomorrow.',
    };
  }
  if (/connect|연결/i.test(text)) {
    return {
      title: 'Cannot reach the backend',
      detail: 'Check that the API server is running.',
    };
  }
  return { title: 'Request failed', detail: text.slice(0, 300) };
}

// 진행 단계를 한 문장으로 옮긴다.
function describeStep(step) {
  switch (step.node) {
    case 'contextualize':
      return 'Rewrote the question to stand alone';
    case 'retriever':
      return `Found ${step.doc_count} documents`;
    case 'grader':
      return `Kept ${step.kept} of ${step.kept + step.dropped} documents`
        + (step.method === 'reranker' ? ' (reranker)' : '');
    case 'question_rewriter':
      return 'Rewrote question to refine search';
    case 'generator':
      return 'Generating final answer';
    default:
      return step.node;
  }
}

function Home() {
  const [query, setQuery] = useState('');
  const { trace, answer, sources, isStreaming, error, askQuestion, stopStream } = useAgentStream();

  // 대화가 시작됐는지. 히어로를 접고 결과로 스크롤하는 기준이 된다.
  const hasSession = trace.length > 0 || Boolean(answer) || Boolean(error);
  const resultRef = useRef(null);

  useEffect(() => {
    // 히어로가 화면을 채우고 있으면 답변이 스크롤 아래에서 생겨,
    // 질문을 던진 사용자가 아무 반응도 못 본다. 첫 결과에서 한 번만 옮긴다.
    if (hasSession && resultRef.current) {
      resultRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [hasSession]);

  const handleAsk = () => {
    if (!query.trim() || isStreaming) return;
    askQuestion(query);
  };

  return (
    <div className="animate-in fade-in duration-500">
      <section className={`container hero-section${hasSession ? ' is-compact' : ''}`}>
        <div className="flex flex-col items-center text-center mx-auto" style={{ maxWidth: '48rem', width: '100%' }}>
          <div className="hero-badge">
            <div className="pulse-dot animate-pulse-glow"></div>
            <span>Self-Verifying RAG</span>
          </div>
          <h1 className="hero-title mb-6 font-bold">
            Ask your <br/>
            <span className="text-accent">technical docs.</span>
          </h1>
          {!hasSession && (
            <p className="text-xl text-muted mb-10" style={{ maxWidth: '42rem', lineHeight: '1.6' }}>
              Grades whether the retrieved documents actually answer your question, and rewrites
              the question to search again when they don&apos;t. With no supporting evidence it
              says so, rather than making something up.
            </p>
          )}

          <div className="w-full flex flex-col md:flex-row gap-4 justify-center" style={{ maxWidth: '42rem' }}>
            <input
              type="text"
              className="input flex-1"
              placeholder="e.g., What is LCEL in LangChain?"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAsk()}
              disabled={isStreaming}
            />
            <button
              className="btn btn-primary"
              style={{ padding: '0 2rem' }}
              onClick={handleAsk}
              disabled={isStreaming || !query.trim()}
            >
              {isStreaming ? 'Thinking...' : 'Ask Agent'}
            </button>
            {isStreaming && (
              <button className="btn btn-secondary" style={{ padding: '0 1.5rem' }} onClick={stopStream}>
                Stop
              </button>
            )}
          </div>
        </div>
      </section>

      {/* Results Section */}
      {hasSession && (
        <section ref={resultRef} className="container mb-24" style={{ maxWidth: '48rem', scrollMarginTop: '5rem' }}>
          <div className="card text-left">

            {/* Agent Trace */}
            {trace.length > 0 && (
              <div className="mb-6 pb-6" style={{ borderBottom: '1px solid var(--border)' }}>
                <h4 className="text-sm font-medium text-muted-foreground mb-3 uppercase tracking-wide">Agent Trace</h4>
                <div className="flex flex-col gap-2">
                  {trace.map((step, idx) => (
                    <div
                      key={idx}
                      className="trace-step flex items-center gap-2 text-sm text-muted"
                      style={{ animationDelay: `${Math.min(idx, 8) * 40}ms` }}
                    >
                      <span className="text-accent">▶</span>
                      <span className="trace-chip">{step.node}</span>
                      <span>{describeStep(step)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Final Answer */}
            <div className="answer-content">
              <h3 className="text-xl font-semibold mb-4 text-foreground">Answer</h3>
              {error ? (
                <div
                  className="p-4 rounded-lg"
                  style={{
                    border: '1px solid rgba(248, 113, 113, 0.35)',
                    backgroundColor: 'rgba(248, 113, 113, 0.08)',
                  }}
                >
                  <p className="text-base font-semibold msg-error">
                    {describeError(error).title}
                  </p>
                  <p className="text-sm text-muted mt-2" style={{ lineHeight: '1.6' }}>
                    {describeError(error).detail}
                  </p>
                </div>
              ) : answer ? (
                <div className="text-base text-foreground answer-markdown">
                  <ReactMarkdown components={markdownComponents}>{answer}</ReactMarkdown>
                </div>
              ) : (
                <p className="text-muted-foreground animate-pulse">Generating response...</p>
              )}

              {/* Sources */}
              {sources.length > 0 && (
                <div className="mt-6 pt-4" style={{ borderTop: '1px dashed var(--border)' }}>
                  <h4 className="text-sm font-medium text-muted-foreground mb-2">Sources</h4>
                  <ul className="flex flex-col gap-1">
                    {sources.map((src, idx) => (
                      <li key={idx} className="text-sm text-accent">
                        <a href={src.url} target="_blank" rel="noreferrer" className="hover:underline">{src.url}</a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {/* 대화가 시작되면 소개 카드는 물러난다. */}
      {!hasSession && (
        <section className="container features-section">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            <div className="card card-interactive flex flex-col items-start text-left">
              <div className="tag mb-5">Ingest</div>
              <h3 className="text-xl font-semibold mb-3">Preview before you index</h3>
              <p className="text-muted text-sm" style={{ lineHeight: '1.6' }}>
                Indexes GitHub repositories, web pages and PDFs. A dry run shows which files
                and how many chunks would be added, so test fixtures and generated docs
                never slip into the index unnoticed.
              </p>
            </div>

            <div className="card card-interactive highlighted flex flex-col items-start text-left">
              <div className="tag mb-5" style={{ color: 'var(--accent)', border: '1px solid rgba(245, 158, 11, 0.2)' }}>Agent</div>
              <h3 className="text-xl font-semibold mb-3">Retrieval that checks itself</h3>
              <p className="text-muted text-sm" style={{ lineHeight: '1.6' }}>
                Runs as a cyclic LangGraph. It grades its own retrievals, drops the documents
                that miss, and rewrites the question to search again — two attempts, then it stops.
              </p>
            </div>

            <div className="card card-interactive flex flex-col items-start text-left">
              <div className="tag mb-5">Stack</div>
              <h3 className="text-xl font-semibold mb-3">Local embeddings + Gemini</h3>
              <p className="text-muted text-sm" style={{ lineHeight: '1.6' }}>
                Embeddings run locally on BAAI/bge-m3, so ingestion costs no API credits.
                Only answer generation calls Gemini 2.5 Flash; Pinecone handles retrieval.
              </p>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

export default Home;
