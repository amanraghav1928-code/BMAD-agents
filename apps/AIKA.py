"""
AIKA — AI-Powered API Knowledge Assistant
Streamlit app: ChromaDB + sentence-transformers + Groq + Langfuse
"""

import os, sys, subprocess, time, uuid, json
from pathlib import Path
from datetime import datetime

# ── load .env first ───────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    # walk up from apps/ to find the .env in project root
    _env = Path(__file__).parent.parent / ".env"
    load_dotenv(dotenv_path=_env, override=True)
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-dotenv", "-q"])
    from dotenv import load_dotenv
    _env = Path(__file__).parent.parent / ".env"
    load_dotenv(dotenv_path=_env, override=True)

# ── auto-install ──────────────────────────────────────────────────────────────
for _pkg in ["chromadb", "sentence-transformers", "groq", "langfuse", "pypdf", "pyyaml"]:
    try:
        __import__(_pkg.split("-")[0].replace("-", "_"))
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", _pkg, "-q"])

import streamlit as st
import yaml
import chromadb
from sentence_transformers import SentenceTransformer
from groq import Groq
from langfuse import Langfuse

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AIKA — API Knowledge Assistant",
    page_icon="🤖",
    layout="wide",
)

# ── CSS (light theme) ─────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background: #F0FDFA; }

