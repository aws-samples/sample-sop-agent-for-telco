# Security Policy

## Reporting a Vulnerability

If you discover a potential security issue in this project, **do not** create a
public GitHub issue. Instead, please notify AWS Security via our
[vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/)
or directly via email to `aws-security@amazon.com`.

Please do **not** create a public GitHub issue.

## Supported Versions

This is **sample code** for demonstration and learning purposes. It is not
intended for production use. Only the `main` branch receives security updates.

| Branch | Supported |
| ------ | --------- |
| `main` | ✅ |
| `workshop` | ❌ (frozen for live workshop event) |

## Scope

This sample code includes:
- Python application code (`agent/`, `evals/`)
- Helm chart (`helm/anra/`)
- Container image build (`Dockerfile`, `docker-entrypoint.sh`)
- CloudFormation infrastructure (`assets/workshop-infra.yaml`)

Findings in any of the above are in scope. Issues in upstream dependencies
(e.g. Open5GS, UERANSIM, ArgoCD) should be reported to the respective projects.

## Disclaimer

This is sample code for non-production usage. You are responsible for testing,
securing, and optimizing the code as appropriate for production-grade use based
on your specific quality control practices and standards. See [LICENSE](LICENSE)
for details.
