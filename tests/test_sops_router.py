# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the read-only SOP viewer, including Bedrock-generated SOPs."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amzn_cse_telco_autonomous_network_agents_app.agent.routers import sops


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "sops" / "day2-remediate").mkdir(parents=True)
    (repo / "sops" / "day2-remediate" / "pod-restart.md").write_text("# Pod restart\n**Severity:** major\n")
    gen = tmp_path / "generated-sops"
    gen.mkdir()
    (gen / "remediate-nf_crashloop.md").write_text("# Remediate nf_crashloop\n")
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    (scratch / "remediate-Free5GCWorkshopPipelineTest-enriched.md").write_text("# Enriched pipeline test\n")
    (scratch / "notes.md").write_text("# private notes\n")
    (tmp_path / "secret.md").write_text("# outside\n")
    (repo / "secret.md").write_text("# outside\n")
    (gen / "remediate-dup.md").write_text("# from generated-sops\n")
    (scratch / "remediate-dup.md").write_text("# from tmp\n")
    monkeypatch.setenv("SOP_REPO", str(repo))
    monkeypatch.setattr(sops, "GENERATED_SOP_DIRS", [gen, scratch])
    return {"repo": repo, "gen": gen, "scratch": scratch, "root": tmp_path}


@pytest.fixture
def client(dirs):
    app = FastAPI()
    app.include_router(sops.router)
    return TestClient(app)


def test_generated_sops_are_listed_alongside_repo_sops(client):
    body = client.get("/api/sops").json()
    by_path = {s["path"]: s for s in body["sops"]}
    assert by_path["day2-remediate/pod-restart.md"] == {
        "path": "day2-remediate/pod-restart.md",
        "title": "Pod restart",
        "severity": "major",
        "phase": "day2-remediate",
    }
    gen = by_path["generated/remediate-nf_crashloop.md"]
    assert gen["phase"] == "generated" and gen["generated"] is True
    assert gen["title"] == "Remediate nf_crashloop"
    assert by_path["generated/remediate-Free5GCWorkshopPipelineTest-enriched.md"]["phase"] == "generated"
    assert body["count"] == 4


def test_unrelated_tmp_file_is_not_listed_or_served(client):
    paths = [s["path"] for s in client.get("/api/sops").json()["sops"]]
    assert not any("notes" in p for p in paths)
    assert client.get("/api/sops/generated/notes.md").status_code == 404
    assert client.get("/api/sops/notes.md").status_code == 404


def test_generated_sop_is_served_by_prefix_and_bare_name(client):
    r = client.get("/api/sops/generated/remediate-Free5GCWorkshopPipelineTest-enriched.md")
    assert r.status_code == 200
    assert r.json()["content"] == "# Enriched pipeline test\n"
    assert r.json()["generated"] is True
    bare = client.get("/api/sops/remediate-nf_crashloop.md")
    assert bare.status_code == 200 and bare.json()["path"] == "generated/remediate-nf_crashloop.md"


def test_repo_sop_still_served_and_missing_repo_sop_is_404(client):
    assert client.get("/api/sops/day2-remediate/pod-restart.md").json()["content"].startswith("# Pod restart")
    assert client.get("/api/sops/day2-remediate/missing.md").status_code == 404


@pytest.mark.parametrize(
    "url",
    [
        "/api/sops/%2E%2E/secret.md",  # repo/sops/../secret.md exists
        "/api/sops/%2E%2E/%2E%2E/secret.md",  # tmp_path/secret.md exists
        "/api/sops/generated/%2E%2E/%2E%2E/secret.md",
        "/api/sops/generated/remediate-x.md%5C..",  # backslash
        "/api/sops/generated/sub/remediate-x.md",  # slash after the prefix
    ],
)
def test_traversal_over_http_is_rejected_with_400(client, url):
    r = client.get(url)
    assert r.status_code == 400, r.text
    assert "outside" not in r.text


def test_name_clash_prefers_earlier_generated_dir(client):
    r = client.get("/api/sops/generated/remediate-dup.md")
    assert r.json()["content"] == "# from generated-sops\n"
    assert [s["path"] for s in client.get("/api/sops").json()["sops"]].count("generated/remediate-dup.md") == 1


def test_symlink_out_of_generated_dir_is_not_served(client, dirs):
    (dirs["scratch"] / "remediate-evil.md").symlink_to(dirs["root"] / "secret.md")
    assert client.get("/api/sops/generated/remediate-evil.md").status_code == 404
    assert "generated/remediate-evil.md" not in [s["path"] for s in client.get("/api/sops").json()["sops"]]


