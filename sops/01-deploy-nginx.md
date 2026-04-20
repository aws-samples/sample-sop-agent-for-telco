# Deploy Nginx Application

## Prerequisites
- Kubernetes cluster accessible via kubectl
- Namespace `demo-app` exists

## Steps

### Step 1: Create Deployment
```bash
kubectl apply -f - <<YAML
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx
  namespace: demo-app
spec:
  replicas: 2
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:1.25
        ports:
        - containerPort: 80
YAML
```
**Expected**: deployment.apps/nginx created

### Step 2: Create Service
```bash
kubectl apply -f - <<YAML
apiVersion: v1
kind: Service
metadata:
  name: nginx
  namespace: demo-app
spec:
  selector:
    app: nginx
  ports:
  - port: 80
    targetPort: 80
  type: ClusterIP
YAML
```
**Expected**: service/nginx created

### Step 3: Verify Deployment
```bash
kubectl get pods -n demo-app -l app=nginx
```
**Expected**: 2/2 Running
