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


import json
import logging
import os
import pathlib
import pprint
import requests
import subprocess
import sys
import textwrap
import urllib3

from library_submodules import reset_branches
from library_submodules import label_exists
from library_submodules import get_git_root
from library_submodules import git_fetch
from library_submodules import git
from library_patch_submodules import backport_hashes
from library_patch_submodules import backport_branch_info
from library_patch_submodules import library_patch_submodules
from library_patch_submodules import library_merge_submodules
from library_patch_submodules import library_clean_submodules


# Figure out the GitHub access token.
ACCESS_TOKEN = os.environ.get('GH_TOKEN', None)
if not ACCESS_TOKEN:
    ACCESS_TOKEN = os.environ.get('GITHUB_TOKEN', None)

if ACCESS_TOKEN is None:
    raise SystemError('Did not find an access token of `GH_TOKEN` or `GITHUB_TOKEN`')


DEBUG = True # os.environ.get('ACTIONS_STEP_DEBUG', 'false').lower() in ('true', '1')

def flush():
    sys.stderr.flush()
    sys.stdout.flush()


def debug(*args, **kw):
    if DEBUG:
        print(*args, **kw)

def debug_json(name, json):
    if DEBUG:
        group_start(name)
        pprint.pprint(json)
        group_end()


GROUP_OPEN = []

def group_end():
    flush()
    assert GROUP_OPEN
    f, title = GROUP_OPEN.pop()
    f()
    f('-'*50)
    f("::endgroup::")
    flush()


def group_start(title, f=print):
    flush()
    if GROUP_OPEN:
        group_end()
    f("::group::"+str(title))
    f('-'*50)
    flush()
    GROUP_OPEN.append((f, title))


HEADERS = {
    'Authorization': 'token ' + ACCESS_TOKEN,
    'Accept': 'application/vnd.github.v3+json',
}

def get_github_json(url, *args, **kw):
    full_url = url.format(*args, **kw)
    return send_github_json(full_url, 'GET')


