import json
import asyncio
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from agent.graph import graph

router = APIRouter()

@router.get("/stream")
async def stream_agent(q: str, request: Request):
    """
    EventSource로 스트리밍 반환.
    trace, token, chunk, sources 이벤트를 보냄.
    """
    async def event_generator():
        try:
            state = {"question": q, "rewrite_count": 0, "trace": []}
            
            async for output in graph.astream(state):
                if await request.is_disconnected():
                    break
                    
                for node_name, node_state in output.items():
                    trace = node_state.get("trace", [])
                    if trace:
                        new_trace = trace[-1]
                        yield {
                            "event": "trace",
                            "data": json.dumps(new_trace)
                        }
                    
                    if node_name == "retriever":
                        docs = node_state.get("documents", [])
                        for doc in docs:
                            yield {
                                "event": "chunk",
                                "data": json.dumps({
                                    "content": doc.page_content,
                                    "source": doc.metadata.get("source", "")
                                })
                            }
                            
                    if node_name == "generator":
                        generation = node_state.get("generation", "")
                        for char in generation:
                            yield {
                                "event": "token",
                                "data": json.dumps({"text": char})
                            }
                            await asyncio.sleep(0.01)
                            
                        sources = trace[-1].get("sources", []) if trace else []
                        yield {
                            "event": "sources",
                            "data": json.dumps({"sources": [{"url": s, "title": s} for s in sources]})
                        }

            yield {"event": "done", "data": json.dumps({})}
            
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
            yield {"event": "done", "data": json.dumps({})}

    return EventSourceResponse(event_generator())
