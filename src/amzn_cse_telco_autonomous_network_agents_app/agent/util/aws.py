# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""AWS session helpers.

A single place to construct boto3 sessions so the profile/region convention is
consistent across agent modules. Previously every call site repeated
``boto3.Session(profile_name=profile or None, region_name=region)``; this
centralizes that one pattern.
"""

from __future__ import annotations

from typing import Optional

import boto3  # type: ignore[import-untyped]  # boto3 ships no type stubs


def aws_session(profile: Optional[str] = None, region: Optional[str] = None) -> boto3.Session:
    """Build a boto3 Session with the project's profile/region convention.

    An empty-string profile is treated as "no profile" (use the default
    credential chain), matching the ``profile or None`` idiom the call sites
    used inline. Passing region=None lets boto3 resolve the region from the
    environment / config as usual.

    Args:
        profile: AWS named profile, or None/empty to use the default chain.
        region: AWS region, or None to defer to boto3's own resolution.
    """
    return boto3.Session(profile_name=profile or None, region_name=region)
