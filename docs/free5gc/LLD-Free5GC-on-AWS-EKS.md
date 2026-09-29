# AWS Infrastructure Low-Level Design Document (LLD) for Free5GC

This document is Free5GC LLD with all details of AWS resources needed for a successful deployment of Free5GC Core on AWS.

## 1. Infrastructure Overview

This document details the AWS infrastructure for an EKS cluster deployment and multus networking capabilities.

### 1.1 High-Level Components

- VPC with multi-AZ design
- EKS Cluster with managed node groups
- Multus networking support
- AWS-managed add-ons
- Custom IAM roles and security configurations

## 2. Networking Architecture

### 2.1 VPC Configuration

- CIDR Block: 10.100.0.0/16
- Region: us-west-2
- Supports 2 Availability Zones
  - AZ1: us-west-2a
  - AZ2: us-west-2b
- DNS Support: Enabled
- DNS Hostnames: Enabled

### 2.2 Subnet Layout

| Subnet Type | AZ | CIDR Block | Purpose |
|-------------|------|------------|---------|
| Public Management | us-west-2a | 10.100.0.0/24 | External connectivity, NAT Gateway placement |
| Public Management | us-west-2b | 10.100.1.0/24 | External connectivity, NAT Gateway placement |
| Private Kubernetes | us-west-2a | 10.100.2.0/24 | Main Kubernetes cluster network |
| Private Kubernetes | us-west-2b | 10.100.3.0/24 | Main Kubernetes cluster network |
| Multus | us-west-2a | 10.100.4.0/24 | N2 Multus network, Secondary network interfaces for EKS Worker nodes part of EKS Managed Node group |
| Multus | us-west-2b | 10.100.8.0/24 | N2 Multus network, Secondary network interfaces for EKS Worker nodes part of EKS Managed Node group |
| Multus | us-west-2a | 10.100.5.0/24 | N3 Multus network, Secondary network interfaces for EKS Worker nodes part of EKS Managed Node group |
| Multus | us-west-2b | 10.100.9.0/24 | N3 Multus network, Secondary network interfaces for EKS Worker nodes part of EKS Managed Node group |
| Multus | us-west-2a | 10.100.6.0/24 | N4 Multus network, Secondary network interfaces for EKS Worker nodes part of EKS Managed Node group |
| Multus | us-west-2b | 10.100.10.0/24 | N4 Multus network, Secondary network interfaces for EKS Worker nodes part of EKS Managed Node group |
| Multus | us-west-2a | 10.100.7.0/24 | N6 Multus network, Secondary network interfaces for EKS Worker nodes part of EKS Managed Node group |
| Multus | us-west-2b | 10.100.11.0/24 | N6 Multus network, Secondary network interfaces for EKS Worker nodes part of EKS Managed Node group |

#### 2.2.1 cidr reservation

- In each of the subnet with type multus, carve out the second /27 network and configure it for subnet-cidr-reservation with type explicit. Example subnet cidr 10.100.4.0/24, carve out 10.0.4.32/27 and configure it for subnet-cidr-reservation with type explicit. Reminder that creating CIDR reservation does not have a tag argument.

### 2.3 Networking Components

#### 2.3.1. Internet Gateway (IGW)

- IGW Attached to VPC
- Enables internet access for public subnets

#### 2.3.2. NAT Gateways

- One per AZ for high availability
- Located in public subnets
- Provides internet access for private subnets

#### 2.3.3. Route Tables

- Public Subnets: Routes to Internet Gateway
- Private Subnets: Routes to NAT Gateway
- Multus Subnets: Routes to NAT Gateway

## 3. Security Configuration

### 3.1 IAM Roles

#### 3.1.1. EKS Cluster IAM Role

EKS Cluster role must be configured with the following IAM policies -

- AmazonEKSClusterPolicy
- AmazonEKSServicePolicy

#### 3.1.2. EKS Node Group IAM Role

EKS Node Group IAM role must be configured with the following IAM policies -

- AmazonEKSWorkerNodePolicy
- AmazonEC2ContainerRegistryReadOnly
- AmazonEKS_CNI_Policy
- AmazonSSMManagedInstanceCore
- AmazonS3ReadOnlyAccess
- CloudWatchAgentServerPolicy
- Custom IAM policy for EC2/networking operations with the following actions for all resources -