def test_symlink_to_non_generated_name_in_same_dir_is_not_served(client, dirs):
    (dirs["scratch"] / "remediate-link.md").symlink_to(dirs["scratch"] / "notes.md")
    assert client.get("/api/sops/generated/remediate-link.md").status_code == 404
    assert "generated/remediate-link.md" not in [s["path"] for s in client.get("/api/sops").json()["sops"]]


def test_non_utf8_generated_sop_is_skipped_and_404(client, dirs):
    (dirs["scratch"] / "remediate-bin.md").write_bytes(b"\xff\xfe\x00bad")
    r = client.get("/api/sops")
    assert r.status_code == 200
    assert "generated/remediate-bin.md" not in [s["path"] for s in r.json()["sops"]]
    assert client.get("/api/sops/generated/remediate-bin.md").status_code == 404


def test_repo_sop_deleted_after_listing_is_404(client, dirs):
    sop = dirs["repo"] / "sops" / "day2-remediate" / "transient.md"
    sop.write_text("# Transient\n")
    assert "day2-remediate/transient.md" in [s["path"] for s in client.get("/api/sops").json()["sops"]]
    sop.unlink()
    assert client.get("/api/sops/day2-remediate/transient.md").status_code == 404


def test_view_path_for_decision_cards(dirs):
    assert sops.generated_view_path(str(dirs["gen"] / "remediate-nf_crashloop.md")) == "generated/remediate-nf_crashloop.md"
    assert sops.generated_view_path(str(dirs["scratch"] / "remediate-x-enriched.md")) == "generated/remediate-x-enriched.md"
    assert sops.generated_view_path(str(dirs["repo"] / "sops" / "day2-remediate" / "pod-restart.md")) == "day2-remediate/pod-restart.md"
    assert sops.generated_view_path("day2-remediate/pod-restart.md") == "day2-remediate/pod-restart.md"
    assert sops.generated_view_path(str(dirs["scratch"] / "notes.md")) == ""
    assert sops.generated_view_path("/elsewhere/remediate-x.md") == ""
    assert sops.generated_view_path("") == ""


def test_approvals_payload_carries_sop_view_path(dirs, monkeypatch):
    from amzn_cse_telco_autonomous_network_agents_app.agent.routers import approvals

    entry = {"alarm_name": "nf_crashloop", "sop": str(dirs["gen"] / "remediate-nf_crashloop.md")}
    monkeypatch.setattr(approvals, "snapshot_pending_approvals", lambda: {"nf_crashloop": entry})
    card = approvals.get_approvals()["pending"][0]
    assert card["sop_view_path"] == "generated/remediate-nf_crashloop.md"
    assert card["sop"] == entry["sop"]
    assert "sop_view_path" not in entry


def test_viewer_covers_the_paths_the_monitor_writes():
    """monitor.py writes generated/enriched SOPs; the viewer must read the same places."""
    import inspect
    from pathlib import Path

    from amzn_cse_telco_autonomous_network_agents_app.agent import monitor

    gen_src = inspect.getsource(monitor._generate_sop)
    enrich_src = inspect.getsource(monitor._enrich_sop_file)
    for d in sops.GENERATED_SOP_DIRS:
        assert str(d) in gen_src or str(d) in enrich_src, f"{d} is not written by monitor.py"
    assert Path("/tmp/generated-sops") in sops.GENERATED_SOP_DIRS
    assert sops._is_generated_name("remediate-anything.md")
    assert sops._is_generated_name("free5gc-pod-crashloop-enriched.md")


def test_draft_is_hidden_when_its_enriched_copy_exists(client, dirs):
    (dirs["gen"] / "remediate-Free5GCWorkshopPipelineTest.md").write_text("# Draft pipeline test\n")
    paths = [s["path"] for s in client.get("/api/sops").json()["sops"]]
    assert "generated/remediate-Free5GCWorkshopPipelineTest-enriched.md" in paths
    assert "generated/remediate-Free5GCWorkshopPipelineTest.md" not in paths
    assert "generated/remediate-nf_crashloop.md" in paths  # no enriched copy: still listed
    draft = client.get("/api/sops/generated/remediate-Free5GCWorkshopPipelineTest.md")
    assert draft.status_code == 200
