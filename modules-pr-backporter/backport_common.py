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
import pathlib
import pprint
import requests
import subprocess
import sys


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


GH_BACKPORT_NS_TOP = 'backport'
GH_BACKPORT_NS_PR = GH_BACKPORT_NS_TOP + '/pr{pr_id}'
GH_BACKPORT_NS_BRANCH = GH_BACKPORT_NS_PR + '/v{seq_id}-{seq_hash}/{branch}'


def get_sequence_number(pull_request_id):
    git_sequence = -1
    all_branches = subprocess.check_output(
        'git branch -r', shell=True).decode('utf-8').split()
    print("All branches:", all_branches)
    git_matching_branches = [
        br for br in all_branches
        if GH_BACKPORT_NS_PR.format(pr_id=pull_request_id) in br]

    for matching_branch in git_matching_branches:
        git_sequence = max(int(matching_branch.split("/")[4]), git_sequence)
    return git_sequence


def order_sequence_numbers(items):
    """
    >>> order_sequence_numbers([((1, '000'), {})])
    [(0, None, None), (1, '000', {})]

    >>> order_sequence_numbers([((0, '000'), {}), ((3, '001'), {})])
    [(0, '000', {}), (1, None, None), (2, None, None), (3, '001', {})]
    """

    out_pr = [(-1, None, None)]

    for seq_dat, data in sorted(items):
        while seq_dat[0] - out_pr[-1][0] > 1:
            out_pr.append((len(out_pr)-1, None, None))
        out_pr.append((seq_dat[0], seq_dat[1], data))
    out_pr.pop(0)
    return out_pr


def backport_branch_info(branch_name):
    """

    >>> backport_branch_info('backport/pr1/v12-54b92/branch-0.0.1')
    (1, (12, '54b92'), 'branch-0.0.1')
    >>> backport_branch_info('backport/pr4/v0-d8e61/main')
    (4, (0, 'd8e61'), 'main')

    """
    bits = branch_name.split('/')
    assert bits.pop(0) == GH_BACKPORT_NS_TOP, (bits, branch_name)

    pr_id = bits.pop(0)
    assert pr_id.startswith('pr'), (pr_id, branch_name)
    pr_id = int(pr_id[2:])

    seq_info = bits.pop(0)
    assert seq_info.startswith('v'), (seq_info, branch_name)
    seq_id, seq_hash = seq_info.split('-')
    seq_id = int(seq_id[1:])
    assert seq_id >= 0, seq_id
    assert seq_id < 100, seq_id

    seq_dat = (seq_id, seq_hash)

    branch = bits.pop(0)
    assert not bits, (bits, branch_name)
    return pr_id, seq_dat, branch


def backport_hashes(repo_name, pull_request_id, __cache={}):
    if not __cache:
        for l in subprocess.check_output(
                "git ls-remote https://github.com/{}.git '{}/*'".format(
                    repo_name, GH_BACKPORT_NS_PR.format(pr_id=pull_request_id)),
                shell=True).decode('utf-8').split('\n'):

            if not l.strip():
                continue

            githash, ref = l.split('\t')
            heads = 'refs/heads/'
            assert ref.startswith(heads), ref
            pr_id, seq_dat, branch = backport_branch_info(ref[len(heads):])

            if pull_request_id != '*':
                assert pr_id == pull_request_id, (pr_id, pull_request_id, ref)

            if pr_id not in __cache:
                __cache[pr_id] = {}

            if seq_dat not in __cache[pr_id]:
                __cache[pr_id][seq_dat] = {}
            __cache[pr_id][seq_dat][branch] = githash

    out = {}
    for pr_id in __cache:
        out[pr_id] = order_sequence_numbers(__cache[pr_id].items())

    if pull_request_id == '*':
        return out
    return out.get(pull_request_id, [])



def github_headers(_headers={}):
    if not _headers:
        # Figure out the GitHub access token.
        access_token = os.environ.get('GH_APP_TOKEN', None)
        if not access_token:
            import app_token
            access_token = app_token.get_token()
            if not access_token:
                raise SystemError('Did not find an access token of `GH_APP_TOKEN`')
        _headers['Authorization'] = 'token ' + access_token
        _headers['Accept'] = 'application/vnd.github.v3+json'
    return _headers


def get_github_json(url, *args, **kw):
    full_url = url.format(*args, **kw)
    return send_github_json(full_url, 'GET')

def remove_none(d):
    """
    >>> d = {'a': None, 'b': {'c': None, 'd': 1}}
    >>> remove_none(d)
    >>> d
    {'b': {'d': 1}}
    """

    for k, v in list(d.items()):
        if isinstance(v, dict):
            remove_none(v)
        elif v is None:
            del d[k]


def send_github_json(url, mode, json_data=None):
    assert mode in ('GET', 'POST', 'PATCH'), f"Unknown mode {mode}"

    if dataclasses.is_dataclass(json_data):
        json_data = json.loads(json_data.to_json())
        remove_none(json_data)

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


if __name__ == "__main__":
    import doctest
    doctest.testmod()