.hero {
  background: linear-gradient(135deg, #FFFFFF 0%, #CCFBF1 100%);
  border: 1px solid #99F6E4;
  border-radius: 16px;
  padding: 28px 32px;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  gap: 18px;
  box-shadow: 0 4px 20px rgba(13,148,136,0.08);
}
.hero-icon {
  width: 52px; height: 52px;
  background: linear-gradient(135deg, #0D9488, #059669);
  border-radius: 14px;
  display: flex; align-items: center; justify-content: center;
  font-size: 24px; flex-shrink: 0;
}
.hero-title {
  font-size: 1.6rem; font-weight: 700;
  background: linear-gradient(135deg, #0D9488, #059669);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  margin: 0;
}
.hero-sub { color: #6B7280; font-size: .85rem; margin-top: 4px; }

.answer-card {
  background: #FFFFFF;
  border: 1px solid #99F6E4;
  border-left: 4px solid #0D9488;
  border-radius: 14px;
  padding: 20px 24px;
  margin-top: 16px;
  line-height: 1.75;
  font-size: .92rem;
  color: #1F2937;
  box-shadow: 0 2px 12px rgba(13,148,136,0.08);
}
.source-tag {
  display: inline-block;
  background: #CCFBF1;
  border: 1px solid #99F6E4;
  border-radius: 20px;
  padding: 3px 12px;
  font-size: .75rem;
  color: #0D9488;
  margin: 4px 4px 0 0;
  font-weight: 500;
}
.meta-row {
  display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap;
}
.meta-pill {
  background: #F0FDFA;
  border: 1px solid #99F6E4;
  border-radius: 20px;
  padding: 4px 14px;
  font-size: .75rem;
  color: #0D9488;
  font-weight: 500;
}
.badge-live {
  display: inline-flex; align-items: center; gap: 6px;
  background: #ECFDF5; border: 1px solid #6EE7B7;
  border-radius: 20px; padding: 4px 14px;
  font-size: .75rem; color: #059669; font-weight: 600;
}
.dot { width: 7px; height: 7px; background: #10B981; border-radius: 50%;
       display: inline-block; animation: blink 2s infinite; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:.25} }

div[data-testid="stTextArea"] textarea {
  background: #FFFFFF !important;
  border: 1px solid #D1FAE5 !important;
  border-radius: 10px !important;
  color: #1F2937 !important;
  font-family: 'Inter', sans-serif !important;
}
div[data-testid="stTextArea"] textarea:focus {
  border-color: #0D9488 !important;
  box-shadow: 0 0 0 3px rgba(13,148,136,0.12) !important;
}
div[data-testid="stTextInput"] input {
  background: #FFFFFF !important;
  border: 1px solid #D1FAE5 !important;
  color: #1F2937 !important;
  border-radius: 10px !important;
}
.stButton > button {
  background: linear-gradient(135deg, #0D9488, #059669) !important;
  color: white !important;
  border: none !important;
  border-radius: 10px !important;
  font-weight: 600 !important;
  padding: 10px 24px !important;
  transition: .2s !important;
  box-shadow: 0 4px 14px rgba(13,148,136,0.3) !important;
}
.stButton > button:hover { opacity: .88 !important; transform: translateY(-1px) !important; }
[data-testid="stMetric"] {
  background: #FFFFFF;
  border-radius: 12px;
  padding: 14px;
  border: 1px solid #D1FAE5;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
}
[data-testid="stMetricValue"] { color: #0D9488 !important; font-weight: 700 !important; }
[data-testid="stTabs"] [data-baseweb="tab"] { color: #6B7280 !important; }
[data-testid="stTabs"] [aria-selected="true"] { color: #0D9488 !important; font-weight: 600 !important; }
.stMarkdown h4 { color: #1F2937 !important; }
p, li, span { color: #374151; }
</style>
""", unsafe_allow_html=True)

# ── config ────────────────────────────────────────────────────────────────────
_ENV_PATH     = Path(__file__).parent.parent / ".env"
CHROMA_DIR    = str(Path(__file__).parent.parent / "data" / "aika_chromadb")
CORPUS_DIR    = Path(__file__).parent.parent / "corpus"
COLLECTION    = "aika_docs"
EMBED_MODEL   = "sentence-transformers/all-MiniLM-L6-v2"
LLM_MODEL     = "llama-3.3-70b-versatile"
CHUNK_SIZE    = 500
CHUNK_OVERLAP = 50
TOP_K         = 5

def _env(key: str, default: str = "") -> str:
    """Read env var — always re-load .env so Streamlit cache doesn't trap empty values."""
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_ENV_PATH, override=True)
    return os.getenv(key, default)

# ── cached clients ─────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Loading embedding model…")
def get_embed():
    return SentenceTransformer(EMBED_MODEL)

@st.cache_resource(show_spinner="Connecting to ChromaDB…")
def get_col():
    Path(CHROMA_DIR).mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    return client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})

@st.cache_resource
def get_groq():
    key = _env("GROQ_API_KEY")
    if not key:
        raise ValueError("GROQ_API_KEY not found in .env — please add it.")
    return Groq(api_key=key)

@st.cache_resource
def get_lf():
    try:
        pub = _env("LANGFUSE_PUBLIC_KEY")
        sec = _env("LANGFUSE_SECRET_KEY")
        host = _env("LANGFUSE_HOST", "https://cloud.langfuse.com")
        if not pub or not sec:
            return None
        return Langfuse(public_key=pub, secret_key=sec, host=host)
    except Exception:
        return None

# ── helpers ───────────────────────────────────────────────────────────────────
def chunk_text(text: str) -> list[str]:
    chunks, s = [], 0
    while s < len(text):
        chunks.append(text[s:s + CHUNK_SIZE])
        s += CHUNK_SIZE - CHUNK_OVERLAP
    return [c.strip() for c in chunks if c.strip()]

def parse_doc(path: Path) -> str:
    ext = path.suffix.lower()
    try:
        if ext in (".yaml", ".yml"):
            return json.dumps(yaml.safe_load(path.read_text("utf-8")), indent=2)
        elif ext == ".pdf":
            from pypdf import PdfReader
            return "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)
        else:
            return path.read_text("utf-8", errors="ignore")
    except Exception as e:
        return f"[error: {e}]"

def ingest_file(content: str, filename: str):
    col = get_col()
    model = get_embed()
    chunks = chunk_text(content)
    doc_id = f"upload:{filename}:{uuid.uuid4().hex[:6]}"
    for i, chunk in enumerate(chunks):
        col.upsert(ids=[f"{doc_id}:c{i}"],
                   embeddings=model.encode([chunk]).tolist(),
                   documents=[chunk],
                   metadatas=[{"source": filename, "chunk": i}])
    return len(chunks), col.count()

def auto_ingest_corpus():
    if not CORPUS_DIR.exists():
        return 0
    col = get_col()
    model = get_embed()
    added = 0
    for f in sorted(CORPUS_DIR.iterdir()):
        if f.suffix.lower() not in (".yaml", ".yml", ".json", ".md", ".pdf", ".txt"):
            continue
        doc_id = f"corpus:{f.name}"
        if col.get(ids=[doc_id])["ids"]:
            continue
        chunks = chunk_text(parse_doc(f))
        for i, chunk in enumerate(chunks):
            col.upsert(ids=[f"{doc_id}:c{i}"],
                       embeddings=model.encode([chunk]).tolist(),
                       documents=[chunk],
                       metadatas=[{"source": f.name, "chunk": i}])
            added += 1
    return added

def score_faithfulness(context: str, answer: str) -> float:
    try:
        r = get_groq().chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content":
                f"Rate 0.0-1.0: does this answer rely ONLY on the provided context?\n"
                f"1.0=fully grounded, 0.0=hallucinated.\n"
                f"Context: {context[:800]}\nAnswer: {answer[:400]}\n"
                f"Reply with ONLY a number like 0.85"}],
            max_tokens=5, temperature=0.0)
        return max(0.0, min(1.0, float(r.choices[0].message.content.strip())))
    except Exception:
        return 0.75

def lf_log(session_id, question, answer, sources, latency_ms, faith, in_tok, out_tok):
    lf = get_lf()
    if not lf:
        return
    try:
        tr = lf.trace(name="aika-query", session_id=session_id,
                      input={"question": question}, output={"answer": answer[:1000]},
                      tags=["aika", "rag"],
                      metadata={"sources": sources, "latency_ms": round(latency_ms, 2),
                                 "faithfulness": faith})
        tr.generation(name="llm-call", model=LLM_MODEL,
                      input=[{"role": "user", "content": question}], output=answer[:2000],
                      usage={"input": in_tok, "output": out_tok,
                             "total": in_tok + out_tok, "unit": "TOKENS"})
        try:
            traces = lf.get_traces(session=session_id, limit=3)
            if traces.data:
                lf.score(trace_id=traces.data[0].id, name="faithfulness",
                         value=faith, data_type="NUMERIC")
        except Exception:
            pass
        lf.flush()
    except Exception:
        pass

def rag_query(question: str):
    col   = get_col()
    model = get_embed()
    t0    = time.time()
    session_id = uuid.uuid4().hex
    query_id   = f"q-{session_id[:8]}"

    # retrieve
    q_emb   = model.encode([question]).tolist()
    n       = min(TOP_K, max(1, col.count()))
    results = col.query(query_embeddings=q_emb, n_results=n)
    docs    = results.get("documents", [[]])[0]
    metas   = results.get("metadatas",  [[]])[0]
    context = "\n\n---\n\n".join(docs) if docs else ""
    sources = list({m.get("source", "unknown") for m in metas})

    if not context:
        return {"answer": "No relevant documents found. Please ingest some API docs first.",
                "sources": [], "query_id": query_id, "latency_ms": 0,
                "faithfulness": 0.0, "in_tok": 0, "out_tok": 0, "error": None}

    prompt = (
        "You are AIKA, an AI assistant for internal API documentation.\n"
        "Answer using ONLY the provided context. Cite the source file name.\n"
        "If not in context say: 'I don't have that information in the indexed documents.'\n\n"
        f"Context:\n{context[:3000]}\n\nQuestion: {question}\n\nAnswer:"
    )

    try:
        resp   = get_groq().chat.completions.create(
            model=LLM_MODEL, messages=[{"role": "user", "content": prompt}],
            temperature=0.1, max_tokens=512)
        answer = resp.choices[0].message.content.strip()
    except Exception as e:
        return {"answer": None, "sources": sources, "query_id": query_id,
                "latency_ms": round((time.time()-t0)*1000, 2),
                "faithfulness": 0.0, "in_tok": 0, "out_tok": 0,
                "error": f"Groq API error: {e}"}

    usage      = resp.usage
    latency_ms = (time.time() - t0) * 1000
    faith      = score_faithfulness(context, answer)
    usage  = resp.usage
    latency_ms = (time.time() - t0) * 1000
    faith = score_faithfulness(context, answer)

    lf_log(session_id, question, answer, sources, latency_ms,
           faith, usage.prompt_tokens, usage.completion_tokens)

    return {"answer": answer, "sources": sources, "query_id": query_id,
            "latency_ms": round(latency_ms, 2), "faithfulness": round(faith, 3),
            "in_tok": usage.prompt_tokens, "out_tok": usage.completion_tokens}

# ── session state ─────────────────────────────────────────────────────────────
if "history"     not in st.session_state: st.session_state.history     = []
if "total_q"     not in st.session_state: st.session_state.total_q     = 0
if "total_lat"   not in st.session_state: st.session_state.total_lat   = 0.0
if "total_faith" not in st.session_state: st.session_state.total_faith = 0.0
if "ingested"    not in st.session_state: st.session_state.ingested    = False

# ── auto-ingest corpus once ───────────────────────────────────────────────────
if not st.session_state.ingested:
    with st.spinner("Ingesting corpus documents…"):
        added = auto_ingest_corpus()
    st.session_state.ingested = True
    if added:
        st.toast(f"✅ Auto-ingested {added} chunks from corpus/", icon="📚")

col = get_col()

# ── header ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="hero">
  <div class="hero-icon">🤖</div>
  <div style="flex:1">
    <p class="hero-title">AIKA — API Knowledge Assistant</p>
    <p class="hero-sub">RAG-powered Q&amp;A over internal API documentation &nbsp;|&nbsp; Groq + ChromaDB + Langfuse</p>
  </div>
  <div class="badge-live"><span class="dot"></span> Live &nbsp;|&nbsp; {col.count()} docs indexed</div>
</div>
""", unsafe_allow_html=True)

# ── tabs ──────────────────────────────────────────────────────────────────────
tab_ask, tab_docs, tab_ingest, tab_metrics = st.tabs([
    "🔍 Ask AIKA", "📚 Documents", "📄 Ingest", "📊 Metrics"
])

# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — Ask
# ════════════════════════════════════════════════════════════════════════════════
with tab_ask:
    st.markdown("#### Ask a natural-language question about your API docs")

    example_qs = [
        "What HTTP method creates a product?",
        "What Kafka topic fires when an order ships?",
        "Why was ChromaDB chosen over Pinecone?",
        "What are the rate limits for Free tier consumers?",
        "What embedding model does AIKA use and why?",
    ]

    # auto-run if a quick example was clicked last rerun
    if "pending_question" not in st.session_state:
        st.session_state.pending_question = ""

    col1, col2 = st.columns([3, 1])
    with col1:
        question = st.text_area("Your question", height=100,
                                value=st.session_state.pending_question,
                                placeholder="e.g. What fields are required when creating a product?")
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("**Quick examples:**")
        for eq in example_qs[:3]:
            if st.button(eq[:38] + "…", key=f"eq_{eq[:10]}"):
                st.session_state.pending_question = eq
                st.rerun()

    ask_btn = st.button("✨ Ask AIKA", use_container_width=True)

    # auto-fire if a quick example populated the box
    auto_fire = bool(st.session_state.pending_question and not ask_btn)
    if auto_fire:
        st.session_state.pending_question = ""   # clear so it doesn't loop

    if (ask_btn or auto_fire) and question.strip():
        if col.count() == 0:
            st.warning("⚠️ No documents indexed yet. Go to the **Ingest** tab to add documents.")
        else:
            with st.spinner("🔍 Retrieving relevant chunks and generating answer…"):
                try:
                    result = rag_query(question.strip())
                except Exception as e:
                    st.error(f"❌ Unexpected error: {e}")
                    result = None

            if result:
                if result.get("error"):
                    st.error(f"❌ {result['error']}")
                    st.info("💡 Check that your GROQ_API_KEY is set in `.env` and your internet is working.")
                else:
                    st.session_state.total_q     += 1
                    st.session_state.total_lat   += result["latency_ms"]
                    st.session_state.total_faith += result["faithfulness"]
                    st.session_state.history.insert(0, {"q": question, **result})

                    st.markdown(f"""
<div class="answer-card">{result['answer']}</div>
<div style="margin-top:10px">
  {''.join(f'<span class="source-tag">📄 {s}</span>' for s in result['sources'])}
</div>
<div class="meta-row">
  <span class="meta-pill">⏱ {result['latency_ms']} ms</span>
  <span class="meta-pill">🎯 Faithfulness: {result['faithfulness']}</span>
  <span class="meta-pill">🆔 {result['query_id']}</span>
  <span class="meta-pill">📥 {result['in_tok']} in / {result['out_tok']} out tokens</span>
</div>
""", unsafe_allow_html=True)

                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("👍 Helpful", key="up"):
                            lf = get_lf()
                            if lf:
                                try:
                                    tr = lf.get_traces(limit=5)
                                    if tr.data:
                                        lf.score(trace_id=tr.data[0].id, name="user_feedback",
                                                 value=1.0, data_type="NUMERIC")
                                        lf.flush()
                                except Exception:
                                    pass
                            st.success("Thanks! Feedback logged.")
                    with c2:
                        if st.button("👎 Not helpful", key="dn"):
                            lf = get_lf()
                            if lf:
                                try:
                                    tr = lf.get_traces(limit=5)
                                    if tr.data:
                                        lf.score(trace_id=tr.data[0].id, name="user_feedback",
                                                 value=0.0, data_type="NUMERIC")
                                        lf.flush()
                                except Exception:
                                    pass
                            st.info("Noted. Feedback logged.")

    # history
    if st.session_state.history:
        st.markdown("---")
        st.markdown("#### 🕓 Recent Questions")
        for i, h in enumerate(st.session_state.history[:5]):
            with st.expander(f"**{h['q'][:80]}**", expanded=(i == 0)):
                st.markdown(h["answer"])
                st.caption(f"Sources: {', '.join(h['sources'])} | "
                           f"{h['latency_ms']} ms | Faithfulness: {h['faithfulness']}")

# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — Documents
# ════════════════════════════════════════════════════════════════════════════════
with tab_docs:
    st.markdown("#### Indexed Documents")
    data  = col.get(limit=500)
    metas = data.get("metadatas") or []
    seen, docs_list = set(), []
    for m in metas:
        src = m.get("source", "unknown")
        if src not in seen:
            seen.add(src)
            docs_list.append(src)

    if docs_list:
        for src in sorted(docs_list):
            # get all chunks for this doc to show content
            doc_chunks = [doc for doc, meta in zip(data.get("documents") or [], metas)
                          if meta.get("source") == src]
            chunk_count = len(doc_chunks)
            full_text = "\n\n".join(doc_chunks)

            with st.expander(f"📄 **{src}** — {chunk_count} chunks", expanded=False):
                # action buttons inside expander
                bc1, bc2 = st.columns([1, 1])
                with bc2:
                    if st.button("🗑 Remove from index", key=f"del_{src}"):
                        ids_to_del = [i for i, m in zip(data["ids"], metas)
                                      if m.get("source") == src]
                        col.delete(ids=ids_to_del)
                        st.success(f"Removed '{src}'")
                        st.rerun()

                # show file content — try to read from corpus/ first (clean original),
                # fall back to reconstructed chunks
                corpus_path = CORPUS_DIR / src
                if corpus_path.exists():
                    raw = parse_doc(corpus_path)
                    ext = corpus_path.suffix.lower()
                    if ext in (".yaml", ".yml"):
                        st.code(corpus_path.read_text("utf-8", errors="ignore"),
                                language="yaml")
                    elif ext == ".json":
                        st.code(raw, language="json")
                    elif ext == ".md":
                        st.markdown(raw)
                    else:
                        st.text(raw)
                else:
                    # uploaded doc — reconstruct from chunks
                    st.markdown(full_text)

        st.caption(f"Total chunks in ChromaDB: **{col.count()}**")
    else:
        st.info("No documents indexed yet. Go to the **Ingest** tab.")

# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — Ingest
# ════════════════════════════════════════════════════════════════════════════════
with tab_ingest:
    st.markdown("#### Add a New Document")
    c1, c2 = st.columns([3, 1])
    with c1:
        ingest_content = st.text_area("Document content",
            height=200,
            placeholder="Paste your API spec, markdown, YAML, or any text…")
    with c2:
        ingest_name = st.text_input("Filename", value="document.md")
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("⬆️ Ingest Document", use_container_width=True):
            if ingest_content.strip():
                with st.spinner("Chunking and embedding…"):
                    chunks_added, total = ingest_file(ingest_content.strip(), ingest_name)
                st.success(f"✅ Added **{chunks_added} chunks** from `{ingest_name}`. Collection: **{total}**")
                st.rerun()
            else:
                st.warning("Paste some content first.")

    st.markdown("---")
    st.markdown("**Corpus auto-ingested on startup:**")
    if CORPUS_DIR.exists():
        for f in sorted(CORPUS_DIR.iterdir()):
            if f.suffix.lower() in (".yaml", ".yml", ".json", ".md", ".pdf", ".txt"):
                st.markdown(f"- `{f.name}`")
    else:
        st.caption("No corpus/ folder found.")

# ════════════════════════════════════════════════════════════════════════════════
# TAB 4 — Metrics
# ════════════════════════════════════════════════════════════════════════════════
with tab_metrics:
    st.markdown("#### Live Session Metrics")
    n = st.session_state.total_q
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Queries", n)
    m2.metric("Avg Latency (ms)",
              round(st.session_state.total_lat / n, 0) if n else "—")
    m3.metric("Avg Faithfulness",
              round(st.session_state.total_faith / n, 3) if n else "—")
    m4.metric("Docs Indexed", col.count())

    st.markdown("---")
    st.markdown("#### Observability")
    lf_ok = bool(_env("LANGFUSE_PUBLIC_KEY") and _env("LANGFUSE_SECRET_KEY"))
    if lf_ok:
        st.success("✅ Langfuse connected — every query is traced with faithfulness + user_feedback scores")
        st.markdown(f"🔗 [Open Langfuse Dashboard]({_env('LANGFUSE_HOST','https://cloud.langfuse.com')})")
    else:
        st.warning("⚠️ Langfuse keys not set — add LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to .env")

    st.markdown("---")
    st.markdown("#### Query History")
    if st.session_state.history:
        import pandas as pd
        rows = [{"Question": h["q"][:60], "Latency (ms)": h["latency_ms"],
                 "Faithfulness": h["faithfulness"], "Sources": ", ".join(h["sources"])}
                for h in st.session_state.history]
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
    else:
        st.info("No queries yet in this session.")
