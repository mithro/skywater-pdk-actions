#!/usr/bin/env python3
# Copyright 2020 SkyWater PDK Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0


import dataclasses
import json
import os
import pprint
import requests

from typing import Optional

import checks

from backport_common import *


def github_headers(_headers={}):
    if not _headers:
        # Figure out the GitHub access token.
        access_token = os.environ.get('GH_APP_TOKEN', None)
        if not access_token:
            raise SystemError('Did not find an access token of `GH_APP_TOKEN`')

        _headers['Authorization'] = 'token ' + access_token
        _headers['Accept'] = 'application/vnd.github.v3+json'
    return _headers


def get_github_json(url, *args, **kw):
    full_url = url.format(*args, **kw)
    return send_github_json(full_url, 'GET')


def send_github_json(url, mode, json_data=None):
    assert mode in ('GET', 'POST', 'PATCH'), f"Unknown mode {mode}"

    if dataclasses.is_dataclass(json_data):
        json_data = json.loads(json_data.to_json())

    kw = {
        'url': url,
        'headers': github_headers(),
    }
    if mode == 'POST':
        f = requests.post
        assert json_data is not None, json_data
        kw['json'] = json_data
    elif mode == 'PATCH':
        f = requests.patch
        assert json_data is not None, json_data
        kw['json'] = json_data
    elif mode == 'GET':
        assert json_data is None, json_data
        f = requests.get

    if json_data:
        debug_json(f'{mode} to {url}', json_data)
    json_data = f(**kw).json()
    debug_json(f'Got from {url}', json_data)
    return json_data


BACKPORT_MARKER = 'BACKPORT'


def get_pullrequest_info(url):
    """Get info on the associated pull request"""

    # Get the pull request's 'checks' json
    pr_check_runs_json = get_github_json(url)
    assert 'check_runs' in pr_check_runs_json, pr_check_runs_json
    pr_check_runs = pr_check_runs_json['check_runs']

    # Workout the PR's full hash
    head_sha = set()
    for check in pr_check_runs:
        head_sha.add(check['head_sha'])

    debug()
    debug('Found head_sha values of:', head_sha)
    debug()
    assert len(head_sha) == 1, head_sha
    head_sha = head_sha.pop()

    # Find any existing backport check runs
    extid2run = {}
    for check in pr_check_runs:
        check.pop('app')
        check = checks.CheckRun.from_json(json.dumps(check))

        if not check.external_id.startswith(BACKPORT_MARKER):
            continue

        extid2run[check.external_id] = check

    group_start('Existing backported check_runs', debug)
    pprint.pprint(extid2run)
    group_end()

    return head_sha, extid2run


def get_workflow_checks(workflow_run):

    workflow_check_runs = get_github_json(workflow_run['check_suite_url']+'/check-runs')
    assert 'check_runs' in workflow_check_runs, workflow_check_runs

    workflow_checks = []
    for check in workflow_check_runs['check_runs']:
        check.pop('app')
        out_check = checks.CheckRun.from_json(json.dumps(check))
        if out_check.output.annotations_count > 0:
            # FIXME: Also get the annotations if there are any.
            pass

        workflow_checks.append(out_check)

    return workflow_checks


def convert_check_run(prr, workflow_branch, workflow_name, workflow_check):
    assert isinstance(workflow_check, checks.CheckRun), workflow_check

    new_check = checks.CheckRunCreate.from_output(workflow_check)

    extid = (workflow_branch, workflow_name, workflow_check.name)

    new_check.external_id = '$'.join([BACKPORT_MARKER]+list(extid))
    assert prr.sha_full is not None, prr
    new_check.head_sha = prr.sha_full

    new_check.name = f"{workflow_branch}: {workflow_name} / {workflow_check.name}"
    # Invalid request. For 'properties/title', nil is not a string.
    if not new_check.output.title:
        new_check.output.title = new_check.name

    new_check.output.summary = f"""\
Run of {workflow_name} - {workflow_check.name} on Pull Request #{prr.id} (run #{prr.run} with git hash {prr.sha_short}) backported to {workflow_branch}.
"""
    # Invalid request. For 'properties/text', nil is not a string.
    if not new_check.output.text:
        new_check.output.text = new_check.output.summary

    return new_check


