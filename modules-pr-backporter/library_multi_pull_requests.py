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


def debug(*args, **kw):
    if DEBUG:
        print(*args, **kw)


GROUP_OPEN = []

def group_end():
    assert GROUP_OPEN
    f, title = GROUP_OPEN.pop()
    f()
    f('-'*50)
    f("::endgroup::")
    f(flush=True)


def group_start(title, f=print):
    if GROUP_OPEN:
        group_end()
    f("::group::"+str(title))
    f('-'*50)
    f(flush=True)
    GROUP_OPEN.append((f, title))


def get_github_json(url, *args, **kw):
    headers = {'Authorization': 'token ' + ACCESS_TOKEN}
    full_url = url.format(*args, **kw)
    debug(full_url, '-'*50)
    json_data = requests.get(full_url, headers=headers).json()
    debug(pprint.pformat(json_data))
    debug('-'*50)
    return json_data


def handle_pull_requests(args):
    http = urllib3.PoolManager()

    event_json_path = os.environ.get('GITHUB_EVENT_PATH', None)
    if not event_json_path:
        print("Did not find GITHUB_EVENT_NAME environment value.")
        return -1
    event_json_path = pathlib.Path(event_json_path)
    if not event_json_path.exists():
        print(f"Path {event_json_path} was not found.")
        return -2

    event_json_data = open(event_json_path).read()
    group_start('Raw event_json_data', debug)
    debug(event_json_data)
    group_end()

    event_json = json.load(open(event_json_path))
    group_start("Event data")
    pprint.pprint(event_json)
    group_end()

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


if __name__ == "__main__":
    sys.exit(handle_pull_requests(sys.argv[1:]))
