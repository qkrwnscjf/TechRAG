import { useState } from 'react';
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
function describeError(raw) {
  const text = String(raw || '');
  if (/429|RESOURCE_EXHAUSTED|quota/i.test(text)) {
    return {
      title: 'Gemini 무료 티어 한도에 도달했습니다',
      detail: '무료 티어는 분당 5회 · 하루 20회입니다. 잠시 후 다시 시도하거나, 내일 다시 질문해 주세요.',
    };
  }
  if (/connect|연결/i.test(text)) {
    return { title: '백엔드에 연결할 수 없습니다', detail: 'API 서버가 실행 중인지 확인해 주세요.' };
  }
  return { title: '요청을 처리하지 못했습니다', detail: text.slice(0, 300) };
}

function Home() {
  const [query, setQuery] = useState('');
  const { trace, answer, sources, isStreaming, error, askQuestion, stopStream } = useAgentStream();

  const handleAsk = () => {
    if (!query.trim() || isStreaming) return;
    askQuestion(query);
  };

  return (
    <div className="animate-in fade-in duration-500">
      <section className="container hero-section">
        <div className="flex flex-col items-center text-center mx-auto" style={{ maxWidth: '48rem', width: '100%' }}>
          <div className="hero-badge">
            <div className="pulse-dot animate-pulse-glow"></div>
            <span>자기 검증 RAG</span>
          </div>
          <h1 className="text-5xl md:text-6xl lg:text-7xl mb-6 font-bold" style={{ letterSpacing: '-0.03em', lineHeight: '1.2' }}>
            기술 문서에 <br/>
            <span className="text-accent">물어보세요.</span>
          </h1>
          <p className="text-xl text-muted mb-10" style={{ maxWidth: '42rem', lineHeight: '1.6' }}>
            검색한 문서가 질문에 맞는지 스스로 채점하고, 맞지 않으면 질문을 고쳐 다시 찾습니다.
            근거가 없으면 지어내지 않고 모른다고 답합니다.
          </p>
          
          <div className="w-full flex flex-col md:flex-row gap-4 justify-center" style={{ maxWidth: '42rem' }}>
            <input 
              type="text" 
              className="input flex-1" 
              placeholder="e.g., LangChain의 LCEL이란 무엇인가"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAsk()}
              disabled={isStreaming}
            />
            <button 
              className="btn btn-primary" 
              style={{ padding: '0 2rem' }} 
              onClick={handleAsk}
              disabled={isStreaming}
            >
              {isStreaming ? 'Thinking...' : 'Ask Agent'}
            </button>
            {isStreaming && (
              <button className="btn btn-secondary" style={{ padding: '0 1.5rem' }} onClick={stopStream}>
                중단
              </button>
            )}
          </div>
        </div>
      </section>

      {/* Results Section */}
      {(trace.length > 0 || answer || error) && (
        <section className="container mb-24" style={{ maxWidth: '48rem' }}>
          <div className="card text-left">
            
            {/* Agent Trace */}
            {trace.length > 0 && (
              <div className="mb-6 pb-6" style={{ borderBottom: '1px solid var(--border)' }}>
                <h4 className="text-sm font-medium text-muted-foreground mb-3 uppercase tracking-wide">Agent Trace</h4>
                <div className="flex flex-col gap-2">
                  {trace.map((step, idx) => (
                    <div key={idx} className="flex items-center gap-2 text-sm text-muted">
                      <span className="text-accent">▶</span>
                      <span className="font-mono text-xs bg-[var(--muted)] px-2 py-1 rounded">{step.node}</span>
                      <span>
                        {step.node === 'contextualize' && `질문을 독립 문장으로 정리`}
                        {step.node === 'router' && `${step.decision} 로 라우팅${step.method === 'rule' ? ' (규칙)' : ''}`}
                        {step.node === 'retriever' && `Found ${step.doc_count} documents`}
                        {step.node === 'grader' && `문서 ${step.kept + step.dropped}개 중 ${step.kept}개 채택`                          + (step.method === 'reranker' ? ' (리랭커)' : '')}
                        {step.node === 'question_rewriter' && `Rewrote question to refine search`}
                        {step.node === 'generator' && `Generating final answer`}
                      </span>
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
                  <p className="text-base font-semibold" style={{ color: '#f87171' }}>
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

      <section className="container features-section">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
          <div className="card flex flex-col items-start text-left">
            <div className="tag mb-5">수집</div>
            <h3 className="text-xl font-semibold mb-3">넣기 전에 확인</h3>
            <p className="text-muted text-sm" style={{ lineHeight: '1.6' }}>
              GitHub 레포·웹페이지·PDF를 색인합니다. 수집 전에 어떤 문서가 몇 청크로
              들어갈지 미리 보여주므로, 테스트 코드나 자동 생성 문서가 섞이는 것을 막습니다.
            </p>
          </div>

          <div className="card highlighted flex flex-col items-start text-left">
            <div className="tag mb-5" style={{ color: 'var(--accent)', border: '1px solid rgba(245, 158, 11, 0.2)' }}>에이전트</div>
            <h3 className="text-xl font-semibold mb-3">스스로 검증하는 검색</h3>
            <p className="text-muted text-sm" style={{ lineHeight: '1.6' }}>
              LangGraph 순환 그래프로 동작합니다. 검색 결과를 채점해 관련 없는 문서를 버리고,
              남는 게 없으면 질문을 고쳐 다시 검색합니다. 두 번까지 시도하고 멈춥니다.
            </p>
          </div>

          <div className="card flex flex-col items-start text-left">
            <div className="tag mb-5">구성</div>
            <h3 className="text-xl font-semibold mb-3">로컬 임베딩 + Gemini</h3>
            <p className="text-muted text-sm" style={{ lineHeight: '1.6' }}>
              임베딩은 BAAI/bge-m3로 로컬에서 처리해 수집에 API 비용이 들지 않습니다.
              답변 생성만 Gemini 2.5 Flash를 쓰고, 검색은 Pinecone이 맡습니다.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}

export default Home;
