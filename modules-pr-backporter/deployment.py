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


import enum
import json
import pprint
import dataclasses

from dataclasses import dataclass, field
from dataclasses_json import dataclass_json, config
from datetime import datetime, timezone
from typing import Optional


"""
Small library for working with GitHub Check Runs / Suites.
"""

def fromisoformat(s):
    """

    >>> fromisoformat('2021-05-03T01:48:37Z')
    datetime.datetime(2021, 5, 3, 1, 48, 37, tzinfo=datetime.timezone.utc)

    >>> repr(fromisoformat(None))
    'None'
    """
    if not s or s == 'null':
        return None
    if s.endswith('Z'):
        s = s[:-1]+'+00:00'
    return datetime.fromisoformat(s)


def toisoformat(s):
    """

    >>> toisoformat(datetime(2021, 5, 3, 1, 48, 37, tzinfo=timezone.utc))
    '2021-05-03T01:48:37Z'
    >>> toisoformat(datetime(2021, 5, 3, 1, 48, 37, tzinfo=None))
    '2021-05-03T01:48:37Z'
    """
    if s is None:
        return None
    else:
        assert s.tzinfo in (timezone.utc, None), (s.tzinfo, repr(s), str(s))
        if s.tzinfo == timezone.utc:
            return datetime.isoformat(s).replace('+00:00', 'Z')
        elif s.tzinfo is None:
            return datetime.isoformat(s) + 'Z'


def datetime_field():
    return field(
        metadata=config(
            encoder=toisoformat,
            decoder=fromisoformat,
        ),
        default = None,
    )


# https://docs.github.com/en/rest/reference/repos#create-a-deployment-status
# -------------------------------------------------------------------


@enum.unique
class DeploymentState(enum.Enum):
    error       = 'error'
    failure     = 'failure'
    inactive    = 'inactive'
    in_progress = 'in_progress'
    queued      = 'queued'
    pending     = 'pending'
    success     = 'success'


@dataclass_json
@dataclass
class DeploymentStatus:
    id: int
    node_id: str
    state: DeploymentState
    creator: dict

    description: str = None
    environment: str = None

    created_at: Optional[datetime] = datetime_field()
    updated_at: Optional[datetime] = datetime_field()

    target_url: str = None
    environment_url: str = None
    log_url: str = None

    #url: str = None # "https://api.github.com/repos/octocat/example/deployments/42/statuses/1"
    #deployment_url: str = None # "https://api.github.com/repos/octocat/example/deployments/42"
    #repository_url: str = None # "https://api.github.com/repos/octocat/example"


@dataclass_json
@dataclass
class Deployment:
    url: str

    id: int
    node_id: str
    sha: str
    ref: str = None
    task: str = None
    payload: object = None
    original_environment: str = None
    environment: str = None
    description: str = None

    created_at: Optional[datetime] = datetime_field()
    updated_at: Optional[datetime] = datetime_field()

    #statuses_url: Optional[str] = None # 'https://api.github.com/repos/mithro/skywater-pdk-libs-sky130_fd_sc_hd/deployments/365563468/statuses'
    #repository_url: Optional[str] = None # "https://api.github.com/repos/octocat/example"

    log_url: Optional[str] = None
    environment_url: Optional[str] = None

    transient_environment: Optional[bool] = None
    production_environment: Optional[bool] = None
    auto_inactive:  Optional[bool] = None

    @staticmethod
    def _pprint(p, object, stream, indent, allowance, context, level):
        p._pprint_dict(dataclasses.asdict(object), stream, indent, allowance, context, level)


pprint.PrettyPrinter._dispatch[Deployment.__repr__] = Deployment._pprint


# https://docs.github.com/en/rest/reference/repos#create-a-deployment-status

@dataclass_json
@dataclass
class DeploymentStatusCreate:
    # Header: accept = "application/vnd.github.v3+json"
    # URL: owner: str = ""
    # URL: repo: str = ""
    # URL: depolyment_id: int = 0
    state: DeploymentState

    #target_url: Optional[str] = None -- Old name for the log_url
    log_url: Optional[str] = None

    description: Optional[str] = None

    environment: Optional[str] = None
    environment_url: Optional[str] = None

    auto_inactive:  Optional[bool] = None


# https://docs.github.com/en/rest/reference/repos#create-a-deployment

@dataclass_json
@dataclass
class DeploymentCreate:
    # Header: accept = "application/vnd.github.v3+json"
    # URL: owner: str = ""
    # URL: repo: str = ""

    ref: str

    task: Optional[str] = None  # deploy or deploy:migrations

    auto_merge: Optional[bool] = None
    required_contexts: list[str] = field(default_factory=list)

    payload: Optional[object] = None

    environment: Optional[str] = None
    description: Optional[str] = None

    transient_environment: Optional[bool] = None
    production_environment: Optional[bool] = None


    @staticmethod
    def _pprint(p, object, stream, indent, allowance, context, level):
        p._pprint_dict(dataclasses.asdict(object), stream, indent, allowance, context, level)


pprint.PrettyPrinter._dispatch[DeploymentCreate.__repr__] = DeploymentCreate._pprint


test_check_run_output_json = [
]


if __name__ == "__main__":
    import doctest
    doctest.testmod()

    for t in test_check_run_output_json:
        o = Deployment.from_json(json.dumps(t))
        pprint.pprint(o)
        i = DeploymentCreate.from_output(o)
        pprint.pprint(i)
        print()
