import React, { useState } from 'react';
import { useAgentStream } from '../hooks/useAgentStream';

function Home() {
  const [query, setQuery] = useState('');
  const { trace, chunks, answer, sources, isStreaming, askQuestion } = useAgentStream();

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
            <span>v1.0.0-beta</span>
          </div>
          <h1 className="text-5xl md:text-6xl lg:text-7xl mb-6 font-bold" style={{ letterSpacing: '-0.03em', lineHeight: '1.2' }}>
            Ask your codebase <br/>
            <span className="text-accent">anything.</span>
          </h1>
          <p className="text-xl text-muted mb-10" style={{ maxWidth: '42rem', lineHeight: '1.6' }}>
            Autonomous RAG agent that searches, evaluates, and understands your technical documentation to provide exact answers.
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
          </div>
        </div>
      </section>

      {/* Results Section */}
      {(trace.length > 0 || answer) && (
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
                        {step.node === 'router' && `Routed to ${step.decision}`}
                        {step.node === 'retriever' && `Found ${step.doc_count} documents`}
                        {step.node === 'grader' && `Kept ${step.kept}, Dropped ${step.dropped}`}
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
              {answer ? (
                <p className="text-base text-foreground leading-relaxed whitespace-pre-wrap">
                  {answer}
                </p>
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
            <div className="tag mb-5">Ingest</div>
            <h3 className="text-xl font-semibold mb-3">Automated Indexing</h3>
            <p className="text-muted text-sm" style={{ lineHeight: '1.6' }}>
              Connect your GitHub repos, website docs, or PDF files. The agent automatically chunks and vectorizes your data.
            </p>
          </div>
          
          <div className="card highlighted flex flex-col items-start text-left">
            <div className="tag mb-5" style={{ color: 'var(--accent)', border: '1px solid rgba(245, 158, 11, 0.2)' }}>Agentic</div>
            <h3 className="text-xl font-semibold mb-3">Self-Reflective RAG</h3>
            <p className="text-muted text-sm" style={{ lineHeight: '1.6' }}>
              Built with LangGraph. It evaluates its own search results and automatically rewrites queries if needed.
            </p>
          </div>
          
          <div className="card flex flex-col items-start text-left">
            <div className="tag mb-5">Cloud Native RAG</div>
            <h3 className="text-xl font-semibold mb-3">Gemini & Pinecone</h3>
            <p className="text-muted text-sm" style={{ lineHeight: '1.6' }}>
              Runs on Google's Gemini 2.5 Flash, with local HuggingFace embeddings and Pinecone Vector DB. Maximum performance and seamless scalability.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}

export default Home;
