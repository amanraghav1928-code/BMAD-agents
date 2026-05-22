# Solution Design: ACME E-Commerce Platform — Microservices Architecture

**Document Type:** Solution Design  
**Version:** 2.1  
**Date:** 2025-02-20  
**Author:** Platform Architecture Team  
**Status:** Approved

---

## Executive Summary

This document describes the target architecture for the ACME e-commerce platform following the migration from a monolithic Rails application to a microservices architecture. The platform handles 2M+ active users, 50K SKUs, and processes ~10K orders/day.

---

## System Overview

The platform is decomposed into 8 domain services plus 3 platform services:

**Domain Services:**
1. Product Catalogue Service — product/category/inventory management
2. Order Management Service — cart, checkout, order lifecycle
3. Customer Service — user accounts, auth, addresses
4. Notification Service — multi-channel notifications (email/SMS/push/in-app)
5. Payment Service — payment processing (Stripe integration)
6. Search Service — full-text and faceted product search (Elasticsearch)
7. Recommendation Service — personalised product recommendations (ML model)
8. Analytics Service — event ingestion, real-time dashboards

**Platform Services:**
1. API Gateway — Kong 3.4 (entry point, JWT auth, rate limiting, routing)
2. Event Bus — Apache Kafka 3.6 (domain event streaming)
3. Observability Stack — OpenTelemetry + Datadog + Langfuse (AI components)

---

## Architecture Diagram (Logical)

```
                         ┌─────────────────┐
  Browser / Mobile  ────►│   API Gateway   │ (Kong on EKS)
                         │  - JWT Auth     │
                         │  - Rate Limit   │
                         │  - Routing      │
                         └────────┬────────┘
                                  │
           ┌──────────────────────┼──────────────────────┐
           │                      │                      │
    ┌──────▼──────┐       ┌───────▼──────┐     ┌────────▼───────┐
    │  Catalogue  │       │    Orders    │     │   Customer     │
    │  Service    │       │   Service    │     │   Service      │
    │ (FastAPI)   │       │  (FastAPI)   │     │  (FastAPI)     │
    └──────┬──────┘       └──────┬───────┘     └────────┬───────┘
           │                     │                      │
           └─────────────────────┴──────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │      Kafka Event Bus     │
                    │  order.*, product.*,     │
                    │  user.*, inventory.*     │
                    └────────────┬────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
    ┌─────────▼──────┐  ┌────────▼───────┐  ┌──────▼─────────┐
    │  Notification  │  │    Payment     │  │   Analytics    │
    │   Service      │  │   Service      │  │   Service      │
    └────────────────┘  └────────────────┘  └────────────────┘
```

---

## Service Specifications

### Product Catalogue Service

- **Language:** Python 3.12 / FastAPI
- **Database:** PostgreSQL 16 (primary) + Redis 7 (caching, TTL=5min)
- **API:** REST (OpenAPI 3.0 spec: `product-catalogue-api-v2.yaml`)
- **Scale:** 3-10 replicas, HPA at 60% CPU
- **Key tables:** `products`, `categories`, `inventory`, `product_images`
- **Events published:** `product.created`, `product.updated`, `product.deleted`, `inventory.adjusted`, `inventory.low_stock`

### Order Management Service

- **Language:** Python 3.12 / FastAPI
- **Database:** PostgreSQL 16 (dedicated schema)
- **API:** REST (OpenAPI 3.0 spec: `order-management-api-v1.yaml`)
- **Scale:** 5-15 replicas (higher during sales events)
- **Key tables:** `carts`, `cart_items`, `orders`, `order_items`, `returns`
- **Events published:** `order.placed`, `order.status_changed`, `order.shipped`, `order.delivered`, `order.cancelled`
- **Events consumed:** `payment.succeeded`, `payment.failed`, `inventory.insufficient`

### Notification Service

- **Language:** Node.js 20 / Express
- **Database:** PostgreSQL 16 (notification logs) + Redis (deduplication)
- **API:** AsyncAPI 2.6 spec (`notification-api-asyncapi.yaml`) + REST management API
- **Channels:** Email (SendGrid), SMS (Twilio), Push (FCM/APNs), In-App (WebSocket)
- **Events consumed:** All `order.*` events, `user.registered`, `user.password_reset`, `inventory.low_stock`

### AIKA — AI Knowledge Assistant

- **Language:** Python 3.12 / FastAPI
- **Vector Store:** ChromaDB (persistent, local path `./data/chromadb`)
- **Embedding Model:** `sentence-transformers/all-MiniLM-L6-v2` (384-dim, local)
- **LLM:** Groq `llama-3.3-70b-versatile` via GROQ_API_KEY
- **Observability:** Langfuse (every query traced: embed → retrieve → llm_call; faithfulness + answer_relevance scores)
- **API endpoints:**
  - `POST /ingest` — ingest documents into ChromaDB
  - `POST /query` — semantic search + LLM answer
  - `GET /health` — service health
  - `GET /metrics` — query stats (total queries, avg latency, avg faithfulness)
  - `POST /scores` — user feedback (thumbs up/down) → Langfuse score
  - `GET /documents` — list ingested documents
  - `DELETE /documents/{id}` — remove document from corpus
