import os
import json
import pathlib
import logging
import tempfile
import urllib.parse
import shutil
import base64
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime
from typing import List

from langchain_core.documents import Document
from langchain_community.document_loaders import WebBaseLoader, PyMuPDFLoader
from langchain_community.document_loaders.git import GitLoader
from git import Repo
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from config import settings, get_md_excludes, get_include_exts

logger = logging.getLogger(__name__)

# Initialize Vision LLM
vision_llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.1,
    google_api_key=settings.google_api_key,
    max_retries=2
)

def describe_image(image_url: str, base_url: str) -> str:
    """다운로드 후 base64로 인코딩하여 Gemini Vision에 분석 요청"""
    try:
        img_url = urljoin(base_url, image_url)
        # 텔레메트리 픽셀이나 아이콘 제외를 위해 특정 확장자 필터링
        if img_url.endswith('.svg') or img_url.endswith('.gif'):
            return ""
            
        resp = requests.get(img_url, timeout=5)
        resp.raise_for_status()
        
        # 너무 작은 이미지(아이콘 등, 5KB 미만)는 무시
        if len(resp.content) < 5000:
            return ""
            
        content_type = resp.headers.get('Content-Type', 'image/jpeg')
        b64_data = base64.b64encode(resp.content).decode('utf-8')
        
        msg = HumanMessage(
            content=[
                {"type": "text", "text": "이 이미지(다이어그램, 아키텍처, 캡처 화면, 또는 코드 스니펫)의 내용을 기술 문서 관점에서 상세히 설명해 줘. 안에 적힌 텍스트나 핵심 구조를 빠짐없이 글로 작성해."},
                {"type": "image_url", "image_url": f"data:{content_type};base64,{b64_data}"}
            ]
        )
        res = vision_llm.invoke([msg])
        return res.content
    except Exception as e:
        print(f"Vision API error on {image_url}: {e}")
        return ""


def notebook_to_text(raw: str) -> str:
    """
    주피터 노트북(.ipynb)을 검색 가능한 텍스트로 재조립한다.

    노트북은 마크다운이 아니라 JSON 이다. 원문을 그대로 임베딩하면 실행 결과에 들어 있는
    base64 이미지(그래프 하나가 100KB 를 넘기도 한다), 트레이스백, 반복되는 stdout 이
    청크를 가득 채워 인덱스를 오염시킨다. 그래서 outputs 는 통째로 버리고
    설명(markdown)과 코드(code)만 남긴다.
    """
    nb = json.loads(raw)
    parts = []
    for cell in nb.get("cells", []):
        src = cell.get("source", "")
        if isinstance(src, list):
            src = "".join(src)
        src = (src or "").strip()
        if not src:
            continue
        kind = cell.get("cell_type")
        if kind == "markdown":
            parts.append(src)
        elif kind == "code":
            # 코드 펜스를 붙이면 chunker 가 코드용 800자 splitter 로 자동 분기한다.
            parts.append(f"```python\n{src}\n```")
        # outputs / execution_count / metadata 는 의도적으로 버린다.
    return "\n\n".join(parts)



def _build_file_filter(include_exts=None, excludes=None):
    """
    GitHub 레포에서 수집할 파일을 고르는 필터.

    실제 수집(load_from_url)과 미리보기(preview_github)가 **같은 기준**을 써야
    미리보기가 의미를 갖는다. 그래서 한 곳에서만 정의한다.

    include_exts / excludes 를 넘기면 전역 설정 대신 그것을 쓴다.
    수집 필터는 레포마다 달라야 하는데 설정은 전역 하나뿐이라, 호출 시점에
    문서별 필터를 주입할 수 있어야 한다. (pipeline 이 저장된 필터를 넘긴다.)
    """
    excludes = get_md_excludes() if excludes is None else excludes
    include_exts = get_include_exts() if include_exts is None else include_exts

    def _keep(file_path: str) -> bool:
        lowered = file_path.lower()
        if not any(lowered.endswith(e) for e in include_exts):
            return False
        return not any(x and x in file_path for x in excludes)

    return _keep


def _shallow_clone(url: str, dest: str):
    """최신 스냅샷만 받고 (repo, 기본 브랜치명) 을 돌려준다."""
    repo = Repo.clone_from(url, dest, depth=1)
    try:
        branch = repo.active_branch.name
    except TypeError:
        branch = repo.head.commit.hexsha   # detached HEAD
    return repo, branch


