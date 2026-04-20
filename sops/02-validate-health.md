# Validate Application Health

## Prerequisites
- Application deployed in `demo-app` namespace

## Steps

### Step 1: Check Pod Status
```bash
kubectl get pods -n demo-app -o wide
```
**Expected**: All pods in Running state

### Step 2: Check Service Endpoints
```bash
kubectl get endpoints -n demo-app
```
**Expected**: Endpoints have IP addresses

### Step 3: Test Connectivity
```bash
kubectl run curl-test --rm -i --restart=Never --image=curlimages/curl -- curl -s http://nginx.demo-app.svc.cluster.local
```
**Expected**: nginx welcome page HTML
