"""
Cross-encoder 리랭커.

검색 단계(bi-encoder)는 질문과 문서를 각각 따로 벡터로 만들어 비교하므로 빠르지만 정밀도가 낮다.
cross-encoder 는 (질문, 문서) 쌍을 함께 읽고 점수를 매겨 훨씬 정확하지만 그만큼 느리다.
그래서 "검색으로 후보를 넓게 뽑고(k=10~20) 리랭커로 좁힌다(top 4)" 는 2단계 구성을 쓴다.

기본값은 비활성이다. CPU 에서는 질문당 3~7초가 들어(측정치는 BENCHMARK.md 참고)
병렬화된 LLM grader(약 0.8초)보다 느리기 때문이다. GPU 가 있거나 정확도를 우선한다면
RERANKER_ENABLED=true 로 켠다.
"""
import logging
import threading
from typing import List, Tuple

from langchain_core.documents import Document
from config import settings, resolve_device

logger = logging.getLogger(__name__)

_model = None
_lock = threading.Lock()


def _get_model():
    """무거운 모델이므로 실제로 쓸 때 한 번만 로드한다."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import CrossEncoder
                logger.info("Loading reranker model: %s", settings.reranker_model)
                _model = CrossEncoder(settings.reranker_model, device=resolve_device(settings.reranker_device))
                _model.max_length = settings.reranker_max_length
    return _model


def is_enabled() -> bool:
    return bool(settings.reranker_enabled)


def rerank(question: str, docs: List[Document], top_k: int) -> Tuple[List[Document], List[float]]:
    """
    (질문, 문서) 쌍을 점수화해 상위 top_k 를 반환한다.

    주의: 이 모델의 원점수(logit)는 음수 영역에 넓게 퍼져 있고, sentence-transformers 의
    기본 Sigmoid 를 거치면 0.0003 같은 값으로 뭉개진다. 따라서 "점수 > 0.5" 류의
    절대 임계값은 쓸 수 없고 상대 순위로만 판단해야 한다.
    """
    if not docs:
        return [], []

    model = _get_model()
    pairs = [(question, d.page_content) for d in docs]
    scores = model.predict(pairs, batch_size=max(1, len(pairs)))

    ranked = sorted(zip(docs, scores), key=lambda x: float(x[1]), reverse=True)

    threshold = settings.reranker_score_threshold
    if threshold is not None:
        filtered = [(d, s) for d, s in ranked if float(s) >= threshold]
        # 전부 잘려나가면 재작성 루프가 돌도록 빈 목록을 그대로 돌려준다.
        ranked = filtered

    ranked = ranked[:top_k]
    return [d for d, _ in ranked], [float(s) for _, s in ranked]
