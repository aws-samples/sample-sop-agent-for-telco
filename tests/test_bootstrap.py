# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for bootstrap.py deployment script."""
import subprocess  # nosec B404 - required for testing CLI
import sys
from pathlib import Path


BOOTSTRAP_PATH = Path(__file__).parent.parent / "scripts" / "bootstrap.py"


class TestBootstrapCLI:
    """Test CLI argument parsing."""

    def test_help_flag(self):
        """Test --help shows usage."""
        result = subprocess.run(  # nosec B603 B607 - testing own script
            [sys.executable, str(BOOTSTRAP_PATH), "--help"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "--cluster" in result.stdout

    def test_missing_cluster_fails(self):
        """Test that missing --cluster argument fails."""
        result = subprocess.run(  # nosec B603 B607 - testing own script
            [sys.executable, str(BOOTSTRAP_PATH)],
            capture_output=True, text=True
        )
        assert result.returncode != 0
        assert "required" in result.stderr.lower() or "cluster" in result.stderr.lower()

    def test_dry_run_shows_sop(self):
        """Test --dry-run prints SOP without executing."""
        result = subprocess.run(  # nosec B603 B607 - testing own script
            [sys.executable, str(BOOTSTRAP_PATH), "--cluster", "test", "--dry-run"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "Deploy SOP Agent" in result.stdout
        assert "Phase 1" in result.stdout

    def test_cluster_name_substitution(self):
        """Test cluster name is substituted in SOP."""
        result = subprocess.run(  # nosec B603 B607 - testing own script
            [sys.executable, str(BOOTSTRAP_PATH), "--cluster", "my-test-cluster", "--dry-run"],
            capture_output=True, text=True
        )
        assert "my-test-cluster" in result.stdout


class TestSOPContent:
    """Test SOP file content."""

    def test_sop_exists(self):
        """Test deployment SOP file exists."""
        sop_path = Path(__file__).parent.parent / "sops" / "00-deploy-sop-agent.md"
        assert sop_path.exists()

    def test_sop_has_phases(self):
        """Test SOP has all required phases."""
        sop_path = Path(__file__).parent.parent / "sops" / "00-deploy-sop-agent.md"
        content = sop_path.read_text()
        assert "Phase 1: Prerequisites" in content
        assert "Phase 2: Cluster Setup" in content
        assert "Phase 3: Build and Push" in content
        assert "Phase 4: IAM Setup" in content
        assert "Phase 5: Deploy" in content
        assert "Phase 6: CloudFront" in content
        assert "Phase 7: Verification" in content

    def test_sop_has_troubleshooting(self):
        """Test SOP includes troubleshooting section."""
        sop_path = Path(__file__).parent.parent / "sops" / "00-deploy-sop-agent.md"
        content = sop_path.read_text()
        assert "Troubleshooting" in content


class TestDeployScript:
    """Test deploy.sh wrapper script."""

    def test_deploy_script_exists(self):
        """Test deploy.sh exists and is executable."""
        deploy_path = Path(__file__).parent.parent / "scripts" / "deploy.sh"
        assert deploy_path.exists()
        assert deploy_path.stat().st_mode & 0o111  # executable

    def test_deploy_script_help(self):
        """Test deploy.sh --help works."""
        deploy_path = Path(__file__).parent.parent / "scripts" / "deploy.sh"
        result = subprocess.run(  # nosec B603 B607 - testing own script
            ["bash", str(deploy_path), "--help"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "--cluster" in result.stdout
