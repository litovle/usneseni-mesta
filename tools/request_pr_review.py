#!/usr/bin/env python3
"""Request a PR review after publication, retrying temporary GitHub API failures."""

import argparse
import os
import re
import time

import requests


def request_review(repo: str, number: int, reviewer: str, token: str) -> bool:
    url = f"https://api.github.com/repos/{repo}/pulls/{number}/requested_reviewers"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    for attempt in range(3):
        try:
            response = requests.post(url, headers=headers, json={"reviewers": [reviewer]}, timeout=20)
            if 200 <= response.status_code < 300:
                print(f"Review requested from {reviewer} for {repo}#{number}")
                return True
            reason = f"HTTP {response.status_code}"
            retry = response.status_code == 429 or response.status_code >= 500
        except requests.RequestException:
            reason, retry = "network error", True
        if not retry or attempt == 2:
            break
        time.sleep(2 ** attempt)
    print(f"::warning::Review request for {repo}#{number} failed ({reason}). The published PR remains available.")
    return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--number", default="")
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args(argv)
    if not args.number:
        return 0
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo) or not re.fullmatch(r"[1-9]\d*", args.number):
        parser.error("Expected --repo OWNER/REPO and a positive --number")
    token = os.environ.get("GH_TOKEN")
    if not token:
        print("::warning::Cannot request a review without GH_TOKEN. The published PR remains available.")
        return 1
    return 0 if request_review(args.repo, int(args.number), args.reviewer, token) else 1


if __name__ == "__main__":
    raise SystemExit(main())
