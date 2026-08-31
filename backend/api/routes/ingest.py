from fastapi import APIRouter, HTTPException
from api.schemas import IngestRequest, IngestResponse
from store.vectorstore import get_vector_store_manager
import store.db as db
from ingest.pipeline import process_url
from ingest.loader import preview_github

router = APIRouter()

@router.post("/ingest", response_model=IngestResponse)
def ingest_document(req: IngestRequest):
    status, message, chunks_added = process_url(
        req.url, force=True,
        include_ext=req.include_ext, exclude_paths=req.exclude_paths,
    )
    if status == 'error':
        return IngestResponse(status="error", message=message)
    if status == 'partial':
        # 일부 배치가 실패했다. 성공으로 보고하면 사용자가 색인이 온전하다고 오해한다.
        return IngestResponse(status="partial", chunks_added=chunks_added,
                              source=req.url, message=message)
    # Even if status == 'skipped', when forced from UI, it will actually update. 
    # But since UI requests are 'force=True', it won't skip unless there's an error.
    return IngestResponse(status="ok", chunks_added=chunks_added, source=req.url, message=message)

@router.get("/ingest/preview")
def preview_document(url: str, include_ext: str = None, exclude_paths: str = None):
    """
    수집 전에 대상 레포에 무엇이 들어 있는지 확인한다.

    얕은 클론 -> 필터 -> 청킹까지만 수행하고 임베딩은 하지 않으므로 몇 초면 끝난다.
    문서를 이관해 마케팅 README 만 남은 레포를 그대로 수집하면
    검색이 그 문구를 물어오게 되므로, 넣기 전에 걸러내기 위한 것이다.
    """
    # 미리보기는 GitHub 레포에만 제공한다.
    # PDF/웹은 원본을 통째로 받아야 파일 수와 청크 수를 알 수 있고, 특히 웹 분기는
    # 그 과정에서 Gemini Vision 을 호출한다. "임베딩 없이 공짜로 미리 본다"는 전제가
    # 깨지므로 미리보기는 막되, 수집 자체는 정상 동작하므로 에러가 아니라 안내로 돌려준다.
    # 400 으로 던지면 화면에 빨간 에러가 떠서, 되는 기능이 안 되는 것처럼 보인다.
    if "github.com" not in url:
        kind = "PDF" if url.lower().endswith(".pdf") else "web page"
        return {
            "url": url,
            "preview_supported": False,
            "message": (
                f"Preview is available for GitHub repositories only. "
                f"This {kind} can still be ingested directly."
            ),
        }
    try:
        result = preview_github(
            url,
            include_exts=[x.strip() for x in include_ext.split(',')] if include_ext else None,
            excludes=[x.strip() for x in exclude_paths.split(',')] if exclude_paths else None,
        )
        result["preview_supported"] = True
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Preview failed: {e}")


@router.get("/docs")
def get_documents():
    return db.get_documents()

@router.delete("/docs")
def delete_document(url: str):
    get_vector_store_manager().delete_source(url)
    db.delete_document(url)
    return {"status": "ok", "message": f"Deleted {url}"}
