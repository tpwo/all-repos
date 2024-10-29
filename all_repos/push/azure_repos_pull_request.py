from __future__ import annotations

import base64
import json
import subprocess
import urllib.request
from typing import Any
from typing import NamedTuple

from all_repos import autofix_lib
from all_repos import git
from all_repos.util import hide_api_key_repr
from all_repos.util import load_api_key


class Settings(NamedTuple):
    organization: str
    project: str
    base_url: str = 'https://dev.azure.com'
    api_key: str | None = None
    api_key_env: str | None = None
    draft: bool = False
    fork_suffix: str = ''

    def __repr__(self) -> str:
        return hide_api_key_repr(self)

    @property
    def auth(self) -> str:
        value = f':{load_api_key(self)}'
        return base64.b64encode(value.encode()).decode()


def make_pull_request(
        settings: Settings,
        branch_name: str,
) -> Any:
    headers = {
        'Authorization': f'Basic {settings.auth}',
        'Content-Type': 'application/json',
    }

    remote_url = git.remote('.')
    *_, repo_slug = remote_url.split('/')
    remote = 'origin'
    head = branch_name

    title = subprocess.check_output(('git', 'log', '-1', '--format=%s'))
    body = subprocess.check_output(('git', 'log', '-1', '--format=%b'))

    pr_data = {
        'title': title.decode().strip(),
        'description': body.decode().strip(),
        'sourceRefName': f'refs/heads/{head}',
        'targetRefName': f'refs/heads/{autofix_lib.target_branch()}',
        'isDraft': settings.draft,
    }

    if settings.fork_suffix:
        try:
            fork_id, fork_url = _get_fork_details(settings, headers, repo_slug)
        except ValueError:
            autofix_lib.run(
                'git', 'push', remote, f'HEAD:{branch_name}', '--quiet',
            )
        else:
            autofix_lib.run('git', 'remote', 'add', 'fork', fork_url)
            autofix_lib.run(
                'git', 'push', 'fork', f'HEAD:{branch_name}', '--quiet',
            )
            pr_data['forkSource'] = {'repository': {'id': fork_id}}
    else:
        autofix_lib.run(
            'git', 'push', remote, f'HEAD:{branch_name}', '--quiet',
        )

    data = json.dumps(pr_data).encode()

    pull_request_url = (
        f'{settings.base_url}/{settings.organization}/{settings.project}/'
        f'_apis/git/repositories/{repo_slug}/pullrequests?api-version=6.0'
    )

    resp = urllib.request.urlopen(
        urllib.request.Request(
            pull_request_url, data=data, headers=headers, method='POST',
        ),
    )
    return json.load(resp)


def _get_fork_details(
        settings: Settings,
        headers: dict[str, str],
        repo_slug: str,
) -> tuple[str, str]:
    collection_url = (
        f'{settings.base_url}/{settings.organization}/'
        f'_apis/projects/{settings.project}?api-version=6.0'
    )
    collection_resp = urllib.request.urlopen(
        urllib.request.Request(
            collection_url, headers=headers, method='GET',
        ),
    )
    collection_data = json.load(collection_resp)
    collection_href = collection_data['_links']['collection']['href']
    collection_id = collection_href.rpartition('/')[-1]

    fork_list_url = (
        f'{settings.base_url}/{settings.organization}/{settings.project}/'
        f'_apis/git/repositories/{repo_slug}/forks/'
        f'{collection_id}?api-version=6.0'
    )
    fork_list_resp = urllib.request.urlopen(
        urllib.request.Request(
            fork_list_url, headers=headers, method='GET',
        ),
    )
    fork_data = json.load(fork_list_resp)

    for fork in fork_data['value']:
        if fork['name'].endswith(settings.fork_suffix):
            fork_id = fork['id']
            fork_url = fork['sshUrl']
            break

    if not fork_id or not fork_url:
        raise ValueError(f'Fork with suffix {settings.fork_suffix} not found')

    return fork_id, fork_url


def push(settings: Settings, branch_name: str) -> None:
    obj = make_pull_request(settings, branch_name)
    web_url = obj['repository']['webUrl']
    pr_id = obj['pullRequestId']
    url = f'{web_url}/pullrequest/{pr_id}'
    print(f'Pull request created at {url}')