- **Auth:** Bearer token (`AIKA_API_KEY` env var)
- **Docker:** `docker-compose up --build` (backend + frontend + chroma volume)

---

## Data Architecture

### PostgreSQL Clusters

| Cluster | Services | Replicas | Backup |
|---------|----------|----------|--------|
| `pg-catalogue` | Product Catalogue | 1 primary, 2 read replicas | Daily snapshot + WAL streaming |
| `pg-orders` | Order Management, Payment | 1 primary, 2 read replicas | Daily snapshot + WAL streaming |
| `pg-platform` | Customer, Notification | 1 primary, 1 read replica | Daily snapshot |

### Kafka Topics

| Topic | Partitions | Retention | Producers | Consumers |
|-------|------------|-----------|-----------|-----------|
| `order.placed` | 12 | 7 days | Orders | Notifications, Analytics, Payment |
| `order.status_changed` | 12 | 7 days | Orders | Notifications, Analytics |
| `order.shipped` | 6 | 7 days | Orders | Notifications |
| `inventory.low_stock` | 6 | 3 days | Catalogue | Notifications, Analytics |
| `product.updated` | 6 | 3 days | Catalogue | Search, Recommendations |

---

## Security Architecture

- **Authentication:** Auth0 (JWT RS256 tokens, 1h TTL)
- **Authorisation:** RBAC per service (consumer tiers: guest, customer, admin, ops)
- **API Gateway:** JWT validation at edge; services trust forwarded `X-Consumer-ID` header
- **Secrets:** AWS Secrets Manager; rotated every 90 days; injected at pod startup via External Secrets Operator
- **TLS:** All internal service-to-service traffic on mTLS (Istio service mesh)
- **Data at rest:** PostgreSQL TDE enabled; S3 SSE-S3 for media/assets
- **PCI scope:** Payment Service is the only PCI-DSS scoped service; isolated namespace `payment-ns`

---

## Observability

- **Metrics:** Prometheus + Grafana; custom business metrics (orders/min, cart_abandonment_rate)
- **Tracing:** OpenTelemetry SDK → Datadog APM; all services instrumented
- **Logging:** Structured JSON logs → Fluent Bit → Datadog Logs
- **AI Observability:** Langfuse for all LLM/RAG calls (AIKA service); tracks: latency, tokens, cost, faithfulness, answer_relevance
- **Alerting:** PagerDuty routing; SEV-1 = 5min response; SEV-2 = 30min

---

## Deployment

- **Orchestration:** Kubernetes (EKS 1.29) across 3 AZs (us-east-1)
- **CI/CD:** GitHub Actions → ECR image build → ArgoCD GitOps deployment
- **Environments:** dev → staging → production (automated gates: unit tests, integration tests, smoke tests)
- **Helm charts:** `charts/` directory; one chart per service
- **Infrastructure:** Terraform (IaC); state in S3 + DynamoDB locking

---

## Non-Functional Requirements

| Requirement | Target | Measurement |
|-------------|--------|-------------|
| API Gateway P99 latency | < 50ms | Datadog SLO |
| Catalogue read P99 | < 100ms | Datadog SLO |
| Order placement P99 | < 500ms | Datadog SLO |
| AIKA query P99 | < 2s | Langfuse dashboard |
| Availability | 99.9% | Monthly |
| RTO | 30 min | DR runbook |
| RPO | 1 hour | Backup verification |

---

## Appendix: Environment Variables Reference

| Service | Variable | Description |
|---------|----------|-------------|
| All | `ENVIRONMENT` | dev / staging / production |
| All | `LOG_LEVEL` | DEBUG / INFO / WARNING / ERROR |
| API Gateway | `KONG_ADMIN_TOKEN` | Admin API token |
| AIKA | `GROQ_API_KEY` | Groq LLM API key |
| AIKA | `AIKA_API_KEY` | Bearer token for AIKA API auth |
| AIKA | `LANGFUSE_PUBLIC_KEY` | Langfuse public key |
| AIKA | `LANGFUSE_SECRET_KEY` | Langfuse secret key |
| AIKA | `LANGFUSE_HOST` | Langfuse host (default: cloud.langfuse.com) |
| AIKA | `CHROMA_PERSIST_DIR` | ChromaDB persistence path (default: ./data/chromadb) |
| Payment | `STRIPE_SECRET_KEY` | Stripe API secret key |
| Notification | `SENDGRID_API_KEY` | SendGrid email API key |
| Notification | `TWILIO_AUTH_TOKEN` | Twilio SMS auth token |
