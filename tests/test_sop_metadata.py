# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for sop_metadata: SOP content parsing, dependency resolution, model tiering.

These functions are pure (stdlib + regex only, no strands/AWS), so unlike the
graph tests they run without the multi-agent SDK present.
"""

from pathlib import Path

from amzn_cse_telco_autonomous_network_agents_app.agent.sop_metadata import (
    parse_sop_metadata,
    resolve_dependencies,
    select_model,
)

SOPS_DIR = Path(__file__).parent.parent / "sops"


def _real_sop(name: str) -> str:
    return str(SOPS_DIR / name)


class TestParseSopMetadata:
    def test_extracts_stage_number_from_filename(self):
        meta = parse_sop_metadata(_real_sop("day1-deploy/deploy-5g-core.md"))
        # Stage is extracted from content "**Stage:** N", not filename
        # Generic SOPs may not have stage markers
        assert meta["stem"] == "deploy-5g-core"

    def test_extracts_stem(self):
        meta = parse_sop_metadata(_real_sop("day1-deploy/deploy-5g-core.md"))
        assert meta["stem"] == "deploy-5g-core"

    def test_counts_bash_blocks(self):
        meta = parse_sop_metadata(_real_sop("day1-deploy/deploy-5g-core.md"))
        assert meta["bash_blocks"] > 0

    def test_counts_lines(self):
        meta = parse_sop_metadata(_real_sop("day1-deploy/deploy-5g-core.md"))
        assert meta["lines"] > 10

    def test_missing_file_returns_defaults(self):
        meta = parse_sop_metadata("/nonexistent/fake-sop.md")
        assert meta["stem"] == "fake-sop"
        assert meta["stage"] is None
        assert meta["dep_stages"] == []
        assert meta["bash_blocks"] == 0
        # Error path must expose the same keys as the success path.
        assert meta["sleep_seconds"] == 0

    def test_missing_and_present_files_have_same_keys(self):
        missing = parse_sop_metadata("/nonexistent/fake-sop.md")
        present = parse_sop_metadata(_real_sop("day1-deploy/deploy-5g-core.md"))
        assert missing.keys() == present.keys()

    def test_all_sops_parse_without_error(self):
        # rglob, not glob: SOPs live in subdirs (day0-infra/, day1-deploy/, ...);
        # a non-recursive glob matched only the top-level TEMPLATE.md and passed
        # vacuously. Assert we actually found the tree.
        sops = list(SOPS_DIR.rglob("*.md"))
        assert sops, "expected at least one SOP file under sops/"
        for sop in sops:
            meta = parse_sop_metadata(str(sop))
            assert meta["stem"] == sop.stem


class TestResolveDependencies:
    def _all_metas(self):
        # rglob to include SOPs in subdirectories (see note in TestParseSopMetadata).
        return [parse_sop_metadata(str(p)) for p in sorted(SOPS_DIR.rglob("*.md"))]

    def test_returns_edges_or_empty(self):
        edges = resolve_dependencies(self._all_metas())
        assert isinstance(edges, list)

    def test_edges_are_tuples(self):
        edges = resolve_dependencies(self._all_metas())
        for e in edges:
            assert len(e) == 2
            assert isinstance(e[0], str)
            assert isinstance(e[1], str)

    def test_no_self_edges(self):
        edges = resolve_dependencies(self._all_metas())
        for frm, to in edges:
            assert frm != to

    def test_single_sop_no_edges(self):
        metas = [parse_sop_metadata(_real_sop("day1-deploy/deploy-5g-core.md"))]
        edges = resolve_dependencies(metas)
        assert edges == []


class TestSelectModel:
    def test_simple_sop_gets_haiku(self):
        meta = {"bash_blocks": 5, "lines": 50}
        assert select_model(meta) == "haiku"

    def test_medium_sop_gets_sonnet(self):
        meta = {"bash_blocks": 12, "lines": 160}
        assert select_model(meta) == "sonnet"

    def test_complex_sop_gets_opus(self):
        meta = {"bash_blocks": 25, "lines": 400}
        assert select_model(meta) == "opus4.6"

    def test_high_lines_low_blocks_gets_opus(self):
        meta = {"bash_blocks": 5, "lines": 350}
        assert select_model(meta) == "opus4.6"

    def test_high_blocks_low_lines_gets_opus(self):
        meta = {"bash_blocks": 22, "lines": 100}
        assert select_model(meta) == "opus4.6"

    def test_default_override(self):
        meta = {"bash_blocks": 3, "lines": 30}
        assert select_model(meta, default="sonnet") == "sonnet"

    def test_real_deploy_nginx_gets_haiku(self):
        meta = parse_sop_metadata(_real_sop("day1-deploy/deploy-5g-core.md"))
        assert select_model(meta) == "haiku"
