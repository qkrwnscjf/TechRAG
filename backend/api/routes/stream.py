import json
import logging
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from langchain_core.messages import HumanMessage, AIMessageChunk
from agent.graph import get_graph

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_THREAD_ID = "user_session_1"


@router.get("/stream")
async def stream_agent(q: str, request: Request, thread_id: str = DEFAULT_THREAD_ID):
    """
    EventSource로 스트리밍 반환.
    trace, chunk, token, sources, done, error 이벤트를 보냄.

    LangGraph 를 두 가지 stream_mode 로 동시에 구독한다.
      - "updates"  : 노드가 끝날 때마다 상태 변화 -> trace / chunk / sources 이벤트
      - "messages" : LLM 이 토큰을 뱉는 즉시 -> token 이벤트

    이전 구현은 generator 노드가 "완전히 끝난 뒤" 완성된 문자열을 한 글자씩
    0.01초 간격으로 흘려보내 스트리밍을 흉내냈다. 그 방식은 답변 길이에 비례해
    순수한 대기시간을 더했고(1,000자 = +10초), 첫 글자가 보이기까지도
    파이프라인 전체가 끝나기를 기다려야 했다. 아래는 실제 토큰 스트리밍이다.
    """

    async def event_generator():
        try:
            state_input = {
                "question": q,
                "rewrite_count": 0,
                "trace": [],
                "messages": [HumanMessage(content=q)],
            }
            config = {"configurable": {"thread_id": thread_id}}

            graph = await get_graph()
            async for mode, payload in graph.astream(
                state_input, config=config, stream_mode=["updates", "messages"]
            ):
                if await request.is_disconnected():
                    logger.info("Client disconnected, aborting stream.")
                    break

                # ---- LLM 토큰: 생성되는 즉시 전달 ----
                if mode == "messages":
                    message_chunk, metadata = payload
                    # generator 노드의 출력만 사용자에게 보낸다.
                    # (router/grader/rewriter 도 LLM을 쓰지만 내부 판단용이다.)
                    if metadata.get("langgraph_node") != "generator":
                        continue
                    # messages 모드는 LLM 이 흘리는 조각(AIMessageChunk)뿐 아니라
                    # 노드가 state["messages"] 에 append 한 완성본(AIMessage)까지 내보낸다.
                    # 둘 다 전달하면 답변이 두 번 출력되므로 조각만 골라낸다.
                    if not isinstance(message_chunk, AIMessageChunk):
                        continue
                    text = getattr(message_chunk, "content", "")
                    if text:
                        yield {"event": "token", "data": json.dumps({"text": text})}
                    continue

                # ---- 노드 단위 상태 변화 ----
                for node_name, node_state in payload.items():
                    if not isinstance(node_state, dict):
                        continue

                    trace = node_state.get("trace", [])
                    if trace:
                        yield {"event": "trace", "data": json.dumps(trace[-1])}

                    if node_name == "retriever":
                        for doc in node_state.get("documents", []):
                            yield {
                                "event": "chunk",
                                "data": json.dumps({
                                    "content": doc.page_content,
                                    "source": doc.metadata.get("source", ""),
                                }),
                            }

                    if node_name == "generator":
                        sources = trace[-1].get("sources", []) if trace else []
                        yield {
                            "event": "sources",
                            "data": json.dumps({
                                "sources": [{"url": s, "title": s} for s in sources]
                            }),
                        }

            yield {"event": "done", "data": json.dumps({})}

        except Exception as e:
            logger.exception("Stream failed for question: %s", q)
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
            yield {"event": "done", "data": json.dumps({})}

    return EventSourceResponse(event_generator())
