import os
import tempfile
import urllib.parse
import shutil
from datetime import datetime
from typing import List
from langchain_core.documents import Document
from langchain_community.document_loaders import WebBaseLoader, PyMuPDFLoader
from langchain_community.document_loaders.git import GitLoader

def load_from_url(url: str) -> List[Document]:
    """
    - github.com -> GitLoader
    - .pdf -> PyMuPDFLoader
    - 그 외 -> WebBaseLoader
    """
    docs = []
    parsed_url = urllib.parse.urlparse(url)
    now_str = datetime.now().isoformat()

    if "github.com" in parsed_url.netloc:
        temp_dir = tempfile.mkdtemp()
        try:
            # 기본 브랜치(main) 시도
            loader = GitLoader(
                clone_url=url,
                repo_path=temp_dir,
                branch="main",
                file_filter=lambda file_path: file_path.endswith(".md")
            )
            docs = loader.load()
        except Exception:
            # 실패 시 master 시도
            loader = GitLoader(
                clone_url=url,
                repo_path=temp_dir,
                branch="master",
                file_filter=lambda file_path: file_path.endswith(".md")
            )
            docs = loader.load()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            
    elif url.lower().endswith(".pdf"):
        loader = PyMuPDFLoader(url)
        docs = loader.load()
    else:
        loader = WebBaseLoader(url)
        docs = loader.load()
        
    for doc in docs:
        doc.metadata["source"] = url
        doc.metadata["loaded_at"] = now_str
        
    return docs
