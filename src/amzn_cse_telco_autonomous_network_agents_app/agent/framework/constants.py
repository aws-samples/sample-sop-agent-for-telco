# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Shared framework constants.

Values that are NOT customer-tunable config but ARE referenced in more than one
place. A value referenced from a single site stays inline at that site; it earns
a name here only once a second caller needs the same value, so this file never
becomes a junk drawer.
"""

from __future__ import annotations

# Default AWS region for Bedrock when neither config nor BEDROCK_REGION/AWS_REGION
# is set. Mirrors the default already used by SiteConfig.bedrock_region and
# model_resolver, named here so future framework code references one constant.
DEFAULT_BEDROCK_REGION = "us-west-2"

# Logged when a hot-reload changes the `plugins:` list. Plugin loading is
# load-once-at-boot: Python cannot safely unload a module whose tools an
# in-flight agent loop is holding, so a change to the plugin set takes effect
# only on pod restart.
PLUGINS_RELOAD_REQUIRES_RESTART = "The 'plugins' list changed but plugin loading is applied only at startup; restart the pod for the change to take effect."
