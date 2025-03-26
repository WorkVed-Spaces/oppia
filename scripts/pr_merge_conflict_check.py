# coding: utf-8
#
# Copyright 2025 The Oppia Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Script to check open GitHub PRs for merge conflicts and notify authors.

This script checks open pull requests in the repository for merge conflicts.
If a PR is found to have merge conflicts (indicated by a mergeable_state of 'dirty'),
the script assigns the PR author to the PR and notifies them via a GitHub comment.
"""

from __future__ import annotations

import collections
import datetime
import logging
import os
from scripts import install_third_party_libs

import requests
from typing import Dict, List, Optional, Set, TypedDict, Any
import time

# Global configuration.
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
REPO = os.getenv('GITHUB_REPOSITORY')
RETRY_COUNT = 3
RETRY_DELAY = 5  # seconds between retries.
TIMEOUT = 10  # seconds for HTTP requests.

# Configure logging.
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')


class GitHubService:
    """Service class for GitHub API interactions related to pull requests.

    This class provides methods to list open PRs, fetch PR details with retry logic,
    assign PR authors, and post notification comments.
    """

    def __init__(self, token: str, repo: str) -> None:
        """Initialize GitHubService.

        Args:
            token: GitHub API token.
            repo: GitHub repository in the format 'owner/repo'.
        """
        self.token = token
        self.repo = repo
        self.base_url = f'https://api.github.com/repos/{repo}'
        self.rest_headers = {
            'Authorization': f'token {self.token}',
            'Accept': 'application/vnd.github.v3+json'
        }

    def list_open_prs(self) -> List[Dict[str, Any]]:
        """Fetches all open pull requests with pagination.

        Returns:
            List of dictionaries representing open pull requests.
        """
        prs: List[Dict[str, Any]] = []
        page = 1
        while True:
            url = (
                f'{self.base_url}/pulls?state=open&page={page}&per_page=100'
            )
            response = requests.get(url, headers=self.rest_headers, timeout=TIMEOUT)
            response.raise_for_status()
            current_prs = response.json()
            if not current_prs:
                break
            prs.extend(current_prs)
            page += 1
        return prs

    def fetch_pr_details(self, pr_number: int) -> Optional[Dict[str, Any]]:
        """Fetches pull request details with retries until a definitive mergeable state is found.

        Args:
            pr_number: The number of the pull request.

        Returns:
            A dictionary with PR details if the mergeable state is determined;
            otherwise, None.
        """
        pr_details_url = f'{self.base_url}/pulls/{pr_number}'
        for attempt in range(RETRY_COUNT):
            response = requests.get(pr_details_url, headers=self.rest_headers, timeout=TIMEOUT)
            response.raise_for_status()
            pr_details = response.json()
            mergeable_state = pr_details.get('mergeable_state')
            if mergeable_state and mergeable_state != 'unknown':
                return pr_details
            logging.info(
                'Retry %d/%d: Mergeable state is "unknown" for PR #%d. Retrying...',
                attempt + 1, RETRY_COUNT, pr_number
            )
            time.sleep(RETRY_DELAY)
        logging.warning(
            'Mergeable state could not be determined for PR #%d after %d retries.',
            pr_number, RETRY_COUNT
        )
        return None

    def assign_pr_author(self, pr_number: int, pr_author: str) -> bool:
        """Assigns the PR author as the sole assignee.

        Args:
            pr_number: The pull request number.
            pr_author: The GitHub username of the PR author.

        Returns:
            True if the assignment was successful; False otherwise.
        """
        assign_url = f'{self.base_url}/issues/{pr_number}'
        assign_payload = {'assignees': [pr_author]}
        response = requests.patch(assign_url, json=assign_payload, headers=self.rest_headers, timeout=TIMEOUT)
        if response.ok:
            return True
        logging.error(
            'Failed to assign %s to PR #%d. Response: %s',
            pr_author, pr_number, response.text
        )
        return False

    def notify_pr_author(self, pr_number: int, pr_author: str) -> bool:
        """Notifies the PR author about merge conflicts by posting a comment.

        Args:
            pr_number: The pull request number.
            pr_author: The GitHub username of the PR author.

        Returns:
            True if the notification was posted successfully; False otherwise.
        """
        comment_url = f'{self.base_url}/issues/{pr_number}/comments'
        message = (
            f'Hi @{pr_author}, due to recent changes in the develop branch, '
            'this PR now has a merge conflict. Please refer to '
            '[GitHub\'s guide on resolving merge conflicts]'
            '(https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/'
            'addressing-merge-conflicts/resolving-a-merge-conflict-using-the-command-line) '
            'if you need help resolving the conflict so that the PR can be merged. Thanks!'
        )
        comment_payload = {'body': message}
        response = requests.post(comment_url, json=comment_payload, headers=self.rest_headers, timeout=TIMEOUT)
        if response.ok:
            return True
        logging.error(
            'Failed to notify %s in PR #%d. Response: %s',
            pr_author, pr_number, response.text
        )
        return False


class PRManager:
    """Manager class for handling pull request merge conflict notifications.

    This class utilizes GitHubService to check the state of open PRs and take action
    when merge conflicts are detected.
    """

    def __init__(self, github_service: GitHubService) -> None:
        """Initialize PRManager.

        Args:
            github_service: Instance of GitHubService.
        """
        self.github_service = github_service

    def check_and_notify(self) -> None:
        """Checks each open pull request for merge conflicts and notifies authors.

        For each PR with a mergeable_state of 'dirty', the PR author is assigned
        to the PR and notified via a GitHub comment.
        """
        prs = self.github_service.list_open_prs()
        for pr in prs:
            pr_number = pr.get('number')
            pr_author = pr.get('user', {}).get('login')
            logging.info('Checking PR #%d by %s.', pr_number, pr_author)

            pr_details = self.github_service.fetch_pr_details(pr_number)
            if not pr_details:
                # Skip if mergeable state remains undetermined.
                continue

            mergeable_state = pr_details.get('mergeable_state')
            if mergeable_state == 'dirty':
                logging.info('PR #%d has merge conflicts.', pr_number)
                if self.github_service.assign_pr_author(pr_number, pr_author):
                    logging.info('Assigned %s to PR #%d.', pr_author, pr_number)
                else:
                    logging.error('Assignment failed for PR #%d.', pr_number)

                if self.github_service.notify_pr_author(pr_number, pr_author):
                    logging.info('Notified %s about conflicts in PR #%d.', pr_author, pr_number)
                else:
                    logging.error('Notification failed for PR #%d.', pr_number)
            else:
                logging.info('PR #%d state: %s. No action needed.', pr_number, mergeable_state)


def main() -> None:
    """Main function to check open pull requests for merge conflicts and notify authors."""
    try:
        github_service = GitHubService(GITHUB_TOKEN, REPO)
        pr_manager = PRManager(github_service)
        pr_manager.check_and_notify()
    except Exception as e:
        logging.error('Error encountered: %s', e)


if __name__ == '__main__': # pragma: no cover
    # This installs third party libraries (requests) before
    # importing other files or importing libraries that use
    # the builtins python module (e.g. build, utils).
    install_third_party_libs.main()
    main()
