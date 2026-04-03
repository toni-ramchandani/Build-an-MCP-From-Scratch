"""GitHub API utilities.

This module provides helper functions for interacting with the GitHub API
using PyGithub.
"""

import os
from github import Github


def get_github_client() -> Github:
    """Return an authenticated GitHub client.
    
    Raises:
        ValueError: If GITHUB_TOKEN environment variable is not set.
    
    Returns:
        Github: An authenticated PyGithub client instance.
    """
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN environment variable is required")
    return Github(token)
