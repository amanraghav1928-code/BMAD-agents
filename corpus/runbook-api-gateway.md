# Runbook: API Gateway Operations

**Service:** api-gateway  
**Team:** Platform Engineering  
**Last Updated:** 2025-04-01  
**On-Call Rotation:** platform-oncall@acmecorp.com  
**Escalation:** #platform-engineering (Slack) → PagerDuty → VP Engineering

---

## Overview

The ACME API Gateway is the single entry point for all external traffic. It sits in front of the Product Catalogue API, Order Management API, Notification API, and Auth Service. It handles:

- TLS termination (wildcard cert via ACM)
- JWT validation + rate limiting
- Request routing (path-based)
- Canary traffic splitting
- Distributed tracing (OpenTelemetry → Datadog)
- Circuit breaking per upstream

**Stack:** Kong Gateway 3.4 on EKS; Terraform-managed; Helm chart `acme/api-gateway`

---

## Health Checks

### Quick Health

```bash
# Public health probe (no auth)
curl https://api.acmecorp.com/healthz

# Expected response
{"status":"healthy","version":"3.4.2","uptime_seconds":172800}

# Per-upstream health (requires ops token)
curl -H "Authorization: Bearer $OPS_TOKEN" \
     https://api.acmecorp.com/admin/upstreams
```

### Dashboard Links
- Datadog: https://app.datadoghq.com/dashboard/api-gateway (internal)
- Kong Manager: https://kong-manager.internal.acmecorp.com
- Grafana: https://grafana.internal.acmecorp.com/d/api-gw-overview

---

## Common Incidents

### INC-01: High Error Rate (5xx spike)

**Symptoms:** Error rate > 5% on `api.acmecorp.com`; Datadog alert `API_GW_5XX_HIGH` fires

**Diagnosis steps:**
1. Check which upstream is returning 5xx:
   ```bash
   kubectl logs -n api-gateway deploy/kong-proxy --tail=100 | grep '"status":5'
   ```
2. Identify top failing routes:
   ```bash
   curl -H "Authorization: Bearer $OPS_TOKEN" \
     "https://api.acmecorp.com/admin/routes?status=5xx"
   ```
3. Check upstream health:
   ```bash
   kubectl get pods -n catalogue && kubectl get pods -n orders
   ```

**Resolution options:**

| Cause | Action |
|-------|--------|
| Upstream pod OOMKilled | `kubectl rollout restart deploy/<upstream>` |
| DB connection exhausted | Check connection pool; restart upstream deployment |
| Bad deploy to upstream | `kubectl rollout undo deploy/<upstream>` |
| Kong config error | `git revert` last Helm release; `helm rollback api-gateway` |

---

### INC-02: Rate Limit False Positives

**Symptoms:** Legitimate users receiving `429 Too Many Requests`; `rate_limit_incidents` alert

**Diagnosis:**
```bash
# Check rate limit state in Redis
redis-cli -h redis.internal.acmecorp.com GET "rl:consumer:<consumer_id>"

# List rate limit plugins per route
curl -H "Authorization: Bearer $OPS_TOKEN" \
  https://api.acmecorp.com/admin/plugins?name=rate-limiting
```

**Resolution:**
1. Temporary relief — increase limit for affected consumer:
   ```bash
   curl -X PATCH \
     -H "Authorization: Bearer $OPS_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"config":{"minute":1000}}' \
     https://api.acmecorp.com/admin/plugins/<plugin_id>
   ```
2. Permanent fix — update `values/rate-limits.yaml` and re-deploy Helm chart
3. File ticket in Jira: `PLATFORM` project, label `rate-limiting`

---

### INC-03: SSL Certificate Expiry Warning

**Symptoms:** Datadog alert `CERT_EXPIRY_14D`; browser shows certificate warning

**Check:**
```bash
openssl s_client -connect api.acmecorp.com:443 -servername api.acmecorp.com \
  </dev/null 2>/dev/null | openssl x509 -noout -dates
```

**Resolution:**
- Certificates are auto-renewed via AWS ACM — check ACM console
- If renewal failed: `aws acm renew-certificate --certificate-arn <arn>`
- Re-attach cert to ALB if ARN changed:
  ```bash
  terraform apply -target=aws_lb_listener.https
  ```

---

