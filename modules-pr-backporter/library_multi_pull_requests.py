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
    print()
    print('-'*50)
    print("::endgroup::")
    print(flush=True)
    GROUP_OPEN.pop()


def group_start(title):
    if GROUP_OPEN:
        group_end()
    print("::group::"+str(title))
    print('-'*50)
    print(flush=True)
    GROUP_OPEN.append(title)


def get_github_json(url, *args, **kw):
    headers = {'Authorization': 'token ' + ACCESS_TOKEN}
    full_url = url.format(*args, **kw)
    debug(full_url, '-'*50)
    json_data = requests.get(full_url, headers=headers).json()
    debug(pprint.pformat(json_data))
    debug('-'*50)
    return json_data


def handle_pull_requests(args):
    repo_name = args.pop(0)
    assert not args, args
    http = urllib3.PoolManager()

    # Get a list of all the open pull requests
    backport_dat = backport_hashes(repo_name, '*')
    group_start("Current backport data")
    pprint.pprint(backport_dat)
    group_end()

    # Get a list of all the open pull requests
    r = get_github_json(
        'https://api.github.com/repos/{0}/pulls?state=open',
        repo_name)
    all_open_pull_requests = list(
        sorted(set(item['number'] for item in r)))
    print()
    print("All Open Pull Requests: ", all_open_pull_requests)
    print(flush=True)

    # Cleaning up any left over merged branches.
    group_start("Cleaning up old branches.")
    #library_clean_submodules(repo_name, all_open_pull_requests)
    group_end()

    # See if any their are any new pull requests or old pull requests which
    # need updating.
    for pull_request_id in all_open_pull_requests:
        group_start("Processing pull request #"+str(pull_request_id))

        # Download the patch metadata
        pr_md = get_github_json(
            'https://api.github.com/repos/{0}/pulls/{1}',
            repo_name, pull_request_id)

        print('Status URL:', pr_md['statuses_url'])

        # Check if the pull request needs to be backported.
        pr_hash = pr_md['head']['sha'][:5]
        print('Source branch hash:', pr_hash)
        pr_seq_dat = backport_dat.get(pull_request_id, [])
        if pr_seq_dat and pr_seq_dat[-1][1] == pr_hash:
            print('Existing backport branches up to date')
            print()
            for seq_id, seq_hash, branches in pr_seq_dat:
                print(' - Sequence:', 'v{}-{}'.format(seq_id, seq_hash))
                bwidth = max(len(n) for n in branches)
                for name, git_hash in branches.items():
                    print('   * {} @ {}'.format(name.ljust(bwidth), git_hash[:5]))
                print()
            continue

        # Backporting needs to run
        label = pr_md['head']['label']
        commitmsg_filename = os.path.abspath(
            'commit-{0}.msg'.format(pull_request_id))
        with open(commitmsg_filename, 'w') as f:
            f.write("Merge pull request #{pr_id} from {label}\n".format(
                pr_id=pull_request_id,
                label=label,
            ))
            f.write("\n")
            f.write(pr_md['title'])
            f.write("\n")
            f.write("\n")
            if pr_md['body'].strip():
                f.write(pr_md['body'])

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
            continue

        patch_filename = os.path.abspath('pr-{0}.patch'.format(pull_request_id))
        with open(patch_filename, 'w') as f:
            f.write(patch_request.data.decode('utf-8'))

        # Backport the patch
        print("Will try to apply: ", patch_filename)
        library_patch_submodules(
            ACCESS_TOKEN,
            repo_name,
            pull_request_id, pr_hash, patch_filename, commitmsg_filename)

    if all_open_pull_requests:
        group_end()

#        continue
#        if label_exists(repo_name, pull_request_id, 'ready-to-merge'):
#            print("PR {0} is now ready to be merged..".format(pull_request_id))
#            library_merge_submodules(
#                pull_request_id, repo_name, ACCESS_TOKEN)


if __name__ == "__main__":
    sys.exit(handle_pull_requests(sys.argv[1:]))
