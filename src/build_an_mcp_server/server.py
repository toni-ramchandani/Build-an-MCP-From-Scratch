#!/usr/bin/env python3

import json
import os
from typing import Any, Optional

import requests
from dotenv import find_dotenv, load_dotenv
from github import GithubException
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base
from playwright.async_api import TimeoutError as PWTimeoutError

from .browser_utils import close_page, get_page, new_page, page_screenshot_base64
from .fs_utils import (
    list_directory as fs_list_directory,
    read_file_text,
    resolve_and_validate,
)
from .github_utils import (
    fetch_open_issues,
    fetch_repository_metadata,
    get_github_client,
)

# Load environment variables - search up the directory tree for .env file
load_dotenv(find_dotenv(usecwd=True))

mcp = FastMCP("Build an MCP from Scratch")


# ---------------------------------------------------------------------------
# Filesystem MCP – Resources & Tools
# ---------------------------------------------------------------------------

@mcp.resource("file:///{file_path}")
def get_file(file_path: str) -> str:
    """Return text content of a file within allowed directories.

    If the file exceeds the inline limit, the output will be truncated with a
    notice. Binary data is decoded using UTF-8 with replacement of undecodable
    bytes, ensuring the response is always valid UTF-8.
    """
    try:
        return read_file_text(file_path)
    except (ValueError, OSError):
        return "Unable to read the requested file."


@mcp.tool()
def read_file(path: str) -> dict[str, object]:
    """Read text content of *path* and return it inside a JSON envelope."""
    try:
        content = read_file_text(path)
        return {
            "ok": True,
            "path": path,
            "content": content,
        }
    except (ValueError, OSError):
        return {
            "ok": False,
            "path": path,
            "error": "Unable to read the requested file.",
        }


@mcp.tool()
def write_file(path: str, content: str, overwrite: bool = True) -> dict[str, object]:
    """Write *content* to *path*.

    If *overwrite* is False and the file exists, the operation will fail.
    """
    try:
        p = resolve_and_validate(path)
        if p.exists() and not overwrite:
            return {
                "ok": False,
                "path": path,
                "error": "File exists and overwrite is False",
            }

        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {
            "ok": True,
            "path": str(p),
            "bytes_written": len(content),
        }
    except (ValueError, OSError) as exc:
        return {
            "ok": False,
            "path": path,
            "error": str(exc),
        }


