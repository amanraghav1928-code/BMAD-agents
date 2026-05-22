# ADR-002: Embedding Model Selection for AIKA

**Status:** Accepted  
**Date:** 2025-03-14  
**Deciders:** AI/ML Guild, Platform Architecture Team  
**Supersedes:** N/A  
**Related:** ADR-001 (vector DB choice)

---

## Context

AIKA indexes API documentation (OpenAPI specs, AsyncAPI specs, ADRs, runbooks, design docs) and performs semantic search to answer developer questions. The embedding model converts both documents and queries into dense vectors.

Requirements:
- No API key or external call at inference time (dev + CI environments have no internet guarantees)
- Vector dimension ≤1024 (ChromaDB HNSW memory budget)
- Optimised for technical prose / short structured text (YAML/JSON field descriptions, markdown)
- Inference latency ≤50ms per chunk on CPU (MacBook M-series or CI runner)
- Permissive open-source license

---

## Considered Options

### Option A: `sentence-transformers/all-MiniLM-L6-v2`
- Dimensions: 384
- Model size: 22MB (6-layer MiniLM distillation)
- Licence: Apache 2.0
- Optimised for: semantic similarity, paraphrase detection
- CPU inference: ~5ms/chunk on M2 MacBook
- MTEB score (avg): 56.2

### Option B: `sentence-transformers/all-mpnet-base-v2`
- Dimensions: 768
- Model size: 420MB
- CPU inference: ~25ms/chunk
- MTEB score (avg): 57.8
- Note: 19x larger than MiniLM for ~3% quality gain

### Option C: `BAAI/bge-small-en-v1.5`
- Dimensions: 384
- Model size: 33MB
- CPU inference: ~8ms/chunk
- MTEB score (avg): 58.4
- Optimised for retrieval; strong on technical docs
- Licence: MIT

### Option D: `text-embedding-3-small` (OpenAI)
- Dimensions: 1536
- Requires OpenAI API key and internet
- $0.02/1M tokens — acceptable cost but external dependency
- Rules out offline dev and air-gapped CI

### Option E: `nomic-embed-text-v1`
- Dimensions: 768
- Requires trust_remote_code=True (security concern flagged by Security Review Board)
- Deferred pending security assessment

---

## Decision Outcome

**Chosen: Option A — `sentence-transformers/all-MiniLM-L6-v2`**

For the 6-week intern POC, `all-MiniLM-L6-v2` provides the best balance of speed, size, and quality:

- Ships as a single 22MB download (cached by HuggingFace hub after first use)
- Runs entirely locally — no API key, no network dependency
- 384-dim vectors keep ChromaDB memory footprint small (~20MB for 50K docs)
- Inference is fast enough to embed an entire fresh corpus in under 30 seconds

### Why not bge-small?
`BAAI/bge-small-en-v1.5` scored marginally better on MTEB but:
1. It requires prepending `"Represent this sentence: "` to queries but NOT to documents — asymmetric usage is error-prone
2. The MiniLM model is more widely documented, lowering onboarding friction for interns

---

## Implementation Notes

```python
from sentence_transformers import SentenceTransformer

# Load once at startup (cached ~/.cache/huggingface/hub/)
_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def embed(texts: list[str]) -> list[list[float]]:
    """Batch embed. Returns list of 384-dim float vectors."""
    return _model.encode(texts, batch_size=32, show_progress_bar=False).tolist()
```

**Chunking strategy paired with this model:**
- Chunk size: 500 characters
- Overlap: 50 characters
- Rationale: MiniLM has a 256-token context window; 500 chars ≈ 100-120 tokens — well within limits

---

## Consequences

### Positive
- Zero-cost, offline-capable embedding
- Fast iteration during development (no API quota management)
- Reproducible: model weights are pinned via HuggingFace hub hash

### Negative / Risks
- 384 dimensions may be insufficient for very long, technical YAML specs — mitigated by chunking
- Model is from 2021; newer alternatives exist but were out of scope for this ADR review window
- Not fine-tuned on API documentation domain — may miss domain-specific synonyms

### Migration Trigger
Revisit this ADR if:
- Mean Reciprocal Rank @5 (MRR@5) on the golden Q&A set falls below 0.75 in evaluation
- A domain-fine-tuned model becomes available under Apache/MIT licence

---

## Evaluation Results (Golden Q&A Set, 30 pairs)

| Metric | all-MiniLM-L6-v2 | all-mpnet-base-v2 | bge-small-en |
|--------|-----------------|-------------------|--------------|
| MRR@5  | 0.81            | 0.84              | 0.83         |
| Hit@1  | 0.70            | 0.73              | 0.73         |
| Hit@3  | 0.87            | 0.89              | 0.88         |
| Avg latency (CPU) | 5ms | 28ms | 9ms |

MiniLM's ~3% lower MRR@5 is acceptable given the 5× speed advantage in our latency budget.

---

## References
- SBERT benchmarks: https://www.sbert.net/docs/pretrained_models.html
- MTEB leaderboard: https://huggingface.co/spaces/mteb/leaderboard
- ADR-001: Vector DB Choice
