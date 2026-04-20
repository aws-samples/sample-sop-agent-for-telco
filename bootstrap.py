# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#!/usr/bin/env python3
"""Bootstrap script to deploy the SOP Agent using Strands SDK.

This script creates an AI agent that executes the deployment SOP,
adapting to the target environment and handling missing prerequisites.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Deploy SOP Agent to EKS")
    parser.add_argument("--cluster", required=True, help="EKS cluster name")
    parser.add_argument("--region", default="us-west-2", help="AWS region")
    parser.add_argument("--profile", default=None, help="AWS profile")
    parser.add_argument("--dry-run", action="store_true", help="Print SOP without executing")
    args = parser.parse_args()

    sop_path = Path(__file__).parent / "sops" / "00-deploy-sop-agent.md"
    if not sop_path.exists():
        print(f"Error: SOP not found at {sop_path}")
        sys.exit(1)

    sop_content = sop_path.read_text()
    sop_content = sop_content.replace("my-eks-cluster", args.cluster)

    if args.dry_run:
        print("=== Deployment SOP (dry-run) ===\n")
        print(sop_content)
        return

    try:
        import boto3
        from strands import Agent, tool
        from strands.models import BedrockModel
    except ImportError:
        print("Error: Install dependencies: pip install strands-agents boto3")
        sys.exit(1)

    session = boto3.Session(
        profile_name=args.profile,
        region_name=args.region
    )

    model = BedrockModel(
        model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        boto_session=session
    )

    env = {
        **os.environ,
        "AWS_REGION": args.region,
        "AWS_DEFAULT_REGION": args.region,
        "CLUSTER_NAME": args.cluster,
    }
    if args.profile:
        env["AWS_PROFILE"] = args.profile

    @tool
    def run_shell(command: str) -> str:
        """Execute a shell command and return output.

        Security Note: This tool intentionally uses shell=True to execute SOP commands.
        The agent runs in a controlled environment (container/EKS pod) with limited
        permissions defined by the ServiceAccount. Commands come from trusted SOPs.

        Args:
            command: The shell command to execute
        """
        import shlex
        try:
            # For simple commands, try to avoid shell=True
            # Fall back to shell=True for complex commands with pipes, redirects, etc.
            if any(c in command for c in ['|', '>', '<', '&&', '||', ';', '$(']):
                result = subprocess.run(
                    command,
                    shell=True,  # nosec B602 - required for shell features in SOP commands
                    capture_output=True,
                    text=True,
                    timeout=600,
                    env=env,
                    cwd=str(Path(__file__).parent)
                )
            else:
                result = subprocess.run(
                    shlex.split(command),
                    capture_output=True,
                    text=True,
                    timeout=600,
                    env=env,
                    cwd=str(Path(__file__).parent)
                )
            output = (result.stdout + result.stderr).strip()
            return output if output else "(no output)"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 600 seconds"
        except Exception as e:
            return f"Error: {e}"

    agent = Agent(
        model=model,
        tools=[run_shell],
        system_prompt="""You are a deployment automation agent executing an SOP to deploy the Strands SOP Agent to EKS.

Your approach:
1. Execute each step using run_shell
2. Check if output matches expected result
3. If a prerequisite is missing, install it following the SOP's guidance
4. Adapt commands to the detected OS (check with `uname -s` if needed)
5. If a step fails, diagnose the issue and try alternative approaches from the SOP
6. Only proceed to the next phase after the current phase succeeds

Be resourceful - if something fails, try the alternative approaches mentioned in the SOP.
Report clear status after each phase."""
    )

    print(f"Deploying SOP Agent to: {args.cluster} ({args.region})")
    print("=" * 50)
    print("The agent will now execute the deployment SOP...")
    print("This may take several minutes.\n")

    response = agent(
        f"Execute this deployment SOP. Use run_shell for each command. "
        f"Handle any missing prerequisites by installing them.\n\n{sop_content}"
    )
    print(response)


if __name__ == "__main__":
    main()
