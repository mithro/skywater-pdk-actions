#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
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


import datetime
import sys

import checks

from backport_common import *


def create_master_check(head_sha):
    repo = slug=os.environ.get('GITHUB_REPOSITORY', None)
    assert slug is not None

    url = f"https://api.github.com/repos/{slug}/commits/{head_sha}/check-runs"
    check_runs_json = get_github_json(url)
    assert 'check_runs' in check_runs_json, check_runs_json
    existing_checks = []
    for check in check_runs_json['check_runs']:
        check.pop('app')
        check = checks.CheckRun.from_json(json.dumps(check))
        if check.external_id == "backport":
            existing_checks.append(check)

    pprint.pprint(existing_checks)
    assert len(existing_checks) <= 1
    existing_check = existing_checks.pop(0)

    check = checks.CheckRunCreate(
        name="Backporter Status and Control",
        head_sha=head_sha,
        output=checks.CheckRunCreateOutput(
            title="Backport Status and Control",
            summary="""\

Pull Request Backport Status
============================



""",
            text="""\
""",
            annotations=[],
            images=[],
        ),
        actions=[
            checks.CheckRunCreateAction(
                label="Backport",
                description="Try to backport this PR to the branches.",
                identifier="do-pr-backport",
            ),
            checks.CheckRunCreateAction(
                label="Merge",
                description="Merge the backported branches.",
                identifier="do-pr-merge",
            ),
        ],
        #details_url="https://www.google.com/random",
        external_id="backport",
        started_at=datetime.datetime.utcnow(),
        status=checks.CheckStatus.in_progress,
        #conclusion=checks.CheckConclusion.neutral,
        #completed_at=datetime.datetime.utcnow(),
    )

    if existing_check is None or True:
        print()
        print('Need to *create* this check.')
        pr_check_api_url = f"https://api.github.com/repos/{slug}/check-runs"
        r = send_github_json(pr_check_api_url, 'POST', check)
    else:
        print('Need to *update* this check.', existing_check.id)
        pr_check_api_url = f"https://api.github.com/repos/{slug}/check-runs/{existing_check.id}"
        r = send_github_json(pr_check_api_url, 'PATCH', check)

    print()
    print('Result')
    print('-'*50)
    pprint.pprint(r)
    print('-'*50)

    check.status = checks.CheckStatus.completed
    check.conclusion = checks.CheckConclusion.action_required
    check.completed_at = datetime.datetime.now()


if __name__ == "__main__":
    sys.exit(create_master_check(sys.argv[1]))
