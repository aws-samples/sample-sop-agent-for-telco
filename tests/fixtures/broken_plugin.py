# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A plugin that raises on import — proves the loader fails loud, not silent."""

raise RuntimeError("intentional import-time failure for plugin-loader test")