@dataclasses.dataclass
class PullRequestRun:
    """

    >>> PullRequestRun(100, 1, 'c618aa17146d00598f4617ca05c8a29917c84551')
    PullRequestRun(id=100, run=1, sha_short='c618a', sha_full='c618aa17146d00598f4617ca05c8a29917c84551')
    >>> prr = PullRequestRun(100, 1, 'c618a')
    >>> prr
    PullRequestRun(id=100, run=1, sha_short='c618a', sha_full=None)
    >>> prr.set_sha('c618aa17146d00598f4617ca05c8a29917c84551')
    >>> prr
    PullRequestRun(id=100, run=1, sha_short='c618a', sha_full='c618aa17146d00598f4617ca05c8a29917c84551')

    >>> PullRequestRun.from_backport_branch('backport/pr1/v12-54b92/branch-0.0.1')
    (PullRequestRun(id=1, run=12, sha_short='54b92', sha_full=None), 'branch-0.0.1')

    """

    id: int

    run: int

    sha: dataclasses.InitVar[str]
    sha_short: Optional[str] = dataclasses.field(init=False, default=None)
    sha_full: Optional[str] = dataclasses.field(init=False, default=None)

    def __post_init__(self, sha):
        self.set_sha(sha)

    @classmethod
    def from_backport_branch(cls, branch_ref):
        if not branch_ref.startswith('backport/'):
            raise SystemError('Invalid workflow_run event!')
        pr_id, (run, sha_short), branch_name = backport_branch_info(branch_ref)

        return PullRequestRun(id=pr_id, run=run, sha=sha_short), branch_name

    def set_sha(self, value):
        if len(value) == 40:
            if self.sha_short is None:
                self.sha_short = value[:5]
            else:
                assert value.startswith(self.sha_short), (self.sha_short, value)
            self.sha_full = value
        elif len(value) == 5:
            assert self.sha_short is None
            if self.sha_full is not None:
                assert self.sha_full.startswith(value), (value, self.sha_full)
            self.sha_short = value



def handle_workflow_run(http, event_json):
    workflow = event_json['workflow']
    workflow_run = event_json['workflow_run']
    head_repo = workflow_run.pop('head_repository')
    repo = workflow_run.pop('repository')

    repo_owner = head_repo['owner']['login']
    repo_name = head_repo['name']
    repo_slug = f"{repo_owner}/{repo_name}"

    debug_json('workflow json', workflow)
    debug_json('workflow_run json', workflow_run)

    prr, branch_name = PullRequestRun.from_backport_branch(workflow_run['head_branch'])

    print(
        f'Workflow run comes from backport of',
        f'Pull request #{prr.id}',
        f'run #{prr.run} (with git hash {prr.sha_short})',
        f'to {branch_name}',
    )

    commits_url = head_repo['commits_url']
    SHA_MARKER = '{/sha}'
    assert commits_url.endswith(SHA_MARKER), commits_url

    assert prr.sha_short is not None, prr
    sha_full, extid2run = get_pullrequest_info(
        commits_url.replace(SHA_MARKER, f'/{prr.sha_short}/check-runs'))
    prr.set_sha(sha_full)

    # Create a check on the pull request based on the check-run on the branch.
    # ------------------------------------------------------------------------------
    for check in get_workflow_checks(workflow_run):
        new_check = convert_check_run(prr, branch_name, workflow_run['name'], check)

        print()
        print("New check")
        print('-'*75)
        pprint.pprint(new_check)
        print('-'*75)

        if new_check.external_id not in extid2run:
            print()
            print('Need to *create* this check.')
            pr_check_api_url = commits_url.replace('/commits'+SHA_MARKER, f'/check-runs')
            r = send_github_json(pr_check_api_url, 'POST', new_check)
        else:
            print('Need to *update* this check.')
            existing_id = extid2run[new_check.external_id].id
            pr_check_api_url = commits_url.replace('/commits'+SHA_MARKER, f"/check-runs/{existing_id}")
            r = send_github_json(pr_check_api_url, 'PATCH', new_check)

        print()
        print('Result')
        print('-'*50)
        pprint.pprint(r)
        print('-'*50)


if __name__ == "__main__":
    import doctest
    doctest.testmod()
