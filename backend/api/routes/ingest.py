from fastapi import APIRouter, HTTPException
from api.schemas import IngestRequest, IngestResponse
from store.vectorstore import vector_store_manager
import store.db as db
from ingest.pipeline import process_url

router = APIRouter()

@router.post("/ingest", response_model=IngestResponse)
def ingest_document(req: IngestRequest):
    status, message, chunks_added = process_url(req.url, force=True)
    if status == 'error':
        return IngestResponse(status="error", message=message)
    # Even if status == 'skipped', when forced from UI, it will actually update. 
    # But since UI requests are 'force=True', it won't skip unless there's an error.
    return IngestResponse(status="ok", chunks_added=chunks_added, source=req.url, message=message)

@router.get("/docs")
def get_documents():
    return db.get_documents()

@router.delete("/docs")
def delete_document(url: str):
    vector_store_manager.delete_source(url)
    db.delete_document(url)
    return {"status": "ok", "message": f"Deleted {url}"}
