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


# -------------------------------------------------------------------
# Info for an existing check run.
# -------------------------------------------------------------------


# Annotations
# https://api.github.com/repos/octocat/hello-world/check-runs/42/annotations
# -------------------------------------------------------------------


@enum.unique
class CheckRunAnnotationLevel(enum.Enum):
    notice      = 'notice'
    warning     = 'warning'
    failure     = 'failure'


@dataclass_json
@dataclass
class CheckRunAnnotation:
    path: str
    start_line: int
    end_line: int

    annotation_level: CheckRunAnnotationLevel
    message: str
    title: str
    raw_details: str

    start_column: Optional[int] = None
    end_column: Optional[int] = None

@enum.unique
class CheckStatus(enum.Enum):
    queued      = 'queued'
    in_progress = 'in_progress'
    completed   = 'completed'


# Check Runs
# https://api.github.com/repos/octocat/hello-world/check-runs/42
# -------------------------------------------------------------------


@enum.unique
class CheckConclusion(enum.Enum):
    action_required     = 'action_required'
    cancelled           = 'cancelled'
    failure             = 'failure'
    neutral             = 'neutral'
    success             = 'success'
    skipped             = 'skipped'
    stale               = 'stale'
    timed_out           = 'timed_out'


@dataclass_json
@dataclass
class CheckRunOutput:
    title: Optional[str] = None
    summary: Optional[str] = None
    text: Optional[str] = None

    annotations_count: int = 0
    annotations_url: Optional[str] = None


@dataclass_json
@dataclass
class CheckSuite:
    id: int


@dataclass_json
@dataclass
class CheckRun:

    id: int
    node_id: str

    name: str
    head_sha: str

    details_url: str
    external_id: str

    output: CheckRunOutput

    url: str
    html_url: str

    #app: dict
    check_suite: Optional[CheckSuite] = None

    status: Optional[CheckStatus] = None
    started_at: Optional[datetime] = datetime_field()
    completed_at: Optional[datetime] = datetime_field()
    conclusion: Optional[CheckConclusion] = None

    pull_requests: Optional[list[dict]] = None

    @staticmethod
    def _pprint(p, object, stream, indent, allowance, context, level):
        p._pprint_dict(dataclasses.asdict(object), stream, indent, allowance, context, level)


pprint.PrettyPrinter._dispatch[CheckRun.__repr__] = CheckRun._pprint


# -------------------------------------------------------------------
# Creating a check run.
# -------------------------------------------------------------------


@dataclass_json
@dataclass
class CheckRunCreateAction:
    label: str
    description: str
    identifier: str


@dataclass_json
@dataclass
class CheckRunCreateOutputImage:
    alt: str
    image_url: str
    caption: str


@dataclass_json
@dataclass
class CheckRunCreateOutput:
    title: str      # Required
    summary: str    # Required
    text: str

    annotations: list[CheckRunAnnotation] = field(default_factory=list)
    images: list[CheckRunCreateOutputImage] = field(default_factory=list)


@dataclass_json
@dataclass
class CheckRunCreate:
    # Header: accept = "application/vnd.github.v3+json"
    # URL: owner: str = ""
    # URL: repo: str = ""
    # URL: check_run_id: str = ""

    name: str
    head_sha: str

    details_url: Optional[str] = None
    external_id: Optional[str] = None

    status: Optional[CheckStatus] = CheckStatus.queued
    started_at: Optional[datetime] = datetime_field()

    conclusion: Optional[CheckConclusion] = None
    completed_at: Optional[datetime] = datetime_field()

    output: Optional[CheckRunCreateOutput] = None

    actions: list[CheckRunCreateAction] = field(default_factory=list)


    @classmethod
    def from_output(cls, check: CheckRun, annotations: Optional[list[CheckRunAnnotation]] = None):
        """Create a CheckRunCreate from a CheckRun object."""
        assert isinstance(check, CheckRun), (type(check), check)

        key_action = {
            'check_suite':   'remove',
            'html_url' :     'remove',
            'id':            'remove',
            'node_id':       'remove',
            'pull_requests': 'remove',
            'url':           'remove',
            'output':        'remove', # Special cases
        }

        input_fields = set()
        for field in dataclasses.fields(cls):
            input_fields.add(field.name)

        new_check = {}

        # Special handling for the `output` field
        assert 'output' in input_fields, input_fields
        input_fields.remove('output')
        new_check['output'] = CheckRunCreateOutput(
            title=check.output.title,
            summary=check.output.summary,
            text=check.output.text,
            annotations=[],
            images=[],
        )
        if check.output.annotations_count > 0:
            assert check.output.annotations_url is not None, check.output
            assert annotations is not None, annotations
            assert len(annotations) == check.output.annotations_count, (
                len(annotations), check.output.annotations_count)

        for field in dataclasses.fields(check):
            if field.name in input_fields:
                new_check[field.name] = getattr(check, field.name)
                continue

            if field.name not in key_action:
                raise ValueError(f"{field.name} not found.")

            action = key_action.pop(field.name)
            if action == 'remove':
                continue
            else:
                raise ValueError(f"Unknown action {action}")

        assert not key_action, "%s\n%s" % (pprint.pformat(key_action), pprint.pformat(new_check))
        return cls(**new_check)

    @staticmethod
    def _pprint(p, object, stream, indent, allowance, context, level):
        p._pprint_dict(dataclasses.asdict(object), stream, indent, allowance, context, level)


