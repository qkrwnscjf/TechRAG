import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import { useAgentStream } from '../hooks/useAgentStream';

// 생성 결과는 마크다운이다. 평문으로 뿌리면 코드 블록과 목록이 뭉개져,
// 기술 문서 답변으로서 읽을 수 없게 된다.
const markdownComponents = {
  code({ inline, children, ...props }) {
    if (inline) return <code className="inline-code" {...props}>{children}</code>;
    return (
      <pre className="code-block">
        <code {...props}>{children}</code>
      </pre>
    );
  },
  a: (props) => <a target="_blank" rel="noreferrer" className="link" {...props} />,
  ul: (props) => <ul className="md-list" {...props} />,
  ol: (props) => <ol className="md-list md-list-ordered" {...props} />,
};

// 백엔드가 그대로 올려보내는 원문 에러를 사용자가 읽을 수 있는 문장으로 바꾼다.
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
    return { title: 'Cannot reach the backend', detail: 'Check that the API server is running.' };
  }
  return { title: 'Request failed', detail: text.slice(0, 300) };
}

// 진행 단계를 한 문장으로 옮긴다.
function describeStep(step) {
  if (!step) return 'Working…';
  switch (step.node) {
    case 'contextualize':
      // method: first(첫 질문) / rule(규칙으로 건너뜀) / llm(실제 문맥화)
      if (step.method === 'rule') return 'Self-contained question — no rewrite needed';
      if (step.method === 'first') return 'First question — no prior context';
      return 'Rewrote the question to stand alone';
    case 'retriever':
      return `Found ${step.doc_count} documents`;
    case 'grader':
      return `Kept ${step.kept} of ${step.kept + step.dropped} documents`
        + (step.method === 'reranker' ? ' (reranker)' : '');
    case 'question_rewriter':
      return 'Rewrote the question to refine the search';
    case 'generator':
      return 'Generating the answer';
    default:
      return step.node;
  }
}

// 출처 칩에 URL 전체를 넣으면 한 줄을 다 먹는다. 알아볼 수 있는 만큼만 줄인다.
function shortSource(url) {
  const clean = String(url || '').replace(/^https?:\/\//, '').replace(/\/$/, '');
  return clean.length > 46 ? `${clean.slice(0, 43)}…` : clean;
}

function Trace({ steps, running, elapsed }) {
  // 진행 중에는 펼쳐 두고 끝나면 접는다. 그 뒤 사용자가 연 상태는 유지한다.
  const [userOpen, setUserOpen] = useState(null);
  const open = userOpen === null ? running : userOpen;

  return (
    <details
      className="trace"
      open={open}
      onToggle={(e) => { if (!running) setUserOpen(e.currentTarget.open); }}
    >
      <summary>
        {running ? (
          <>
            <span className="pulse-dot animate-pulse-glow" />
            {describeStep(steps[steps.length - 1])}
          </>
        ) : (
          <>
            {steps.length} step{steps.length === 1 ? '' : 's'}
            {elapsed ? ` · ${(elapsed / 1000).toFixed(1)}s` : ''}
          </>
        )}
      </summary>
      <div className="trace-body">
        {steps.map((step, i) => (
          <div
            key={i}
            className="trace-step flex items-center gap-2 text-sm text-muted"
            style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}
          >
            <span className="trace-chip">{step.node}</span>
            <span>{describeStep(step)}</span>
          </div>
        ))}
      </div>
    </details>
  );
}

function Turn({ turn, running }) {
  const { title, detail } = turn.error ? describeError(turn.error) : {};

  return (
    <article className="turn">
      <header className="turn-q">
        <span className="q-badge" aria-hidden="true">Q</span>
        <h2 className="q-text">{turn.question}</h2>
      </header>

      <div className="turn-a">
        {turn.trace.length > 0 && (
          <Trace steps={turn.trace} running={running} elapsed={turn.elapsed} />
        )}

        {turn.error ? (
          <div className="alert" role="alert">
            <p className="alert-title">{title}</p>
            <p className="alert-detail">{detail}</p>
          </div>
        ) : turn.answer ? (
          <div className="answer">
            <ReactMarkdown components={markdownComponents}>{turn.answer}</ReactMarkdown>
          </div>
        ) : (
          <div className="skeleton-lines" aria-label="Generating the answer">
            <div className="skeleton" />
            <div className="skeleton" />
            <div className="skeleton" />
          </div>
        )}

        {turn.sources.length > 0 && (
          <div className="sources">
            <span className="eyebrow">Sources</span>
            {turn.sources.map((src, i) => (
              <a
                key={i}
                className="source-chip"
                href={src.url}
                target="_blank"
                rel="noreferrer"
                title={src.url}
              >
                <span>{shortSource(src.url)}</span>
              </a>
            ))}
          </div>
        )}

        {/* 근거가 없이 끝났다면 다음 행동을 제시한다. */}
        {turn.done && !turn.error && turn.sources.length === 0 && (
          <p className="answer-hint">
            No sources were used. The answer may not be in the index —{' '}
            <Link to="/docs">add a document</Link>.
          </p>
        )}
      </div>
    </article>
  );
}