```sh
- ec2:UnassignIpv6Addresses
- ec2:AssignIpv6Addresses
- s3:Get*
- s3:Put*
- s3:List*
- ec2:AssignPrivateIpAddresses
- ec2:AssignIpv6Addresses
- ec2:DescribeInstances
- ec2:DescribeSubnets
- ec2:DescribeNetworkInterfaces
- ec2:ModifyNetworkInterfaceAttribute
- ec2:ModifyInstanceMetadataOptions
- ec2:UnassignIpv6Addresses
- ec2:UnassignPrivateIpAddresses
- ec2:DescribeVpcs
- ec2:CreateRoute
- ec2:DeleteRoute
- ec2:ReplaceRoute
- ec2:DescribeNetworkInterfacePermissions
- ec2:DescribeAddresses
- ec2:CreateLocalGatewayRoute
- ec2:ModifyLocalGatewayRoute
- ec2:DeleteLocalGatewayRoute
- ec2:SearchLocalGatewayRoutes
- ec2:AssociateAddress
- ec2:DisassociateAddress
- sts:AssumeRole
- ec2:CreateVolume
- ec2:DeleteVolume
- ec2:AttachVolume
- ec2:DetachVolume
- ec2:DescribeVolumes
- ec2:CreateTags
- ec2:DeleteTags
- ec2:ModifyInstanceAttribute
```

### 3.2 Security Groups

#### 3.2.1. EKS Control Plane Security Group

EKS Control plane Security group should allow following communication -

- Cluster API communication
- Node group communication to Control Plane
- Allow All traffic from VPC CIDR IPs

#### 3.2.2. EKS Node Group Security Group

EKS Node Group Security group should allow following communication -

- Inter-node communication
- EKS Control plane communication
- Application traffic
- Allow SSH traffic from all IPs
- Allow All ICMP Traffic from all IPs
- Allow All traffic from VPC CIDR IPs

#### 3.2.3. Multus Security group for Multus ENIs (passed to the user-data script)

- Allow All access

## 4. EC2 Launch Template with user-data for Multus configuration

### 4.1 EC2 Launch Template for AZ1 Multus subnets

 EC2 Launch template with the relevant parameters passed with the user-data script.
 AMI & image id definition is not needed in EC2 Launch template as the AMI type is defined in the EKS Managed nodegroup (Chapter 5.2)
 This script implements Multus for EKS node group worker nodes with Multus subnet IDs (Section 2.2.3) and Security groups (Section 3.2.4)
 Configure metadata_options with IMDSv2 enabled and HTTP put response hop limit set to 2.
 EC2 Launch Templates must have following configuration -

- Instance Type: m6i.4xlarge
- Volume Size: 20GB
- Capacity Type: ON_DEMAND
- UserData script for Multus interface configuration and GTP module installation

## 5. EKS Cluster Configuration

### 5.1 EKS Control Plane

- EKS Version: 1.33
- API Server Endpoint: Public and Private
- Authentication Mode: API_AND_CONFIG_MAP
- Logging: CloudWatch enabled

### 5.2 EKS Managed Node Groups

EKS NodeGroups are created using EC2 Launch Template (Section 4.1) using the following additional configurations -
Please use AL2023 AMI for Managed Node Group. Please note that AL2023 AMIs dont use EKS bootstraping anymore and relies on nodeadm.

#### EKS NodeGroup

- EKS NodeGroup Auto-scaling Configuration:
  - Minimum: 2
  - Desired: 2
  - Maximum: 3
- Subnet selection: Private Kubernetes Subnet AZ1
- AMI Type: AL2023_x86_64_STANDARD

### 5.3 EKS Add-ons

The following EKS Cluster Add-ons must be installed: use only vpc-cni version v1.20.4-eksbuild.1

- vpc-cni
- kube-proxy

## 6. Backup and Disaster Recovery

### 6.1 EKS Backup

- EBS Snapshots for persistent volumes
- Multi-AZ deployment for high availability
- Node group distribution across AZs

## 7. Networking Flow

### 7.1 External Access Flow

- Internet → Internet Gateway → Public Subnets
- Public Subnets → NAT Gateway → Private Subnets
- Private Subnets → Container Workloads

### 7.2 Pod Networking

- Primary Network: vpc-cni in private subnets
- Secondary Networks: Multus CNI in dedicated subnets
- Cross-AZ Communication: VPC routing