pprint.PrettyPrinter._dispatch[CheckRunCreate.__repr__] = CheckRunCreate._pprint


test_check_run_output_json = [
  {'check_suite': {'id': 2635805147},
   'completed_at': '2021-05-03T01:48:37Z',
   'conclusion': 'success',
   'details_url': 'https://github.com/mithro/skywater-pdk-libs-sky130_fd_sc_hd/runs/2488819601',
   'external_id': '17fd8ba9-7af4-5179-dd33-af07a972ec4b',
   'head_sha': 'c618aa17146d00598f4617ca05c8a29917c84551',
   'html_url': 'https://github.com/mithro/skywater-pdk-libs-sky130_fd_sc_hd/runs/2488819601',
   'id': 2488819601,
   'name': 'Basic',
   'node_id': 'MDg6Q2hlY2tSdW4yNDg4ODE5NjAx',
   'output': {'annotations_count': 0,
              'annotations_url': 'https://api.github.com/repos/mithro/skywater-pdk-libs-sky130_fd_sc_hd/check-runs/2488819601/annotations',
              'summary': None,
              'text': None,
              'title': None},
   'pull_requests': [],
   'started_at': '2021-05-03T01:47:50Z',
   'status': 'completed',
   'url': 'https://api.github.com/repos/mithro/skywater-pdk-libs-sky130_fd_sc_hd/check-runs/2488819601'},
  {'check_suite': {'id': 2635803086},
   'completed_at': '2021-05-03T01:48:37Z',
   'conclusion': 'success',
   'details_url': 'https://github.com/mithro/skywater-pdk-libs-sky130_fd_sc_hd/runs/2505436285',
   'external_id': 'backport main Basic',
   'head_sha': '31760587bfd94263e16af4b310e1e622803c1d14',
   'html_url': 'https://github.com/mithro/skywater-pdk-libs-sky130_fd_sc_hd/runs/2505436285',
   'id': 2505436285,
   'name': 'main - Basic',
   'node_id': 'MDg6Q2hlY2tSdW4yNTA1NDM2Mjg1',
   'output': {'annotations_count': 0,
              'annotations_url': 'https://api.github.com/repos/mithro/skywater-pdk-libs-sky130_fd_sc_hd/check-runs/2505436285/annotations',
              'summary': 'Run of Basic on Pull Request #1 (run #14 with git hash '
                         '31760 backported to main.\n',
              'text': 'Run of Basic on Pull Request #1 (run #14 with git hash '
                      '31760 backported to main.\n',
              'title': 'main - Basic'},
   'pull_requests': [],
   'started_at': '2021-05-03T01:47:50Z',
   'status': 'completed',
   'url': 'https://api.github.com/repos/mithro/skywater-pdk-libs-sky130_fd_sc_hd/check-runs/2505436285'},
  {'check_suite': {'id': 2635803149},
   'completed_at': '2021-05-03T02:32:16Z',
   'conclusion': 'success',
   'details_url': 'https://github.com/mithro/skywater-pdk-libs-sky130_fd_sc_hd/runs/2488963934',
   'external_id': '17fd8ba9-7af4-5179-dd33-af07a972ec4b',
   'head_sha': '31760587bfd94263e16af4b310e1e622803c1d14',
   'html_url': 'https://github.com/mithro/skywater-pdk-libs-sky130_fd_sc_hd/runs/2488963934',
   'id': 2488963934,
   'name': 'Basic',
   'node_id': 'MDg6Q2hlY2tSdW4yNDg4OTYzOTM0',
   'output': {'annotations_count': 0,
              'annotations_url': 'https://api.github.com/repos/mithro/skywater-pdk-libs-sky130_fd_sc_hd/check-runs/2488963934/annotations',
              'summary': None,
              'text': None,
              'title': None},
   'pull_requests': [],
   'started_at': '2021-05-03T02:31:29Z',
   'status': 'completed',
   'url': 'https://api.github.com/repos/mithro/skywater-pdk-libs-sky130_fd_sc_hd/check-runs/2488963934'},
  {'check_suite': {'id': 2635803086},
   'completed_at': '2021-05-03T01:47:42Z',
   'conclusion': 'success',
   'details_url': 'https://github.com/mithro/skywater-pdk-libs-sky130_fd_sc_hd/runs/2488817478',
   'external_id': '9995a1ec-1db8-510e-fb2a-93c27ceb2b21',
   'head_sha': '31760587bfd94263e16af4b310e1e622803c1d14',
   'html_url': 'https://github.com/mithro/skywater-pdk-libs-sky130_fd_sc_hd/runs/2488817478',
   'id': 2488817478,
   'name': 'Run',
   'node_id': 'MDg6Q2hlY2tSdW4yNDg4ODE3NDc4',
   'output': {'annotations_count': 0,
              'annotations_url': 'https://api.github.com/repos/mithro/skywater-pdk-libs-sky130_fd_sc_hd/check-runs/2488817478/annotations',
              'summary': None,
              'text': None,
              'title': None},
   'pull_requests': [],
   'started_at': '2021-05-03T01:47:03Z',
   'status': 'completed',
   'url': 'https://api.github.com/repos/mithro/skywater-pdk-libs-sky130_fd_sc_hd/check-runs/2488817478'},
  {'check_suite': {'id': 2635803111},
   'completed_at': '2021-05-03T01:46:57Z',
   'conclusion': 'success',
   'details_url': 'https://github.com/marketplace/wip',
   'external_id': '',
   'head_sha': '31760587bfd94263e16af4b310e1e622803c1d14',
   'html_url': 'https://github.com/mithro/skywater-pdk-libs-sky130_fd_sc_hd/runs/2488817360',
   'id': 2488817360,
   'name': 'WIP',
   'node_id': 'MDg6Q2hlY2tSdW4yNDg4ODE3MzYw',
   'output': {'annotations_count': 0,
              'annotations_url': 'https://api.github.com/repos/mithro/skywater-pdk-libs-sky130_fd_sc_hd/check-runs/2488817360/annotations',
              'summary': 'No match found based on configuration',
              'text': 'By default, WIP only checks the pull request title for '
                      'the terms "WIP", "Work in progress" and "🚧".\n'
                      '\n'
                      'You can configure both the terms and the location that '
                      'the WIP app will look for by signing up for the pro plan: '
                      'https://github.com/marketplace/wip. All revenue will be '
                      'donated to [Processing | '
                      'p5.js](https://donorbox.org/supportpf2019-fundraising-campaign) '
                      '– one of the most diverse and impactful Open Source '
                      'community there is.',
              'title': 'Ready for review'},
   'pull_requests': [],
   'started_at': '2021-05-03T01:46:56Z',
   'status': 'completed',
   'url': 'https://api.github.com/repos/mithro/skywater-pdk-libs-sky130_fd_sc_hd/check-runs/2488817360'},
  {'check_suite': {'id': 2635805147},
  'completed_at': '2021-05-03T01:48:37Z',
  'conclusion': 'success',
  'details_url': 'https://github.com/mithro/skywater-pdk-libs-sky130_fd_sc_hd/runs/2488819601',
  'external_id': '17fd8ba9-7af4-5179-dd33-af07a972ec4b',
  'head_sha': 'c618aa17146d00598f4617ca05c8a29917c84551',
  'html_url': 'https://github.com/mithro/skywater-pdk-libs-sky130_fd_sc_hd/runs/2488819601',
  'id': 2488819601,
  'name': 'Basic',
  'node_id': 'MDg6Q2hlY2tSdW4yNDg4ODE5NjAx',
  'output': {'annotations_count': 0,
             'annotations_url': 'https://api.github.com/repos/mithro/skywater-pdk-libs-sky130_fd_sc_hd/check-runs/2488819601/annotations',
             'summary': None,
             'text': None,
             'title': None},
  'pull_requests': [],
  'started_at': '2021-05-03T01:47:50Z',
  'status': 'completed',
  'url': 'https://api.github.com/repos/mithro/skywater-pdk-libs-sky130_fd_sc_hd/check-runs/2488819601'},
]


if __name__ == "__main__":
    import doctest
    doctest.testmod()

    for t in test_check_run_output_json:
        o = CheckRun.from_json(json.dumps(t))
        pprint.pprint(o)
        i = CheckRunCreate.from_output(o)
        pprint.pprint(i)
        print()
