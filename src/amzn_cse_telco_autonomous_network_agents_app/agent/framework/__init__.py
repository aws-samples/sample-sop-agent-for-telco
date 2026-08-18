# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Modularity framework — the abstraction layer that lets customers extend ANO
without editing the engine.

The contract for adding a feature:

    1. Implement a contract  — write a class/function satisfying a kind's ABC
       (see ``contracts``) or a Strands ``@tool``.
    2. Register it           — decorate with ``@register_tool`` / ``@register``
       (see ``registry``), which validates it against the kind's contract.
    3. Reference it in config — list the module under ``plugins:`` in
       agent-config.yaml, and (for SELECT kinds) name it via the kind's config
       selector.
    4. Never edit the engine — core algorithms (correlation, remediation steps)
       stay in the engine; only the seams it talks through are pluggable.

What is pluggable is declared as a set of *extension points* (``ExtensionKind``),
each with a contract and a resolution mode (``ResolutionMode``). That table is
the abstraction layer; everything else is implementation.
"""