### INC-04: Canary Deployment Rollback

**Symptoms:** Canary version showing elevated error rate; needs immediate rollback

**Rollback procedure:**
1. Update traffic weight to 0% canary in `values/canary.yaml`:
   ```yaml
   canary:
     weight: 0   # was: 10
     stable_weight: 100
   ```
2. Apply:
   ```bash
   helm upgrade api-gateway acme/api-gateway \
     -f values/production.yaml \
     -f values/canary.yaml \
     --namespace api-gateway
   ```
3. Verify: `curl https://api.acmecorp.com/healthz | jq .version`
4. Create post-mortem ticket in Jira

---

### INC-05: JWT Validation Failures

**Symptoms:** `401 Unauthorized` flood for all authenticated endpoints; no code change

**Diagnosis:**
```bash
# Check JWKS endpoint is reachable
curl https://auth.acmecorp.com/.well-known/jwks.json

# Verify Kong JWKS cache
curl -H "Authorization: Bearer $OPS_TOKEN" \
  https://api.acmecorp.com/admin/plugins?name=jwt
```

**Root causes:**
- Auth service down → restore auth service first
- JWKS rotation triggered but Kong cache not refreshed:
  ```bash
  # Force JWKS cache refresh
  curl -X POST \
    -H "Authorization: Bearer $OPS_TOKEN" \
    https://api.acmecorp.com/admin/jwks/refresh
  ```
- Clock skew > 5 minutes between nodes:
  ```bash
  kubectl exec -n api-gateway deploy/kong-proxy -- date
  # Should match: date -u
  # Fix: drain node, let NTP resync
  ```

---

## Deployment Procedure

### Standard Deploy

```bash
# 1. Lint Helm chart
helm lint charts/api-gateway -f values/production.yaml

# 2. Diff before apply
helm diff upgrade api-gateway acme/api-gateway \
  -f values/production.yaml --namespace api-gateway

# 3. Deploy
helm upgrade api-gateway acme/api-gateway \
  -f values/production.yaml \
  --namespace api-gateway \
  --atomic \
  --timeout 5m

# 4. Smoke test
./scripts/smoke-test-api-gateway.sh
```

### Canary Deploy (10% traffic)

```bash
helm upgrade api-gateway acme/api-gateway \
  -f values/production.yaml \
  -f values/canary.yaml \
  --set canary.image.tag=<new_tag> \
  --set canary.weight=10 \
  --namespace api-gateway
```

Monitor for 30 minutes. If error rate stable, promote to 100%:
```bash
helm upgrade api-gateway acme/api-gateway \
  -f values/production.yaml \
  --set image.tag=<new_tag> \
  --namespace api-gateway
```

---

## Scaling

```bash
# Manual scale-out (emergency)
kubectl scale deploy/kong-proxy --replicas=10 -n api-gateway

# HPA is configured — normal autoscaling is automatic
kubectl describe hpa kong-proxy-hpa -n api-gateway

# Check current resource consumption
kubectl top pods -n api-gateway
```

**HPA thresholds:** min=3, max=20, CPU target=60%, RPS target=5000/pod

---

## Useful Kubectl Commands

```bash
# Tail live logs
kubectl logs -n api-gateway -l app=kong -f --max-log-requests 5

# Describe service for events
kubectl describe svc kong-proxy -n api-gateway

# Get current Kong configuration
kubectl exec -n api-gateway deploy/kong-proxy -- kong config show

# Reload Kong config without restart
kubectl exec -n api-gateway deploy/kong-proxy -- kong reload
```

---

## Rate Limits Reference

| Consumer Tier | Requests/Minute | Requests/Day | Burst |
|---------------|-----------------|--------------|-------|
| Free           | 60              | 1,000        | 100   |
| Pro            | 600             | 50,000       | 1,000 |
| Enterprise     | 6,000           | Unlimited    | 10,000|
| Internal       | Unlimited       | Unlimited    | Unlimited |

---

## Contacts

| Role | Name | Contact |
|------|------|---------|
| Service Owner | Platform Eng Team | platform@acmecorp.com |
| On-Call Primary | Rotation | PagerDuty: `api-gateway` |
| Kong Vendor Support | Kong Inc. | support.konghq.com (Enterprise plan) |
| AWS TAM | — | Via AWS Support Console |