const EXAMPLES = [
  'How does PagedAttention work in vLLM?',
  'How do I set a cache policy on a Prefect task?',
  'What are Scores in Langfuse?',
];

function Home() {
  const [query, setQuery] = useState('');
  const { turns, isStreaming, askQuestion, stopStream } = useAgentStream();
  const inputRef = useRef(null);
  const endRef = useRef(null);
  const started = turns.length > 0;

  const ask = useCallback((text) => {
    const q = (text ?? query).trim();
    if (!q || isStreaming) return;
    askQuestion(q);
    setQuery('');
  }, [query, isStreaming, askQuestion]);

  // 새 턴이 생기면 그 자리로 옮긴다. 답변이 화면 밖에서 생기면 아무 반응도 못 본다.
  useEffect(() => {
    if (started) endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turns.length, started]);

  // 어디서든 입력창으로 돌아올 수 있게 한다.
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="animate-in fade-in duration-500">
      {!started && (
        <section className="container hero-section">
          <div className="flex flex-col items-center text-center mx-auto" style={{ maxWidth: '48rem', width: '100%' }}>
            <div className="hero-badge">
              <div className="pulse-dot animate-pulse-glow" />
              <span>Self-Verifying RAG</span>
            </div>
            <h1 className="hero-title mb-6 font-bold">
              Ask your <br />
              <span className="text-accent">technical docs.</span>
            </h1>
            <p className="page-lead" style={{ maxWidth: '38rem' }}>
              Grades whether the retrieved documents actually answer your question, and rewrites
              the question to search again when they don&apos;t. With no supporting evidence it
              says so, rather than making something up.
            </p>
          </div>
        </section>
      )}

      <div className="chat">
        {started && (
          <div className="conversation">
            {turns.map((turn, i) => (
              <Turn
                key={turn.id}
                turn={turn}
                running={i === turns.length - 1 && isStreaming && !turn.done}
              />
            ))}
            <div ref={endRef} />
          </div>
        )}

        <div className={started ? 'composer' : 'composer is-static'}>
          <div className="composer-row">
            <input
              ref={inputRef}
              type="text"
              className="input"
              placeholder={started ? 'Ask a follow-up…' : 'e.g., What is LCEL in LangChain?'}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && ask()}
              disabled={isStreaming}
              aria-label="Question"
            />
            {isStreaming ? (
              <button className="btn btn-secondary" onClick={stopStream}>Stop</button>
            ) : (
              <button
                className="btn btn-primary"
                onClick={() => ask()}
                disabled={!query.trim()}
              >
                Ask
              </button>
            )}
          </div>
          <div className="composer-meta">
            <span><kbd>Enter</kbd> to send</span>
            <span><kbd>⌘</kbd><kbd>K</kbd> to focus</span>
            {started && <span>Follow-ups keep the conversation context.</span>}
          </div>
        </div>
      </div>

      {!started && (
        <>
          <section className="chat" style={{ paddingBottom: '2rem' }}>
            <div className="flex flex-wrap gap-2">
              <span className="eyebrow" style={{ width: '100%' }}>Try one</span>
              {EXAMPLES.map((ex) => (
                <button key={ex} className="source-chip" onClick={() => ask(ex)}>
                  <span>{ex}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="container features-section">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
              <div className="card card-interactive flex flex-col items-start text-left">
                <div className="tag mb-5">Ingest</div>
                <h3 className="text-xl font-semibold mb-3">Preview before you index</h3>
                <p className="text-muted text-sm">
                  Indexes GitHub repositories, web pages and PDFs. A dry run shows which files
                  and how many chunks would be added, so test fixtures and generated docs
                  never slip into the index unnoticed.
                </p>
              </div>

              <div className="card card-interactive highlighted flex flex-col items-start text-left">
                <div className="tag mb-5 tag-accent">Agent</div>
                <h3 className="text-xl font-semibold mb-3">Retrieval that checks itself</h3>
                <p className="text-muted text-sm">
                  Runs as a cyclic LangGraph. It grades its own retrievals, drops the documents
                  that miss, and rewrites the question to search again — two attempts, then it stops.
                </p>
              </div>

              <div className="card card-interactive flex flex-col items-start text-left">
                <div className="tag mb-5">Stack</div>
                <h3 className="text-xl font-semibold mb-3">Local embeddings + Gemini</h3>
                <p className="text-muted text-sm">
                  Embeddings run locally on BAAI/bge-m3, so ingestion costs no API credits.
                  Only answer generation calls Gemini 2.5 Flash; Pinecone handles retrieval.
                </p>
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

export default Home;
