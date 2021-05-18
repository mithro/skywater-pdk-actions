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

import deployment

from backport_common import *


# 'deployment_id': 0,
# 'state': 


def create_master_check(head_sha):
    repo = slug=os.environ.get('GITHUB_REPOSITORY', None)
    assert slug is not None

    deployments_url = f'https://api.github.com/repos/{slug}/deployments'
    deployments_json = get_github_json(deployments_url, preview='ant-man-preview')

    enviro = {}
    for j in deployments_json:
        d = deployment.Deployment.from_dict(j)
        if d.environment in enviro:
            if d.updated_at < enviro[d.environment].updated_at:
                print('Skipping')
                pprint.pprint(d)
                continue
        enviro[d.environment] = d

    print()
    print('-'*75)
    pprint.pprint(enviro)
    print('-'*75)
    print()

    statuses = {}
    for k, d in enviro.items():
        if d.environment == 'production':
            delete_url = f'https://api.github.com/repos/{slug}/deployments/{d.id}'
            r = send_github_json(delete_url, 'DELETE')
            pprint.pprint(r)
        else:
            status_url = f'https://api.github.com/repos/{slug}/deployments/{d.id}/statuses'
            statuses[(d.id, k)] = get_github_json(status_url, preview='ant-man-preview')

    pprint.pprint(statuses)

    for (did, k), statuses in statuses.items():
        if not statuses:
            status = deployment.DeploymentStatusCreate(
                state = deployment.DeploymentState.success,
                description = f"Backport of {k}",
                environment = k,
                auto_inactive = False,
            )

            status_url = f'https://api.github.com/repos/{slug}/deployments/{d.id}/statuses'
            r = send_github_json(status_url, 'POST', status, preview='ant-man-preview')
            pprint.pprint(r)
        else:
            status = deployment.DeploymentStatusCreate(
                state = deployment.DeploymentState.success,
                description = f"Backport of {k}",
                log_url = 'https://www.google.com/',
                environment = k,
                environment_url = 'https://www.google.com/',
                auto_inactive = False,
            )

            status_url = f'https://api.github.com/repos/{slug}/deployments/{d.id}/statuses'
            r = send_github_json(status_url, 'POST', status, preview='ant-man-preview')
            pprint.pprint(r)

    return




    new_deployment = {
        'ref': head_sha,
        'auto_merge': False,
        'required_contexts': [],
        'payload': {},
        'description': "Hello",
        'environment': 'branch-0.0.1',
        'transient_environment': True,
        'production_environment': False,
    }

    if True or existing_check is None:
        print()
        print('Need to *create* this check.')
        api_url = f"https://api.github.com/repos/{slug}/deployments"
        r = send_github_json(api_url, 'POST', new_deployment, preview='ant-man-preview')
    else:
        print('Need to *update* this check.', existing_check.id)
        api_url = f"https://api.github.com/repos/{slug}/check-runs/{existing_check.id}"
        r = send_github_json(api_url, 'PATCH', new_deployment)

    print()
    print('Result')
    print('-'*50)
    pprint.pprint(r)
    print('-'*50)


if __name__ == "__main__":
    sys.exit(create_master_check(sys.argv[1]))
