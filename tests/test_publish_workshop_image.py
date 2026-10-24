import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLISH_SCRIPT = ROOT / "scripts" / "publish-workshop-image.sh"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def run_publisher(*args: str, ref: str = "workshop-v3") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GITHUB_REF_NAME"] = ref
    return subprocess.run(
        ["bash", str(PUBLISH_SCRIPT), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_publish_script_dry_run_has_no_aws_or_docker_side_effects():
    result = run_publisher("--dry-run", "--skip-validation", "--allow-dirty", "--publish-dev")

    assert result.returncode == 0, result.stderr
    assert "DRY RUN" in result.stdout
    assert "account:    833542146025" in result.stdout
    assert "repository: public.ecr.aws/t2j9i5y9/anra-workshop" in result.stdout
    assert "workshop-v3-" in result.stdout
    assert " dev" in result.stdout
    assert ":latest" not in result.stdout


def test_publish_script_rejects_non_workshop_branch():
    result = run_publisher("--dry-run", "--skip-validation", "--allow-dirty", ref="main")

    assert result.returncode != 0
    assert "restricted to workshop-v3" in result.stderr


def test_publish_script_allows_dirty_override_only_for_dry_run():
    result = run_publisher("--skip-validation", "--allow-dirty")

    assert result.returncode != 0
    assert "--allow-dirty is accepted only with --dry-run" in result.stderr


def test_ci_publish_job_delegates_to_publish_script():
    workflow = CI_WORKFLOW.read_text()

    assert "scripts/publish-workshop-image.sh --skip-validation --publish-dev" in workflow
    assert "docker build -t $REPO" not in workflow
    assert "docker push $REPO" not in workflow
    assert "needs: [unit-tests, code-quality, security, helm-validate, shellcheck]" in workflow
