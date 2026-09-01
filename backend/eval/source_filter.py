"""
질문에서 대상 소스를 추정해 Pinecone 메타데이터 필터를 만든다.

키워드를 하드코딩하지 않는다. 문서를 추가하면 규칙이 저절로 따라와야 하기 때문이다.
색인된 소스 URL 에서 직접 뽑는다.

    https://github.com/vllm-project/vllm       -> {vllm}
    https://github.com/PrefectHQ/prefect       -> {prefect, prefecthq}
    https://github.com/langfuse/langfuse-docs  -> {langfuse}

판정 규칙
  · 정확히 한 소스만 매칭 -> 그 소스로 필터
  · 0개 또는 2개 이상     -> 필터 없음 (전체 검색)

두 개 이상일 때 필터를 걸지 않는 이유: "Prefect 와 Langfuse 를 비교해줘" 같은 질문에서
한쪽만 남기면 답이 반쪽이 된다. 애매하면 넓게 보는 쪽이 안전하다.
"""
import re
from urllib.parse import urlparse

# 소스를 구분하지 못하는 일반 단어
_STOP = {
    "docs", "doc", "documentation", "project", "projects", "main", "master",
    "api", "www", "com", "org", "io", "github", "repo", "core", "python",
}
_MIN_LEN = 4


def _keywords_for(url: str):
    """소스 URL 하나에서 검색 키워드 집합을 뽑는다."""
    path = urlparse(url).path.strip("/")
    if not path:
        return set()

    out = set()
    for segment in path.split("/")[:2]:          # org, repo 까지만 본다
        seg = segment.lower()
        candidates = {seg, *re.split(r"[-_.]", seg)}
        for c in candidates:
            if len(c) >= _MIN_LEN and c not in _STOP:
                out.add(c)
    return out


def build_index(source_urls):
    """{소스 URL: 키워드 집합} 을 만든다."""
    return {url: _keywords_for(url) for url in source_urls}


def route(question: str, index):
    """
    질문에 맞는 소스 URL 을 돌려준다. 판정하지 못하면 None.

    반환값이 None 이면 필터 없이 전체를 검색한다.
    """
    low = (question or "").lower()
    hits = []
    for url, keys in index.items():
        # 단어 경계로 본다. "prefect" 가 "prefecture" 에 걸리면 안 된다.
        if any(re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", low) for k in keys):
            hits.append(url)
    return hits[0] if len(hits) == 1 else None
