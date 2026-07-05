from pydantic import BaseModel

class IngestRequest(BaseModel):
    url: str

class IngestResponse(BaseModel):
    status: str
    chunks_added: int = 0
    source: str = ""
    message: str = ""
