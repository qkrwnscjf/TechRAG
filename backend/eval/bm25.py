"""
BM25 Okapi 구현.

외부 의존성을 쓰지 않는 이유가 둘 있다.

1) 과거에 하이브리드 검색을 걷어낸 원인이 `pinecone-text` 의 BM25Encoder 였다.
   그것은 영어 코퍼스로 사전학습된 IDF 파라미터를 쓰기 때문에 이 코퍼스에서는
   가중치가 맞지 않았다. 여기서는 **실제 색인 코퍼스에서 IDF 를 직접 계산한다.**
   방식이 틀렸던 게 아니라 파라미터가 틀렸던 것이므로, 그 부분만 고친다.

2) 토큰화를 직접 제어해야 한다. 코퍼스는 영어 기술 문서이고 질문은 한국어다.
   형태소 분석기 없이 한국어를 다루려면 음절 n-gram 이 현실적인데,
   범용 라이브러리는 이 조합을 그대로 지원하지 않는다.

토큰화 규칙
  · 영문·숫자·밑줄 덩어리는 그대로 (`cache_policy`, `bge-m3` 의 `m3` 등)
  · 한글 덩어리는 음절 바이그램으로 (`캐시정책` -> `캐시`, `시정`, `정책`)
    한 글자 토큰은 변별력이 없어 버린다.
"""
import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9_]+|[가-힣]+")

K1 = 1.5   # 용어 빈도 포화 지점. 표준값
B = 0.75   # 문서 길이 정규화 강도. 표준값


def tokenize(text: str):
    out = []
    for tok in _TOKEN.findall(str(text).lower()):
        if "가" <= tok[0] <= "힣":
            # 한글: 음절 바이그램. 한 글자짜리는 버린다.
            if len(tok) == 1:
                continue
            out.extend(tok[i:i + 2] for i in range(len(tok) - 1))
        else:
            out.append(tok)
    return out


class BM25:
    def __init__(self, documents, k1=K1, b=B):
        """documents: 원문 문자열 리스트. 색인 순서가 곧 문서 id 다."""
        self.k1 = k1
        self.b = b
        self.docs = [tokenize(d) for d in documents]
        self.n = len(self.docs)
        self.lengths = [len(d) for d in self.docs]
        self.avg_len = (sum(self.lengths) / self.n) if self.n else 0.0
        self.freqs = [Counter(d) for d in self.docs]

        df = Counter()
        for f in self.freqs:
            df.update(f.keys())

        # Okapi IDF. 음수가 나오지 않도록 +1 을 둔다
        # (전체의 절반 이상에 나타나는 흔한 용어에서 음수가 되면 순위가 뒤집힌다).
        self.idf = {
            term: math.log(1 + (self.n - n_q + 0.5) / (n_q + 0.5))
            for term, n_q in df.items()
        }

    def scores(self, query: str):
        q = tokenize(query)
        out = [0.0] * self.n
        for term in q:
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, freq in enumerate(self.freqs):
                f = freq.get(term)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avg_len)
                out[i] += idf * (f * (self.k1 + 1)) / denom
        return out

    def top(self, query: str, k: int):
        sc = self.scores(query)
        idx = sorted(range(self.n), key=lambda i: -sc[i])[:k]
        return [(i, sc[i]) for i in idx if sc[i] > 0]


def rrf(rankings, k=60):
    """
    Reciprocal Rank Fusion. 서로 다른 검색기의 "순위" 만 쓴다.

    점수를 직접 더하지 않는 이유: dense 유사도(0~1)와 BM25 점수(0~수십)는
    척도가 달라서 정규화 방식에 따라 결과가 흔들린다. 순위만 쓰면 그 문제가 없다.
    k=60 은 원 논문의 기본값이다.

    rankings: [[doc_id, ...], [doc_id, ...]]  각 검색기의 상위 결과 (순위 순)
    """
    fused = {}
    for ranked in rankings:
        for rank, doc_id in enumerate(ranked, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(fused, key=lambda d: -fused[d])
