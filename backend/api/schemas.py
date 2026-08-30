from typing import Optional

from pydantic import BaseModel

class IngestRequest(BaseModel):
    url: str
    # 수집 필터를 요청마다 지정할 수 있다. 생략하면 이 문서가 이전에 쓴 필터,
    # 그것도 없으면 전역 설정(.env)을 쓴다.
    # 레포마다 버려야 할 경로가 다르므로(.env 를 갈아끼우지 않기 위한 장치),
    # 예: include_ext=".md,.mdx", exclude_paths="api-ref,release-notes,plans/"
    include_ext: Optional[str] = None
    exclude_paths: Optional[str] = None

class IngestResponse(BaseModel):
    status: str
    chunks_added: int = 0
    source: str = ""
    message: str = ""
