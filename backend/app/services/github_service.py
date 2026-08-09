"""
GitHub integration using PyGithub + Personal Access Token.

Features:
  - List repos for authenticated user
  - Get open issues & PRs per repo
  - Get recent commits per repo
  - Create a GitHub Issue from a task
"""

from typing import Optional
from app.core.config import settings


def _get_github():
    from github import Github, GithubException
    if not settings.GITHUB_PAT:
        raise ValueError("GITHUB_PAT not configured in .env")
    return Github(settings.GITHUB_PAT)


def is_connected() -> bool:
    return bool(settings.GITHUB_PAT)


def get_user_repos(limit: int = 30) -> list[dict]:
    """Return the user's non-forked repos, sorted by last push."""
    g    = _get_github()
    user = g.get_user()
    repos = []
    for repo in user.get_repos(sort="pushed", direction="desc")[:limit]:
        repos.append({
            "id":          repo.id,
            "name":        repo.name,
            "full_name":   repo.full_name,
            "description": repo.description,
            "private":     repo.private,
            "url":         repo.html_url,
            "stars":       repo.stargazers_count,
            "open_issues": repo.open_issues_count,
            "pushed_at":   repo.pushed_at.isoformat() if repo.pushed_at else None,
            "language":    repo.language,
        })
    return repos


def get_open_issues(repo_full_name: str, limit: int = 20) -> list[dict]:
    """Return open issues (excluding PRs) for a repo."""
    g    = _get_github()
    repo = g.get_repo(repo_full_name)
    issues = []
    for issue in repo.get_issues(state="open")[:limit]:
        if issue.pull_request:
            continue  # skip PRs — handled separately
        issues.append({
            "number":   issue.number,
            "title":    issue.title,
            "body":     issue.body,
            "state":    issue.state,
            "labels":   [l.name for l in issue.labels],
            "assignees":[a.login for a in issue.assignees],
            "url":      issue.html_url,
            "created":  issue.created_at.isoformat(),
            "updated":  issue.updated_at.isoformat(),
        })
    return issues


def get_open_prs(repo_full_name: str, limit: int = 20) -> list[dict]:
    """Return open pull requests for a repo."""
    g    = _get_github()
    repo = g.get_repo(repo_full_name)
    prs  = []
    for pr in repo.get_pulls(state="open", sort="updated", direction="desc")[:limit]:
        prs.append({
            "number":  pr.number,
            "title":   pr.title,
            "state":   pr.state,
            "author":  pr.user.login,
            "draft":   pr.draft,
            "url":     pr.html_url,
            "base":    pr.base.ref,
            "head":    pr.head.ref,
            "created": pr.created_at.isoformat(),
            "updated": pr.updated_at.isoformat(),
        })
    return prs


def get_recent_commits(repo_full_name: str, limit: int = 15) -> list[dict]:
    """Return recent commits on the default branch."""
    g    = _get_github()
    repo = g.get_repo(repo_full_name)
    commits = []
    for commit in repo.get_commits()[:limit]:
        commits.append({
            "sha":     commit.sha[:7],
            "message": commit.commit.message.split("\n")[0],   # first line only
            "author":  commit.commit.author.name,
            "date":    commit.commit.author.date.isoformat(),
            "url":     commit.html_url,
        })
    return commits


def create_issue_from_task(
    repo_full_name: str,
    title: str,
    body: str,
    labels: Optional[list[str]] = None,
) -> dict:
    """Push a task to GitHub as an issue. Returns the created issue."""
    g    = _get_github()
    repo = g.get_repo(repo_full_name)

    # Create labels that don't exist yet
    existing_labels = {l.name for l in repo.get_labels()}
    resolved_labels = []
    for label in (labels or []):
        if label in existing_labels:
            resolved_labels.append(repo.get_label(label))
        else:
            try:
                resolved_labels.append(repo.create_label(label, color="4f7cff"))
            except Exception:
                pass

    issue = repo.create_issue(
        title=title,
        body=body,
        labels=resolved_labels,
    )
    return {
        "number": issue.number,
        "title":  issue.title,
        "url":    issue.html_url,
    }
