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
import urllib3


from library_submodules import reset_branches
from library_submodules import label_exists
from library_submodules import get_git_root
from library_submodules import git_fetch
from library_submodules import git
from library_patch_submodules import library_patch_submodules
from library_patch_submodules import library_merge_submodules
from library_patch_submodules import library_clean_submodules


# Figure out the GitHub access token.
ACCESS_TOKEN = os.environ.get('GH_TOKEN', None)
if not ACCESS_TOKEN:
    ACCESS_TOKEN = os.environ.get('GITHUB_TOKEN', None)

if ACCESS_TOKEN is None:
    raise SystemError('Did not find an access token of `GH_TOKEN` or `GITHUB_TOKEN`')


def handle_pull_requests(args):
    print(args)
    repo_name = args.pop(0)
    assert not args, args
    print()
    print()
    http = urllib3.PoolManager()

    r = requests.get(
        'https://api.github.com/repos/{0}/pulls?state=open'.format(
            repo_name)).json()

    all_open_pull_requests = list(
        sorted(set(str(item['number']) for item in r)))

    print("All Open Pull Requests: ", all_open_pull_requests)
    library_clean_submodules(repo_name, all_open_pull_requests)
    for pull_request_id in all_open_pull_requests:
        print()
        print("Processing:", str(pull_request_id))
        print('-'*20, flush=True)
        # Download the patch metadata
        pr_md = requests.get(
            'https://api.github.com/repos/{0}/pulls/{1}' .format(
                repo_name, pull_request_id)).json()
        label = pr_md['head']['label']
        commit_msg_filename = os.path.abspath(
            'commit-{0}.msg'.format(pull_request_id))
        with open(commit_msg_filename, 'w') as f:
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

        # Download the patch
        print("Getting Patch")
        patch_request = http.request(
            'GET',
            'https://github.com/{0}/pull/{1}.patch' .format(
                repo_name, pull_request_id))
        if patch_request.status != 200:
            print('Unable to get patch. Skipping...')
            continue
        patchfile = os.path.abspath('pr-{0}.patch'.format(pull_request_id))
        with open(patchfile, 'w') as f:
            f.write(patch_request.data.decode('utf-8'))

        # Backport the patch
        print("Will try to apply: ", patchfile)
        if library_patch_submodules(
                patchfile, pull_request_id, repo_name, ACCESS_TOKEN, commit_msg_filename):
            print()
            print("Pull Request Handled: ", str(pull_request_id))
            print('-'*20, flush=True)

        continue
        if label_exists(repo_name, pull_request_id, 'ready-to-merge'):
            print("PR {0} is now ready to be merged..".format(pull_request_id))
            library_merge_submodules(
                pull_request_id, repo_name, ACCESS_TOKEN)

    print('-'*20, flush=True)
    print("Done Creating PR branches!")
    print('-'*20, flush=True)


if __name__ == "__main__":
    sys.exit(handle_pull_requests(sys.argv[1:]))