def send_github_json(url, mode, json_data=None):
    assert mode in ('GET', 'POST', 'PATCH'), f"Unknown mode {mode}"

    kw = {
        'url': url,
        'headers': HEADERS,
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


def handle_pull_request(http, event_json):

    pull_request_id = event_json['number']
    repo_name = event_json['repository']['full_name']

    # Get the state for the current pull request
    pr_seq_dat = backport_hashes(repo_name, pull_request_id)
    group_start("Current backport data")
    pprint.pprint(pr_seq_dat)
    group_end()

    # Download the patch metadata
    print('Status URL:', event_json['pull_request']['statuses_url'])

    # Check if the pull request needs to be backported.
    pr_hash = event_json['pull_request']['head']['sha'][:5]
    print('Source branch hash:', pr_hash)
    if pr_seq_dat and pr_seq_dat[-1][1] == pr_hash:
        print('Existing backport branches up to date')
        print()
        for seq_id, seq_hash, branches in pr_seq_dat:
            print(' - Sequence:', 'v{}-{}'.format(seq_id, seq_hash))
            bwidth = max(len(n) for n in branches)
            for name, git_hash in branches.items():
                print('   * {} @ {}'.format(name.ljust(bwidth), git_hash[:5]))
            print()
        return 0

    # Backporting needs to run
    label = event_json['pull_request']['head']['label']
    commitmsg_filename = os.path.abspath(
        'commit-{0}.msg'.format(pull_request_id))
    with open(commitmsg_filename, 'w') as f:
        f.write("Merge pull request #{pr_id} from {label}\n".format(
            pr_id=pull_request_id,
            label=label,
        ))
        f.write("\n")
        f.write(event_json['pull_request']['title'])
        f.write("\n")
        f.write("\n")
        if event_json['pull_request']['body'].strip():
            f.write(event_json['pull_request']['body'])

    debug('Pull request commit message', '-'*50)
    debug(open(commitmsg_filename).read())
    debug('-'*50)

    # Download the patch
    print("Getting Patch")
    patch_request = http.request(
        'GET',
        'https://github.com/{0}/pull/{1}.patch' .format(
            repo_name, pull_request_id))

    patch_data = patch_request.data.decode('utf-8')
    debug('Pull request patch data', '-'*50)
    debug(patch_data)
    debug('-'*50)

    if patch_request.status != 200:
        print('Unable to get patch. Skipping...')
        return -1

    patch_filename = os.path.abspath('pr-{0}.patch'.format(pull_request_id))
    with open(patch_filename, 'w') as f:
        f.write(patch_request.data.decode('utf-8'))

    # Backport the patch
    print("Will try to apply: ", patch_filename)
    library_patch_submodules(
        ACCESS_TOKEN,
        repo_name,
        pull_request_id, pr_hash, patch_filename, commitmsg_filename)


BACKPORT_MARKER = 'BACKPORT'

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

    head_branch = workflow_run['head_branch']
    if not head_branch.startswith('backport/'):
        raise SystemError('Invalid workflow_run event!')
    pr_id, seq_dat, workflow_branch = backport_branch_info(head_branch)

    print(
        f'Workflow run comes from backport of',
        f'Pull request #{pr_id}',
        f'run #{seq_dat[0]} (with git hash {seq_dat[1]})',
        f'to {workflow_branch}',
    )

    # Check the this workflow's 'checks' json
    workflow_check_runs = get_github_json(workflow_run['check_suite_url']+'/check-runs')
    assert 'check_runs' in workflow_check_runs, workflow_check_runs
    workflow_check_runs = workflow_check_runs['check_runs']

    # Get the pull request's 'checks' json.
    commits_url = head_repo['commits_url']
    SHA_MARKER = '{/sha}'
    assert commits_url.endswith(SHA_MARKER), commits_url
    pr_check_runs = get_github_json(commits_url.replace(SHA_MARKER, f'/{seq_dat[1]}/check-runs'))
    assert 'check_runs' in pr_check_runs, pr_check_runs
    pr_check_runs = pr_check_runs['check_runs']

    head_sha = set()

    backport_check_runs = []
    for check in pr_check_runs:
        check.pop('app')
        head_sha.add(check['head_sha'])

        if check['external_id'].startswith(BACKPORT_MARKER):
            backport_check_runs.append(check)

    assert len(head_sha) == 1, head_sha
    head_sha = head_sha.pop()
    assert head_sha.startswith(seq_dat[1]), (head_sha, seq_dat[1])
    debug()
    debug('Found head_sha values of:', head_sha)
    debug()


    extid2run = {}
    for check in backport_check_runs:
        pr_check_runs.remove(check)

        eid = check['external_id']
        marker, pr_check_branch, workflow_name, check_name = eid.split('$', 4)
        assert marker == BACKPORT_MARKER, eid
        extid2run[(pr_check_branch, workflow_name, check_name)] = check['id']

    group_start('Existing backported check_runs', debug)
    pprint.pprint(extid2run)
    group_end()

    print('='*75)
    for check in workflow_check_runs:
        check.pop('app')
        pprint.pprint(check)
        assert 'name' in check
        extid = (workflow_branch, workflow_run['name'], check['name'])

        key_action = {
            'owner':            'add',
            'repo':             'add',
            'name':             'replace',
            'head_sha' :        'replace',
            'details_url':      'keep',
            'external_id' :     'replace',
            'status':           'keep',
            'started_at':       'keep',
            'conclusion':       'keep',
            'completed_at':     'keep',
            'output':           'keep',

            'check_suite':      'remove',
            'html_url' :        'remove',
            'id':               'remove',
            'node_id':          'remove',
            'pull_requests':    'remove',
            'url':              'remove',
            #'url':              'keep',
        }

        new_check = {}
        for k, v in sorted(check.items()):
            if k not in key_action:
                raise ValueError(f"{k} not found.")

            action = key_action.pop(k)
            if action == 'remove':
                continue

            elif action == 'keep':
                new_check[k] = check[k]

            elif action == 'replace':
                if k == 'external_id':
                    new_check[k] = '$'.join([BACKPORT_MARKER]+list(extid))
                elif k == 'head_sha':
                    new_check[k] = head_sha
                elif k == 'name':
                    new_check[k] = f"{workflow_branch}: {workflow_run['name']} - {check['name']}"
            else:
                raise ValueError(f"Unknown action {action}")

        for k, action in sorted(key_action.items()):
            if action == "add":
                key_action.pop(k)
                assert k not in new_check, f"{k} is already exists in {new_check}"
                if k == 'owner':
                    new_check['owner'] = repo_owner
                elif k == 'repo':
                    new_check['repo'] = repo_name

        assert not key_action, key_action

        # Invalid request. For 'properties/summary', nil is not a string.
        if not new_check['output']['summary']:
            new_check['output']['summary'] = f"""\
Run of {workflow_run['name']} - {check['name']} on Pull Request #{pr_id} (run #{seq_dat[0]} with git hash {seq_dat[1]}) backported to {workflow_branch}.
"""
        # Invalid request. For 'properties/title', nil is not a string.
        if not new_check['output']['title']:
            new_check['output']['title'] = new_check['name']

        # Invalid request. For 'properties/text', nil is not a string.
        if not new_check['output']['text']:
            new_check['output']['text'] = new_check['output']['summary']

        print()
        print("New check")
        print('-'*75)
        pprint.pprint(new_check)
        print('-'*75)

        if extid not in extid2run:
            print()
            print('Need to *create* this check.')
            pr_check_api_url = commits_url.replace('/commits'+SHA_MARKER, f'/check-runs')
            r = send_github_json(pr_check_api_url, 'POST', new_check)
        else:
            print('Need to *update* this check.')
            pr_check_api_url = commits_url.replace('/commits'+SHA_MARKER, f"/check-runs/{extid2run[extid]}")
            r = send_github_json(pr_check_api_url, 'PATCH', new_check)

        print()
        print('Result')
        print('-'*50)
        pprint.pprint(r)
        print('-'*50)




def handle_event(args):
    logging.basicConfig(level=logging.DEBUG)
    http = urllib3.PoolManager()

    event_json_path = os.environ.get('GITHUB_EVENT_PATH', None)
    if not event_json_path:
        print("Did not find GITHUB_EVENT_NAME environment value.")
        return -1
    event_json_path = pathlib.Path(event_json_path)
    if not event_json_path.exists():
        print(f"Path {event_json_path} was not found.")
        return -2

    group_start('git config', debug)
    git_config_out = subprocess.check_output(['git', 'config', '--show-origin', '--list'])
    debug(git_config_out.decode('utf-8'))
    group_end()

    event_json_data = open(event_json_path).read()
    group_start('Raw event_json_data', debug)
    debug(event_json_data)
    group_end()

    event_json = json.load(open(event_json_path))
    group_start("Event data")
    pprint.pprint(event_json)
    group_end()

    if 'pull_request' in event_json:
        return handle_pull_request(http, event_json)

    elif 'workflow_run' in event_json:
        return handle_workflow_run(http, event_json)


if __name__ == "__main__":
    sys.exit(handle_event(sys.argv[1:]))
