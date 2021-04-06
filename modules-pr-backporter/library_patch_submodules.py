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


import os
import pprint
import requests
import subprocess
import sys

from collections import defaultdict

import library_submodules
from library_submodules import get_lib_versions
from library_submodules import git
from library_submodules import git_clean
from library_submodules import git_fetch
from library_submodules import git_head
from library_submodules import git_issue_close
from library_submodules import git_issue_comment
from library_submodules import github_auth_set
from library_submodules import out_v
from library_submodules import previous_v


__dir__ = os.path.dirname(__file__)

GH_BACKPORT_NS_TOP = 'backport'
GH_BACKPORT_NS_PR = GH_BACKPORT_NS_TOP + '/pr{pr_id}'
GH_BACKPORT_NS_BRANCH = GH_BACKPORT_NS_PR + '/v{seq_id}/{branch}'


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


def backport_hashes(repo_name, pull_request_id):
    current_hashes = {}
    for l in subprocess.check_output(
            "git ls-remote https://github.com/{}.git '{}/*'".format(
                repo_name, GH_BACKPORT_NS_PR.format(pr_id=pull_request_id)),
            shell=True).decode('utf-8').split('\n'):

        if not l.strip():
            continue
        print(l)
        githash, ref = l.split('\t')
        bits = ref.split('/')
        assert bits.pop(0) == 'refs', bits
        assert bits.pop(0) == 'heads', bits
        assert bits.pop(0) == GH_BACKPORT_NS_TOP, bits
        assert bits.pop(0).endswith(str(pull_request_id)), bits
        seq_id = bits.pop(0)
        assert seq_id.startswith('v'), (seq_id, bits)
        seq_id = int(seq_id[1:])
        assert seq_id >= 0, seq_id
        assert seq_id < 100, seq_id
        branch = bits.pop(0)
        assert not bits, bits
        if seq_id not in current_hashes:
            current_hashes[seq_id] = {}
        current_hashes[seq_id][branch] = githash

    out = []
    while current_hashes:
        i = len(out)
        if i in current_hashes:
            out.append(current_hashes[i])
            del current_hashes[i]
        else:
            out.append({})

    return out


def library_patch_submodules(
        patchfile, pull_request_id, repo_name, access_token, commit_msg_filename):

    assert os.path.exists(patchfile), patchfile
    assert os.path.isfile(patchfile), patchfile

    hashes = backport_hashes(repo_name, pull_request_id)

    # Get the latest date in the patch file.
    date = None
    with open(patchfile) as f:
        for l in f:
            if l.startswith('Date: '):
                prefix, date = l.strip().split(': ', 1)
                assert prefix == 'Date', (prefix, l)
    assert date is not None, (data, open(patchfile).read())
    library_submodules.DATE = date
    print('Patch date is:', date)

    # Clone the repository in blobless mode.
    git_root = os.path.abspath(repo_name.replace('/', '--'))
    if not os.path.exists(git_root):
        git('clone --filter=blob:none https://github.com/{}.git {}'.format(
                repo_name, git_root),
            os.getcwd(),
        )
    else:
        print('Reusing existing clone at:', git_root)

    # Setup the github authentication token to allow pushing.
    github_auth_set(git_root, access_token)

    print()
    print()
    versions = get_lib_versions(git_root)
    backported_to_version = {}
    for i, v in enumerate(versions):
        pv = previous_v(v, versions)
        ov = out_v(v, versions)

        v_branch = "branch-{}.{}.{}".format(*ov)

        print()
        print("Was:", pv, "Now patching", v_branch, "with", patchfile)
        print('-'*20, flush=True)

        # Checkout the right branch
        git('checkout {0}'.format(v_branch), git_root)
        git('reset --hard origin/{0}'.format(v_branch), git_root)
        git_clean(git_root)

        diff_pos = 'branch-{}.{}.{}'.format(*pv)

        # Update the contents
        if not backported_to_version:
            if git('am {}'.format(patchfile), git_root, can_fail=True) is False:
                git('am --show-current-patch=diff', git_root)
                git('am --abort', git_root)
                continue

        # Create the merge commit
        if i > 0:
            git(
                'merge {} --no-ff --no-commit --strategy=recursive'.format(diff_pos),
                git_root)
        git('commit --allow-empty -F {}'.format(commit_msg_filename), git_root)
        backported_to_version[v_branch] = git_head(git_root)

        stat = [l.split() for l in subprocess.check_output(
            ['git', 'diff', '--numstat', 'origin/{0}'.format(v_branch)],
            cwd=git_root,
        ).decode('utf-8').splitlines()]
        changes = subprocess.check_output(
            ['git', 'diff', '--patch-with-stat', 'origin/{0}'.format(v_branch)],
            cwd=git_root,
        ).decode('utf=8')
        print(flush=True)
        print('Changes on {}'.format(v_branch))
        print('Changes in files:')
        pprint.pprint(stat)
        print('-'*20)
        print(changes)
        print('-'*20)

    if not backported_to_version:
        print('Patch was unable to be backported!')
        return False

    git('branch -D master', git_root, can_fail=True)
    git('branch master', git_root)
    backported_to_version['master'] = git_head(git_root)

    print()
    print()
    print('Previous backports:')
    pprint.pprint(hashes)
    print()
    print('Patch was backported to:')
    pprint.pprint(backported_to_version)

    if hashes and backported_to_version == hashes[-1]:
        print()
        print('Backported branches up to date!')
        return

    print()
    print('Backported branches need to be updated!')
    new_seq = len(hashes)

    comment_body = ["""\
The commits from this PR have been backported onto:
"""]

    for b in backported_to_version:
        base_hash = git_head(git_root, 'origin/'+b)

        target = GH_BACKPORT_NS_BRANCH.format(
            pr_id=pull_request_id, seq_id=new_seq, branch=b)
        git('push origin {}:{}'.format(b, target), git_root)

        if b != 'master':
            comment_body += ["""\
 - [{branch_name}](https://github.com/{repo_name}/compare/{base_hash}...{target})
""".format(branch_name=b, repo_name=repo_name, base_hash=base_hash, target=target)]

    comment_body = "".join(comment_body)
    git_issue_comment(
        repo_name,
        pull_request_id,
        comment_body,
        access_token,
    )
    return


