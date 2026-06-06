# AWS Terminology for Telco Engineers

Quick reference for telco engineers encountering AWS terms in this workshop.

## Compute and Containers

| Term | What it is | Telco analogy |
|------|-----------|---------------|
| EKS (Elastic Kubernetes Service) | Managed Kubernetes cluster | Like your NFVI platform (OpenStack/VMware) but containers |
| EC2 | Virtual machines | Like VNF VMs on your NFVI |
| Pod | Smallest deployable unit in K8s (one or more containers) | Like a single NF instance |
| Deployment | Manages replicas of a pod template | Like an NF scaling group |
| Namespace | Logical isolation within a cluster | Like a network slice or tenant partition |
| Node | A physical or virtual machine in the cluster | Like a blade in your ATCA shelf |

## Networking

| Term | What it is | Telco analogy |
|------|-----------|---------------|
| VPC (Virtual Private Cloud) | Isolated network environment | Like a transport network segment |
| Subnet | IP range within a VPC | Like a VLAN |
| Security Group | Stateful firewall rules per resource | Like ACLs on your router |
| Load Balancer (ALB/NLB) | Distributes traffic across targets | Like SCP/SLB in the core |
| Route 53 | DNS service | Like your DNS infrastructure for NF discovery |

## Storage and Data

| Term | What it is | Telco analogy |
|------|-----------|---------------|
| EBS (Elastic Block Store) | Persistent disk volumes | Like SAN storage for your NFs |
| S3 | Object storage | Like your CDR/log archive |
| PVC (PersistentVolumeClaim) | K8s request for storage | Pod asking for a disk |

## Identity and Security

| Term | What it is | Telco analogy |
|------|-----------|---------------|
| IAM | Identity and Access Management | Like your AAA/RADIUS but for cloud APIs |
| IRSA | IAM Roles for Service Accounts | Giving a pod AWS permissions (like giving an NF network access) |
| Secrets Manager | Stores credentials securely | Like your HSM for subscriber keys |

## Monitoring and Operations

| Term | What it is | Telco analogy |
|------|-----------|---------------|
| CloudWatch | Metrics, logs, alarms | Like your OSS/NMS (Prometheus + Grafana) |
| SSM (Systems Manager) | Remote access and automation | Like your element manager / SSH gateway |
| CloudFormation | Infrastructure as code | Like your network orchestrator (ONAP/OSM) |
| Helm | K8s package manager | Like your VNF package (CSAR) installer |
| ArgoCD | GitOps continuous delivery | Auto-deploys when config changes in Git |

## Workshop-Specific

| Term | What it is |
|------|-----------|
| Workshop Studio | AWS service that provisions temporary accounts for training |
| Jump host | EC2 instance you SSH into (via SSM) to access the cluster |
| Bootstrap | The 15-20 min setup script that creates EKS + deploys 5G core |
| ANRA | This workshop's AI agent — monitors and remediates the 5G network |
| SOP | Standard Operating Procedure — step-by-step remediation playbook |
| Bedrock | AWS managed AI service (runs the Claude models powering ANRA) |
