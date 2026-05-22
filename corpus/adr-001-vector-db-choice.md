# ADR-001: Choice of Vector Database for AIKA

**Status:** Accepted  
**Date:** 2025-03-12  
**Deciders:** Platform Architecture Team, AI/ML Guild  
**Consulted:** Infrastructure Team, Security Review Board  
**Informed:** All Engineering Teams

---

## Context and Problem Statement

The AI-Powered API Knowledge Assistant (AIKA) requires a vector database to store and retrieve dense embeddings for semantic search over API documentation corpus (~500 documents, projected to grow to ~5,000 over 12 months).

We evaluated storage backends capable of:
1. Storing 768-dimensional embedding vectors
2. Approximate Nearest Neighbour (ANN) search with sub-100ms P99 latency at our scale
3. Metadata filtering (by API domain, version, doc type)
4. Local development without external services
5. Production-grade persistence and reliability

---

## Decision Drivers

- **Developer Experience**: Must run locally with zero external dependencies for onboarding
- **Operational Simplicity**: No managed service required for MVP; must be self-hostable
- **Performance**: ≤100ms P99 retrieval latency for top-5 chunks with a 50K vector corpus
- **Cost**: Open-source or low-cost; no per-query billing at proof-of-concept stage
- **Python-native**: Must integrate cleanly with LangChain/LlamaIndex if needed later
- **Metadata Filtering**: Must support filtering by `doc_type`, `api_name`, `version`

---

## Considered Options

### Option A: ChromaDB (local persistent)
- Embedded Python library, zero-config local mode
- SQLite-backed persistence, HNSW index
- Full metadata filtering via `where` clause
- Apache 2.0 license

### Option B: Pinecone (managed cloud)
- Fully managed, serverless
- Excellent performance and scalability
- Per-query pricing; requires internet access from dev machines
- Data leaves org boundary — needs DLP review

### Option C: Weaviate (self-hosted Docker)
- Feature-rich: hybrid search (BM25 + vector), GraphQL API
- Requires Docker daemon in all dev environments
- Higher operational overhead for a 6-week POC

### Option D: pgvector (PostgreSQL extension)
- Familiar SQL interface; reuses existing Postgres infra
- `ivfflat` index at this scale has higher memory overhead
- Does not support local-only dev without Postgres running

### Option E: FAISS (Meta, in-process)
- Fastest raw ANN performance
- No built-in persistence (must serialise manually)
- No metadata filtering — would require a separate metadata store
- Not suitable as a standalone document store

---

## Decision Outcome

**Chosen: Option A — ChromaDB (local persistent)**

ChromaDB best satisfies our current constraints:

| Criterion | ChromaDB | Pinecone | Weaviate | pgvector | FAISS |
|-----------|----------|----------|----------|----------|-------|
| Local dev (no infra) | ✅ | ❌ | ⚠️ (Docker) | ⚠️ | ✅ |
| Persistence | ✅ | ✅ | ✅ | ✅ | ❌ |
| Metadata filtering | ✅ | ✅ | ✅ | ✅ | ❌ |
| Zero external cost | ✅ | ❌ | ✅ | ✅ | ✅ |
| Data sovereignty | ✅ | ❌ | ✅ | ✅ | ✅ |
| Python ease-of-use | ✅ | ✅ | ⚠️ | ⚠️ | ✅ |

### Rationale

For a 6-week intern project targeting a corpus under 100K vectors, ChromaDB's embedded mode provides exactly what is needed: a single `chromadb.PersistentClient(path)` call, full metadata filtering, and no infrastructure dependencies. The HNSW index comfortably handles our target scale.

If the project graduates to production and corpus size exceeds 500K vectors, we will revisit this ADR (see Consequences below).

---

## Consequences

### Positive
- Any developer can `pip install chromadb` and run the full stack locally
- No network calls to external services; works in air-gapped CI environments
- Metadata filtering via `where={"doc_type": "openapi"}` works out of the box
- Easy migration path: ChromaDB's API is compatible with the Chroma cloud offering

### Negative / Risks
- **Scale ceiling**: ChromaDB embedded mode is not designed for >1M vectors in production. If corpus grows substantially, we must migrate to Weaviate or Pinecone.
- **No horizontal scaling**: Single process; concurrent writes require application-level locking.
- **HNSW build time**: Index is rebuilt on large batch ingests (mitigated by incremental ingestion).

### Migration Trigger
Open a new ADR to replace ChromaDB when any of the following occur:
- Corpus exceeds 500K vectors
- P99 retrieval latency exceeds 200ms
- Multi-region deployment is required

---

## References
- ChromaDB docs: https://docs.trychroma.com
- HNSW paper: Malkov & Yashunin (2018) "Efficient and Robust Approximate Nearest Neighbor Search Using Hierarchical Navigable Small World Graphs"
- Internal benchmark: `benchmarks/vector-db-comparison-2025-03.ipynb`
