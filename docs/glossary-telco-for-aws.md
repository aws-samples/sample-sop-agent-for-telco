# Telco Terminology for AWS Engineers

Quick reference for AWS-native engineers encountering 5G/telco terms in this workshop.

## Network Functions

| Term | What it is | AWS analogy |
|------|-----------|-------------|
| AMF (Access and Mobility Mgmt Function) | Handles UE registration, mobility, connection management | Like an Application Load Balancer for mobile devices |
| SMF (Session Mgmt Function) | Establishes/maintains data sessions for UEs | Session manager that allocates IPs and routes traffic |
| UPF (User Plane Function) | Forwards user traffic between RAN and the internet | NAT gateway + packet inspector for mobile data |
| AUSF (Auth Server Function) | Handles UE authentication | Cognito for SIM cards |
| UDM (Unified Data Mgmt) | Stores subscriber data | DynamoDB for subscriber records |
| NRF (Network Repository Function) | Service discovery for other NFs | Service Connect / Cloud Map |
| SCP (Service Communication Proxy) | Service mesh proxy between NFs | App Mesh / Envoy sidecar |
| PCF (Policy Control Function) | Policy decisions (QoS, charging) | IAM policies for mobile sessions |
| NSSF (Network Slice Selection Function) | Selects which network slice a UE uses | Like choosing a VPC based on traffic type |

## Radio Access Network (RAN)

| Term | What it is | AWS analogy |
|------|-----------|-------------|
| gNB (gNodeB) | The 5G base station | An edge location / Local Zone |
| DU (Distributed Unit) | Lower-layer radio processing (real-time) | Real-time compute at the edge |
| CU (Central Unit) | Higher-layer radio processing | Regional compute for the radio |
| UE (User Equipment) | The mobile device (phone, IoT sensor) | The client making API calls |
| RU (Radio Unit) | The antenna + RF hardware | The physical network interface |

## Interfaces and Protocols

| Term | What it is |
|------|-----------|
| N1 | UE ↔ AMF (NAS signaling) |
| N2 | gNB ↔ AMF (control plane) |
| N3 | gNB ↔ UPF (user plane / GTP tunnel) |
| N4 | SMF ↔ UPF (PFCP — session rules) |
| N6 | UPF ↔ internet (data network) |
| SBI | Service-Based Interface — HTTP/2 between core NFs |
| PFCP | Packet Forwarding Control Protocol (SMF tells UPF what to do) |
| GTP | GPRS Tunneling Protocol (carries user data over N3) |
| NAS | Non-Access Stratum (signaling between UE and core) |

## Procedures

| Term | What it is |
|------|-----------|
| Registration | UE announces itself to the network (like instance boot → register with ELB) |
| PDU Session | A data path for the UE (like creating a VPN tunnel) |
| Handover | UE moves between cells without dropping connection |
| Paging | Network wakes up an idle UE (like an SQS message to a sleeping consumer) |
| SUPI/SUCI | Permanent/concealed subscriber ID (like IAM ARN vs STS session token) |

## Metrics you'll see in this workshop

| Metric | Meaning | Alarm condition |
|--------|---------|-----------------|
| `amf_gnb` | Number of gNBs connected to AMF | < 1 = radio disconnected |
| `core_nf_health_pct` | Percentage of healthy NF pods | < 95 = degraded |
| `smf_fivegs_smffunction_sm_n4sessionestabfail` | Failed PDU session setups | > 0 = UPF unreachable |
| `du_du_high_mac_dl_0_cpu_usage_percent` | DU CPU usage | > 80 = overloaded |