@mcp.tool()
def list_directory(path: str = ".") -> dict[str, object]:
    """Return names and types of entries in *path*."""
    try:
        entries = fs_list_directory(path)
        return {
            "ok": True,
            "path": path,
            "entries": entries,
        }
    except (ValueError, OSError) as exc:
        return {
            "ok": False,
            "path": path,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# GitHub MCP – Resources & Tools
# ---------------------------------------------------------------------------

@mcp.resource("github://repos/{owner}/{repo}")
async def get_repository(owner: str, repo: str) -> str:
    """Return structured metadata for a GitHub repository."""
    try:
        repo_data = await fetch_repository_metadata(owner, repo)
        return json.dumps(repo_data, indent=2)
    except ValueError:
        return "GitHub data could not be retrieved."


@mcp.resource("github://repos/{owner}/{repo}/issues")
async def get_repository_issues(owner: str, repo: str) -> str:
    """Return a structured list of open GitHub issues."""
    try:
        issues = await fetch_open_issues(owner, repo, limit=10)

        issues_data = []
        for issue in issues:
            issues_data.append(
                {
                    "number": issue["number"],
                    "title": issue["title"],
                    "state": issue["state"],
                    "user": issue["user"],
                    "created_at": issue["created_at"],
                    "updated_at": issue["updated_at"],
                    "html_url": issue["html_url"],
                    "body": issue["body"][:500] if issue.get("body") else None,
                }
            )

        return json.dumps(issues_data, indent=2)
    except ValueError:
        return "GitHub issues could not be retrieved."


@mcp.tool()
def search_repositories(
    query: str,
    sort: str = "stars",
    order: str = "desc",
) -> dict[str, Any]:
    """Search for repositories on GitHub."""
    try:
        github = get_github_client()
        repos = github.search_repositories(query=query, sort=sort, order=order)

        results = []
        for repo in repos[:10]:
            results.append(
                {
                    "name": repo.name,
                    "full_name": repo.full_name,
                    "description": repo.description,
                    "html_url": repo.html_url,
                    "stargazers_count": repo.stargazers_count,
                    "language": repo.language,
                    "updated_at": repo.updated_at.isoformat(),
                }
            )

        return {
            "total_count": repos.totalCount,
            "repositories": results,
        }
    except GithubException as exc:
        return {"error": f"Search failed: {exc.data.get('message', str(exc))}"}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def get_repository_info(owner: str, repo: str) -> dict[str, Any]:
    """Get detailed information about a repository."""
    try:
        github = get_github_client()
        repository = github.get_repo(f"{owner}/{repo}")

        return {
            "name": repository.name,
            "full_name": repository.full_name,
            "description": repository.description,
            "private": repository.private,
            "html_url": repository.html_url,
            "clone_url": repository.clone_url,
            "ssh_url": repository.ssh_url,
            "language": repository.language,
            "stargazers_count": repository.stargazers_count,
            "watchers_count": repository.watchers_count,
            "forks_count": repository.forks_count,
            "open_issues_count": repository.open_issues_count,
            "default_branch": repository.default_branch,
            "created_at": repository.created_at.isoformat(),
            "updated_at": repository.updated_at.isoformat(),
            "pushed_at": repository.pushed_at.isoformat() if repository.pushed_at else None,
            "size": repository.size,
            "topics": repository.get_topics(),
            "license": repository.license.name if repository.license else None,
        }
    except GithubException as exc:
        return {"error": f"Repository not found: {exc.data.get('message', str(exc))}"}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def list_repository_issues(
    owner: str,
    repo: str,
    state: str = "open",
    labels: Optional[str] = None,
) -> dict[str, Any]:
    """List issues for a repository."""
    try:
        github = get_github_client()
        repository = github.get_repo(f"{owner}/{repo}")

        kwargs: dict[str, Any] = {"state": state}
        if labels:
            kwargs["labels"] = labels.split(",")

        issues = repository.get_issues(**kwargs)

        issues_data = []
        for issue in issues[:20]:
            issues_data.append(
                {
                    "number": issue.number,
                    "title": issue.title,
                    "state": issue.state,
                    "user": issue.user.login,
                    "assignees": [assignee.login for assignee in issue.assignees],
                    "labels": [label.name for label in issue.labels],
                    "created_at": issue.created_at.isoformat(),
                    "updated_at": issue.updated_at.isoformat(),
                    "html_url": issue.html_url,
                    "body": issue.body[:1000] if issue.body else None,
                }
            )

        return {
            "repository": f"{owner}/{repo}",
            "issues": issues_data,
        }
    except GithubException as exc:
        return {"error": f"Failed to list issues: {exc.data.get('message', str(exc))}"}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def get_issue_details(owner: str, repo: str, issue_number: int) -> dict[str, Any]:
    """Get detailed information about a specific issue."""
    try:
        github = get_github_client()
        repository = github.get_repo(f"{owner}/{repo}")
        issue = repository.get_issue(issue_number)

        return {
            "number": issue.number,
            "title": issue.title,
            "state": issue.state,
            "user": issue.user.login,
            "assignees": [assignee.login for assignee in issue.assignees],
            "labels": [label.name for label in issue.labels],
            "milestone": issue.milestone.title if issue.milestone else None,
            "created_at": issue.created_at.isoformat(),
            "updated_at": issue.updated_at.isoformat(),
            "closed_at": issue.closed_at.isoformat() if issue.closed_at else None,
            "html_url": issue.html_url,
            "body": issue.body,
            "comments": issue.comments,
            "repository": f"{owner}/{repo}",
        }
    except GithubException as exc:
        return {"error": f"Issue not found: {exc.data.get('message', str(exc))}"}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def list_pull_requests(owner: str, repo: str, state: str = "open") -> dict[str, Any]:
    """List pull requests for a repository."""
    try:
        github = get_github_client()
        repository = github.get_repo(f"{owner}/{repo}")
        pulls = repository.get_pulls(state=state)

        pulls_data = []
        for pr in pulls[:20]:
            pulls_data.append(
                {
                    "number": pr.number,
                    "title": pr.title,
                    "state": pr.state,
                    "user": pr.user.login,
                    "head": {
                        "ref": pr.head.ref,
                        "sha": pr.head.sha,
                    },
                    "base": {
                        "ref": pr.base.ref,
                        "sha": pr.base.sha,
                    },
                    "created_at": pr.created_at.isoformat(),
                    "updated_at": pr.updated_at.isoformat(),
                    "html_url": pr.html_url,
                    "mergeable": pr.mergeable,
                    "draft": pr.draft,
                }
            )

        return {
            "repository": f"{owner}/{repo}",
            "pull_requests": pulls_data,
        }
    except GithubException as exc:
        return {"error": f"Failed to list pull requests: {exc.data.get('message', str(exc))}"}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def get_user_info(username: str) -> dict[str, Any]:
    """Get information about a GitHub user."""
    try:
        github = get_github_client()
        user = github.get_user(username)

        return {
            "login": user.login,
            "name": user.name,
            "email": user.email,
            "bio": user.bio,
            "company": user.company,
            "location": user.location,
            "blog": user.blog,
            "html_url": user.html_url,
            "public_repos": user.public_repos,
            "public_gists": user.public_gists,
            "followers": user.followers,
            "following": user.following,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat(),
            "type": user.type,
        }
    except GithubException as exc:
        return {"error": f"User not found: {exc.data.get('message', str(exc))}"}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Browser Automation MCP – Tools powered by Playwright
# ---------------------------------------------------------------------------

@mcp.tool()
async def browser_open_page(
    url: str,
    wait_until: str = "domcontentloaded",
    timeout_ms: int = 15000,
) -> dict[str, Any]:
    """Open *url* in a new headless Chromium tab and return the page ID."""
    try:
        pid = await new_page()
        page = await get_page(pid)

        actual_timeout = min(timeout_ms, 12000)
        await page.goto(url, wait_until=wait_until, timeout=actual_timeout)

        title = await page.title()
        current_url = page.url

        return {
            "page_id": pid,
            "url": current_url,
            "title": title,
            "status": "success",
            "wait_condition": wait_until,
        }
    except PWTimeoutError:
        return {
            "page_id": pid if "pid" in locals() else None,
            "url": url,
            "error": f"Navigation timeout after {actual_timeout}ms. Use browser_get_page_info to check if page loaded.",
            "status": "timeout",
            "suggestion": "Try 'domcontentloaded' wait condition for faster loading",
        }
    except Exception as exc:
        return {
            "error": str(exc),
            "status": "error",
        }


@mcp.tool()
async def browser_close_page(page_id: str) -> dict[str, Any]:
    """Close a browser page by page ID."""
    try:
        await close_page(page_id)
        return {"status": "closed", "page_id": page_id}
    except KeyError:
        return {"error": f"Unknown page_id '{page_id}'"}


@mcp.tool()
async def browser_get_page_info(page_id: str) -> dict[str, Any]:
    """Get current information about a browser page."""
    try:
        page = await get_page(page_id)
        title = await page.title()
        url = page.url
        ready_state = await page.evaluate("document.readyState")

        return {
            "page_id": page_id,
            "url": url,
            "title": title,
            "ready_state": ready_state,
            "status": "success",
        }
    except Exception as exc:
        return {"error": str(exc), "status": "error"}


@mcp.tool()
async def browser_health_check() -> dict[str, Any]:
    """Quick health check to verify browser automation is working."""
    try:
        pid = await new_page()
        page = await get_page(pid)
        await page.goto("data:text/html,<h1>Browser Test</h1>", timeout=5000)
        title = await page.title()
        await close_page(pid)

        return {
            "status": "healthy",
            "message": "Browser automation is working correctly",
            "test_title": title,
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "message": "Browser automation is not working",
        }


@mcp.tool()
async def browser_click(page_id: str, selector: str, timeout_ms: int = 10000) -> dict[str, Any]:
    """Click an element on the page."""
    try:
        page = await get_page(page_id)
        await page.click(selector, timeout=timeout_ms)
        return {"clicked": selector, "page_id": page_id}
    except KeyError:
        return {"error": f"Unknown page_id '{page_id}'"}
    except PWTimeoutError:
        return {"error": f"Timeout waiting for selector '{selector}'"}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def browser_fill(
    page_id: str,
    selector: str,
    text: str,
    timeout_ms: int = 10000,
    clear: bool = True,
) -> dict[str, Any]:
    """Fill or type into an element."""
    try:
        page = await get_page(page_id)
        if clear:
            await page.fill(selector, text, timeout=timeout_ms)
        else:
            await page.type(selector, text, timeout=timeout_ms)

        return {"filled": selector, "text": text, "page_id": page_id}
    except KeyError:
        return {"error": f"Unknown page_id '{page_id}'"}
    except PWTimeoutError:
        return {"error": f"Timeout waiting for selector '{selector}'"}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def browser_get_text(page_id: str, selector: str, timeout_ms: int = 10000) -> dict[str, Any]:
    """Get text content from an element."""
    try:
        page = await get_page(page_id)
        await page.wait_for_selector(selector, timeout=timeout_ms)
        text = await page.inner_text(selector)
        return {"text": text, "selector": selector, "page_id": page_id}
    except KeyError:
        return {"error": f"Unknown page_id '{page_id}'"}
    except PWTimeoutError:
        return {"error": f"Timeout waiting for selector '{selector}'"}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def browser_screenshot(page_id: str, full_page: bool = False) -> dict[str, Any]:
    """Capture a screenshot from the current page."""
    try:
        data_url = await page_screenshot_base64(page_id, full_page=full_page)
        return {"page_id": page_id, "screenshot": data_url}
    except KeyError:
        return {"error": f"Unknown page_id '{page_id}'"}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Web Search – Tavily API
# ---------------------------------------------------------------------------

def get_tavily_api_key() -> str:
    """Return Tavily API key from env or raise ValueError."""
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        raise ValueError("TAVILY_API_KEY environment variable is required")
    return key


@mcp.tool()
def web_search(
    query: str,
    max_results: int = 10,
    include_domains: Optional[str] = None,
    exclude_domains: Optional[str] = None,
    search_depth: str = "advanced",
) -> dict[str, Any]:
    """Search the web using Tavily and return JSON results."""
    try:
        api_key = get_tavily_api_key()
        url = "https://api.tavily.com/search"
        payload: dict[str, Any] = {
            "api_key": api_key,
            "query": query,
            "max_results": max(1, min(max_results, 20)),
            "search_depth": search_depth,
        }

        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains

        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code != 200:
            return {"error": f"Tavily API error {resp.status_code}: {resp.text}"}

        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# MCP Prompts
# ---------------------------------------------------------------------------

@mcp.prompt()
def analyze_repository(owner: str, repo: str) -> list[base.Message]:
    """Return a reusable prompt for analyzing a GitHub repository."""
    repository = f"{owner}/{repo}"
    prompt_text = (
        "You are an expert software engineer and technical analyst. "
        f"Analyze the GitHub repository {repository} comprehensively.\n\n"
        "Cover these areas:\n"
        "1. Technical overview: languages, frameworks, and architecture patterns\n"
        "2. Code quality: structure, documentation, and testing practices\n"
        "3. Community health: issue management, contribution patterns, and maintenance status\n"
        "4. Development activity: recent commits, release patterns, and contributor activity\n"
        "5. Dependencies: key libraries and potential security concerns\n"
        "6. Recommendations: suggestions for improvement or adoption considerations\n\n"
        "Use the available MCP tools to gather current information before writing the analysis."
    )
    return [base.UserMessage(prompt_text)]


@mcp.prompt()
def debug_issue(owner: str, repo: str, issue_number: int) -> list[base.Message]:
    """Help debug and analyze a specific GitHub issue with context and suggestions."""
    return [
        base.UserMessage(
            "You are a skilled software engineer and debugging specialist. "
            "Analyze the issue by understanding the problem description, gathering repository context, "
            "investigating likely root causes, proposing debugging strategies, and recommending concrete next steps."
        ),
        base.UserMessage(
            f"I need help debugging issue #{issue_number} in {owner}/{repo}. "
            "Please analyze the issue thoroughly, gather relevant context from the repository, "
            "and provide debugging guidance and potential solutions."
        ),
    ]


@mcp.prompt()
def code_review_checklist(language: str = "general") -> list[base.Message]:
    """Return a reusable prompt for requesting a code review checklist."""
    target_language = language.strip() or "general"
    prompt_text = (
        "You are an expert code reviewer and software engineering mentor. "
        f"Create a practical code review checklist for {target_language} development.\n\n"
        "Cover these areas:\n"
        "1. Code quality and style\n"
        "2. Functionality and logic\n"
        "3. Performance and efficiency\n"
        "4. Security\n"
        "5. Maintainability\n"
        f"6. Language-specific best practices for {target_language}\n\n"
        "Make the checklist detailed enough for real reviews, but practical for daily team use."
    )
    return [base.UserMessage(prompt_text)]


@mcp.prompt()
def research_topic(topic: str, focus_area: str = "general") -> list[base.Message]:
    """Research a technical topic using web search and provide comprehensive analysis."""
    return [
        base.UserMessage(
            "You are a technical researcher and analyst. Research the requested topic thoroughly using web search. "
            "Cover the current state, technical details, ecosystem, use cases, advantages, challenges, future outlook, "
            "and practical getting-started guidance."
        ),
        base.UserMessage(
            f"Research the topic '{topic}' with focus on '{focus_area}'. "
            "Provide a comprehensive technical analysis using current web sources. "
            "Include practical insights, current trends, and actionable recommendations."
        ),
    ]


@mcp.prompt()
def file_analysis(file_path: str) -> list[base.Message]:
    """Analyze a source code file for quality, patterns, and improvement suggestions."""
    return [
        base.UserMessage(
            "You are an expert code analyst and software architect. Analyze the target source file for structure, "
            "organization, code quality, potential issues, dependencies, coupling, and practical improvement opportunities."
        ),
        base.UserMessage(
            f"Please analyze the source code file at '{file_path}'. "
            "Provide a comprehensive code quality assessment with specific improvement recommendations."
        ),
    ]


@mcp.prompt()
def web_automation_plan(task_description: str, target_url: str = "") -> list[base.Message]:
    """Create a step-by-step plan for web automation tasks using browser tools."""
    task = (
        f"Create a detailed web automation plan for: '{task_description}'"
        + (f" on the website: {target_url}" if target_url else "")
        + ". Provide step-by-step instructions using the available browser automation tools."
    )
    return [
        base.UserMessage(
            "You are a web automation specialist and QA engineer. Create a robust automation plan that covers task "
            "breakdown, selector strategy, wait conditions, verification steps, error handling, and maintainability."
        ),
        base.UserMessage(task),
    ]


def main() -> None:
    """Main entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
