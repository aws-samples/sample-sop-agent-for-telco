# Teardown Application

## Prerequisites
- Application deployed in `demo-app` namespace

## Steps

### Step 1: Delete Deployment
```bash
kubectl delete deployment nginx -n demo-app
```
**Expected**: deployment.apps "nginx" deleted

### Step 2: Delete Service
```bash
kubectl delete service nginx -n demo-app
```
**Expected**: service "nginx" deleted

### Step 3: Verify Cleanup
```bash
kubectl get all -n demo-app
```
**Expected**: No resources found
