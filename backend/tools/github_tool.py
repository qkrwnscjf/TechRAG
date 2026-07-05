from github import Github
from config import settings

def get_github_client() -> Github:
    if settings.github_token:
        return Github(settings.github_token)
    return Github()

def get_repo_info(repo_name: str) -> str:
    """
    예: "langchain-ai/langchain" -> README + 최근 릴리즈 노트 1개 반환
    """
    gh = get_github_client()
    try:
        repo = gh.get_repo(repo_name)
        
        # Get README
        readme_content = ""
        try:
            readme = repo.get_readme()
            readme_content = f"### README\\n{readme.decoded_content.decode('utf-8')}"
        except Exception:
            readme_content = "No README found."

        # Get latest release
        release_content = ""
        try:
            releases = repo.get_releases()
            if releases.totalCount > 0:
                latest = releases[0]
                release_content = f"### Latest Release: {latest.title}\\n{latest.body}"
            else:
                release_content = "No releases found."
        except Exception:
            release_content = "Failed to fetch releases."

        return f"# {repo_name}\\n\\n{readme_content}\\n\\n{release_content}"
    except Exception as e:
        return f"Error fetching repo info: {e}"

def search_issues(repo_name: str, query: str, limit: int = 5) -> list[dict]:
    """
    이슈 제목 + 본문 상위 limit 개 반환
    """
    gh = get_github_client()
    try:
        # Search syntax: "query repo:owner/name type:issue"
        full_query = f"{query} repo:{repo_name} type:issue"
        issues = gh.search_issues(full_query)
        
        results = []
        for i, issue in enumerate(issues):
            if i >= limit:
                break
            results.append({
                "title": issue.title,
                "body": issue.body or "",
                "url": issue.html_url,
                "state": issue.state
            })
        return results
    except Exception as e:
        print(f"Error searching issues: {e}")
        return []