def library_merge_submodules(pull_request_id, repo_name, access_token):
    print()
    print()
    #git_root = get_git_root() FIXME

    git_fetch(git_root)

    versions = get_lib_versions(git_root)
    for i, v in enumerate(versions):
        pv = previous_v(v, versions)
        ov = out_v(v, versions)

        v_branch = "branch-{}.{}.{}".format(*ov)
        v_tag = "v{}.{}.{}".format(*ov)
        git_sequence = int(get_sequence_number(pull_request_id))
        n_branch = GH_BACKPORT_NS_BRANCH.format(
            pr_id=pull_request_id, seq_id=git_sequence, branch=v_branch)
        print()
        print("Was:", pv, "Now updating", (v_branch, v_tag), "with", n_branch)
        print('-'*20, flush=True)

        # Get us back to a very clean tree.
        # git('reset --hard HEAD', git_root)
        git_clean(git_root)

        # Checkout the right branch
        git('checkout {0}'.format(v_branch), git_root)
        print("Now reseting ", v_branch, " to ", n_branch)
        git('reset --hard origin/{0}'.format(n_branch), git_root)
        print("Now Pushing", v_branch)
        git('push -f origin {0}:{0}'.format(v_branch), git_root)
        for i in range(git_sequence + 1):
            d_branch = GH_BACKPORT_NS_BRANCH.format(
                pr_id=pull_request_id, seq_id=i, branch=v_branch)
            git('push origin --delete {0}'.format(d_branch),
                git_root)

    git_clean(git_root)
    n_branch = GH_BACKPORT_NS_BRANCH.format(
        pr_id=pull_request_id, seq_id=git_sequence, branch='master')
    git('checkout master', git_root)
    print("Now reseting master to ", n_branch)
    git('reset --hard origin/{0}'.format(n_branch), git_root)
    print("Now Pushing", v_branch)
    git('push -f origin master:master', git_root)
    for i in range(git_sequence + 1):
        d_branch = GH_BACKPORT_NS_BRANCH.format(
            pr_id=pull_request_id, seq_id=i, branch='master')
        git('push origin --delete {0}'.format(d_branch),
            git_root)
    git_issue_close(repo_name, pull_request_id, access_token)
    comment_body = """\
Thank you for your pull request. This pull request will be closed, because \
the Pull-Request Merger has successfully applied it internally to all \
branches.
"""
    git_issue_comment(repo_name, pull_request_id, comment_body, access_token)


def library_rebase_submodules(pull_request_id):
    print()
    print()
    #git_root = get_git_root() FIXME

    git_fetch(git_root)

    versions = get_lib_versions(git_root)
    for i, v in enumerate(versions):
        pv = previous_v(v, versions)
        ov = out_v(v, versions)

        v_branch = "branch-{}.{}.{}".format(*ov)
        v_tag = "v{}.{}.{}".format(*ov)
        git_sequence = int(get_sequence_number(pull_request_id))
        n_branch = GH_BACKPORT_NS_BRANCH.format(
            pr_id=pull_request_id, seq_id=git_sequence, branch=v_branch)
        print()
        print("Was:", pv,
              "Now rebasing ", n_branch,
              " with ", (v_branch, v_tag))
        print('-'*20, flush=True)

        # Get us back to a very clean tree.
        # git('reset --hard HEAD', git_root)
        git_clean(git_root)

        # Checkout the right branch
        git('checkout {0}'.format(n_branch), git_root)
        git('rebase origin/{0}'.format(v_branch), git_root)
        print("Now Pushing", n_branch)
        git('push -f origin {0}:{0}'.format(n_branch), git_root)

    git_clean(git_root)
    n_branch = GH_BACKPORT_NS_BRANCH.format(
        pr_id=pull_request_id, seq_id=git_sequence, branch='master')
    git('checkout {0}'.format(n_branch), git_root)
    git('rebase origin/master', git_root)
    print("Now Pushing", n_branch)
    git('push -f origin {0}:{0}'.format(n_branch), git_root)


def library_clean_submodules(git_root, all_open_pull_requests):
    print()
    print()
    print("Cleaning up pull request branches for closed pull requests.")
    all_branches = subprocess.check_output(
        'git branch -r', shell=True).decode('utf-8').split()
    print("All branchs:", all_branches)
    for br in all_branches:
        if not br.startswith('origin'):
            continue

        _, branch_name = br.split('/', 1)
        assert _ == 'origin', (_, branch_name)
        if not branch_name.startswith(GH_BACKPORT_NS_TOP):
            print('Skipping:', branch_name)
            continue

        _, pr, extra = branch_name.split('/', 2)
        if pr not in all_open_pull_requests:
            print('Deleting ', br)
            git('push origin --delete {0}'.format(),
                git_root)


def main(args):
    assert len(args) == 5
    patchfile = os.path.abspath(args.pop(0))
    pull_request_id = args.pop(0)
    repo_name = args.pop(0)
    access_token = args.pop(0)
    commit_hash = args.pop(0)
    library_patch_submodules(
        patchfile, pull_request_id, repo_name, access_token, commit_hash)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