def preview_github(url: str, sample_n: int = 6, include_exts=None, excludes=None) -> dict:
    """
    수집하지 않고 대상 문서를 미리 확인한다.

    임베딩과 LLM 호출 없이 얕은 클론 -> 필터 -> 청킹까지만 수행하므로 몇 초면 끝난다.
    청크 수는 어림이 아니라 실제 청커를 돌린 값이다.

    레포에 쓸만한 문서가 실제로 있는지(마케팅 README 만 남았는지) 넣기 전에 판단하기 위한 것.
    """
    from ingest.chunker import chunk_documents

    keep = _build_file_filter(include_exts, excludes)
    temp_dir = tempfile.mkdtemp()
    try:
        _, branch = _shallow_clone(url, temp_dir)

        picked = []
        for root, dirs, names in os.walk(temp_dir):
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in names:
                abs_path = os.path.join(root, name)
                rel = os.path.relpath(abs_path, temp_dir)
                if not keep(rel):
                    continue
                try:
                    text = pathlib.Path(abs_path).read_text(encoding="utf-8")
                except Exception:
                    continue   # 디코딩 실패 파일은 실제 수집에서도 제외된다
                picked.append((rel, text))

        picked.sort(key=lambda x: -len(x[1]))

        docs = [
            Document(page_content=t,
                     metadata={"source": url, "file_type": os.path.splitext(r)[1]})
            for r, t in picked
        ]
        chunks = chunk_documents(docs) if docs else []

        return {
            "url": url,
            "branch": branch,
            "files": len(picked),
            "total_chars": sum(len(t) for _, t in picked),
            "chunks": len(chunks),
            "largest_files": [
                {"path": r, "chars": len(t), "head": t.strip()[:180]}
                for r, t in picked[:sample_n]
            ],
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def load_from_url(url: str, include_exts=None, excludes=None) -> List[Document]:
    """
    - github.com -> GitLoader
    - .pdf -> PyMuPDFLoader
    - 그 외 -> WebBaseLoader + Multi-modal Image Analysis
    """
    docs = []
    parsed_url = urllib.parse.urlparse(url)
    now_str = datetime.now().isoformat()

    if "github.com" in parsed_url.netloc:
        _keep = _build_file_filter(include_exts, excludes)

        temp_dir = tempfile.mkdtemp()
        try:
            # GitLoader 에 clone_url 을 넘기면 내부에서 전체 커밋 이력을 클론한다.
            # 문서 수집에는 최신 스냅샷만 있으면 되므로 depth=1 로 직접 클론하고,
            # GitLoader 에는 이미 받아둔 로컬 경로만 넘긴다. 큰 레포일수록 차이가 크다.
            #
            # 브랜치를 직접 지정하지도 않는다. 이전 구현은 "main" 을 시도하고 실패하면
            # "master" 를 다시 시도했는데, 그러면 (1) 전체 클론이 두 번 일어나고
            # (2) 기본 브랜치가 develop/trunk 인 레포는 두 번 다 실패했다.
            # clone 은 원격의 기본 브랜치를 알아서 받아오므로, 받은 뒤 이름을 읽어 쓴다.
            _, branch = _shallow_clone(url, temp_dir)
            logger.info("Cloned %s (branch=%s, depth=1)", url, branch)

            loader = GitLoader(repo_path=temp_dir, branch=branch, file_filter=_keep)
            docs = loader.load()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        # GitLoader 는 파일 내용을 원문 그대로 싣는다. .ipynb 는 JSON 이므로 여기서 변환한다.
        # metadata["source"] 는 아래에서 URL 로 덮어써지므로, 확장자는 file_type 으로 판별한다.
        kept = []
        skipped = 0
        for doc in docs:
            if doc.metadata.get("file_type", "").lower() == ".ipynb":
                try:
                    text = notebook_to_text(doc.page_content)
                except Exception as e:
                    logger.warning("노트북 파싱 실패, 건너뜁니다: %s (%s)",
                                   doc.metadata.get("file_path"), e)
                    skipped += 1
                    continue
                if not text.strip():
                    skipped += 1
                    continue
                doc.page_content = text
            kept.append(doc)
        if skipped:
            logger.info("노트북 %d개를 건너뛰었습니다 (파싱 실패 또는 내용 없음)", skipped)
        docs = kept
            
    elif url.lower().endswith(".pdf"):
        loader = PyMuPDFLoader(url)
        docs = loader.load()
    else:
        loader = WebBaseLoader(url)
        docs = loader.load()
        
        # --- Multi-Modal Image Analysis ---
        try:
            resp = requests.get(url, timeout=10)
            soup = BeautifulSoup(resp.text, 'html.parser')
            img_tags = soup.find_all('img')
            
            img_descriptions = []
            count = 0
            for img in img_tags:
                if count >= 3: # 비용 및 시간 낭비 방지를 위해 문서당 최대 3개의 주요 이미지만 분석
                    break
                src = img.get('src') or img.get('data-src')
                if src and not src.startswith('data:'):
                    desc = describe_image(src, url)
                    if desc:
                        img_descriptions.append(f"[Diagram/Image Analysis]:\n{desc}")
                        count += 1
                        
            if img_descriptions:
                # 추출한 이미지 텍스트 설명을 문서 끝에 추가 (Vector DB가 함께 임베딩하도록)
                for doc in docs:
                    doc.page_content += "\n\n--- 첨부 이미지 분석 ---\n\n" + "\n\n".join(img_descriptions)
                    
        except Exception as e:
            print(f"Error processing images for {url}: {e}")
        
    for doc in docs:
        doc.metadata["source"] = url
        doc.metadata["loaded_at"] = now_str
        
    return docs
