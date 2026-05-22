"""
StockPulse — live auto-refreshing stock dashboard
"""
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="StockPulse", page_icon="📈", layout="wide")

# ── Auto-refresh every 30 seconds (30000 ms) ──────────────────────────────────
_refresh_count = st_autorefresh(interval=30_000, limit=None, key="live_refresh")

st.markdown("""
<style>
[data-testid="stAppViewContainer"]{background:#0b0e11;color:#eaecef;}
[data-testid="stHeader"]{background:transparent;}
#MainMenu,footer{visibility:hidden;}
.block-container{padding:1rem 2rem 2rem!important;max-width:100%!important;}
section[data-testid="stSidebar"]{display:none;}
.icard{background:#1e2329;border:1px solid #2b3139;border-radius:10px;padding:12px 16px;text-align:center;}
.iname{font-size:.7rem;color:#848e9c;letter-spacing:.06em;text-transform:uppercase;}
.iprice{font-size:1.1rem;font-weight:700;color:#eaecef;margin:4px 0 2px;}
.up{color:#0ecb81;font-size:.8rem;font-weight:600;}
.down{color:#f6465d;font-size:.8rem;font-weight:600;}
.wcard{background:#1e2329;border:1px solid #2b3139;border-radius:8px;padding:10px 14px;margin-bottom:4px;display:flex;justify-content:space-between;align-items:center;}
.wcard.sel{border-color:#f0b90b;}
.wsym{font-size:.9rem;font-weight:600;color:#eaecef;}
.wname{font-size:.7rem;color:#848e9c;margin-top:2px;}
.wprice{font-size:.88rem;font-weight:600;color:#eaecef;text-align:right;}
.wchg{font-size:.73rem;text-align:right;margin-top:2px;}
.dtitle{font-size:1.4rem;font-weight:700;color:#eaecef;}
.dprice{font-size:2rem;font-weight:700;color:#eaecef;margin:4px 0;}
.bbuy{background:rgba(14,203,129,.15);color:#0ecb81;border:1px solid #0ecb81;padding:5px 18px;border-radius:6px;font-weight:700;font-size:.88rem;display:inline-block;}
.bsell{background:rgba(246,70,93,.15);color:#f6465d;border:1px solid #f6465d;padding:5px 18px;border-radius:6px;font-weight:700;font-size:.88rem;display:inline-block;}
.bhold{background:rgba(240,185,11,.15);color:#f0b90b;border:1px solid #f0b90b;padding:5px 18px;border-radius:6px;font-weight:700;font-size:.88rem;display:inline-block;}
.ncard{background:#1e2329;border:1px solid #2b3139;border-radius:8px;padding:12px 14px;margin-bottom:8px;}
.stButton>button{background:#1e2329!important;color:#848e9c!important;border:1px solid #2b3139!important;border-radius:6px!important;font-size:.78rem!important;padding:4px 8px!important;width:100%;}
.stButton>button:hover{border-color:#f0b90b!important;color:#f0b90b!important;}
div[data-testid="stTabs"] button{color:#848e9c!important;font-size:.82rem!important;}
div[data-testid="stTabs"] button[aria-selected="true"]{color:#f0b90b!important;border-bottom-color:#f0b90b!important;}
</style>
""", unsafe_allow_html=True)

# ── Tickers ───────────────────────────────────────────────────────────────────
INDICES = {"^NSEI":"NIFTY 50","^BSESN":"SENSEX","^GSPC":"S&P 500","^IXIC":"NASDAQ","^DJI":"DOW JONES"}

# ── Search database (ticker → full name) for suggestions ─────────────────────
SEARCH_DB = {
    # ── NIFTY 50 / Large Cap India ────────────────────────────────────────────
    "RELIANCE.NS":    "Reliance Industries",
    "TCS.NS":         "Tata Consultancy Services",
    "HDFCBANK.NS":    "HDFC Bank",
    "INFY.NS":        "Infosys",
    "ICICIBANK.NS":   "ICICI Bank",
    "HINDUNILVR.NS":  "Hindustan Unilever",
    "SBIN.NS":        "State Bank of India",
    "BHARTIARTL.NS":  "Bharti Airtel",
    "BAJFINANCE.NS":  "Bajaj Finance",
    "KOTAKBANK.NS":   "Kotak Mahindra Bank",
    "LT.NS":          "Larsen & Toubro",
    "WIPRO.NS":       "Wipro",
    "HCLTECH.NS":     "HCL Technologies",
    "ASIANPAINT.NS":  "Asian Paints",
    "AXISBANK.NS":    "Axis Bank",
    "MARUTI.NS":      "Maruti Suzuki",
    "TATAMOTORS.NS":  "Tata Motors",
    "TITAN.NS":       "Titan Company",
    "SUNPHARMA.NS":   "Sun Pharmaceutical",
    "ONGC.NS":        "ONGC",
    "NTPC.NS":        "NTPC",
    "POWERGRID.NS":   "Power Grid Corporation",
    "TECHM.NS":       "Tech Mahindra",
    "ULTRACEMCO.NS":  "UltraTech Cement",
    "NESTLEIND.NS":   "Nestle India",
    "DRREDDY.NS":     "Dr. Reddy's Laboratories",
    "CIPLA.NS":       "Cipla",
    "DIVISLAB.NS":    "Divi's Laboratories",
    "BAJAJFINSV.NS":  "Bajaj Finserv",
    "TATASTEEL.NS":   "Tata Steel",
    "JSWSTEEL.NS":    "JSW Steel",
    "HINDALCO.NS":    "Hindalco Industries",
    "COALINDIA.NS":   "Coal India",
    "INDUSINDBK.NS":  "IndusInd Bank",
    "EICHERMOT.NS":   "Eicher Motors",
    "BPCL.NS":        "Bharat Petroleum",
    "HEROMOTOCO.NS":  "Hero MotoCorp",
    "GRASIM.NS":      "Grasim Industries",
    "BRITANNIA.NS":   "Britannia Industries",
    # ── Adani Group ────────────────────────────────────────────────────────────
    "ADANIENT.NS":    "Adani Enterprises",
    "ADANIPORTS.NS":  "Adani Ports & SEZ",
    "ADANIPOWER.NS":  "Adani Power",
    "ADANIGREEN.NS":  "Adani Green Energy",
    "ADANITRANS.NS":  "Adani Transmission",
    "ADANIGAS.NS":    "Adani Total Gas",
    "AWL.NS":         "Adani Wilmar",
    # ── Tata Group ─────────────────────────────────────────────────────────────
    "TATACONSUM.NS":  "Tata Consumer Products",
    "TATACOMM.NS":    "Tata Communications",
    "TATAELXSI.NS":   "Tata Elxsi",
    "TATAPOWER.NS":   "Tata Power",
    # ── Mid/Small Cap India ─────────────────────────────────────────────────────
    "ZOMATO.NS":      "Zomato",
    "PAYTM.NS":       "Paytm (One97 Comm)",
    "NYKAA.NS":       "Nykaa (FSN E-Commerce)",
    "POLICYBZR.NS":   "PolicyBazaar",
    "DELHIVERY.NS":   "Delhivery",
    "IRCTC.NS":       "IRCTC",
    "IRFC.NS":        "IRFC",
    "HAL.NS":         "Hindustan Aeronautics",
    "BEL.NS":         "Bharat Electronics",
    "PIDILITIND.NS":  "Pidilite Industries",
    "HAVELLS.NS":     "Havells India",
    "VOLTAS.NS":      "Voltas",
    "MUTHOOTFIN.NS":  "Muthoot Finance",
    "CHOLAFIN.NS":    "Cholamandalam Fin",
    "PERSISTENT.NS":  "Persistent Systems",
    "COFORGE.NS":     "Coforge",
    "MPHASIS.NS":     "Mphasis",
    "LTIM.NS":        "LTIMindtree",
    # ── US Stocks ─────────────────────────────────────────────────────────────
    "AAPL":   "Apple Inc",
    "MSFT":   "Microsoft Corp",
    "GOOGL":  "Alphabet (Google) Class A",
    "GOOG":   "Alphabet (Google) Class C",
    "AMZN":   "Amazon.com",
    "NVDA":   "Nvidia Corp",
    "META":   "Meta Platforms",
    "TSLA":   "Tesla Inc",
    "NFLX":   "Netflix Inc",
    "ORCL":   "Oracle Corp",
    "AMD":    "Advanced Micro Devices",
    "INTC":   "Intel Corp",
    "QCOM":   "Qualcomm",
    "AVGO":   "Broadcom Inc",
    "CRM":    "Salesforce",
    "ADBE":   "Adobe Inc",
    "PYPL":   "PayPal Holdings",
    "UBER":   "Uber Technologies",
    "LYFT":   "Lyft Inc",
    "SNAP":   "Snap Inc",
    "TWTR":   "Twitter/X",
    "COIN":   "Coinbase Global",
    "RBLX":   "Roblox Corp",
    "SPOT":   "Spotify",
    "SHOP":   "Shopify",
    "SQ":     "Block (Square)",
    "HOOD":   "Robinhood Markets",
    "PLTR":   "Palantir Technologies",
    "JPM":    "JPMorgan Chase",
    "BAC":    "Bank of America",
    "WMT":    "Walmart Inc",
    "KO":     "Coca-Cola",
    "PEP":    "PepsiCo",
    "MCD":    "McDonald's",
    "DIS":    "Walt Disney",
    "V":      "Visa Inc",
    "MA":     "Mastercard",
    "BRK-B":  "Berkshire Hathaway B",
    "JNJ":    "Johnson & Johnson",
    "PFE":    "Pfizer",
    "MRNA":   "Moderna",
    "BNTX":   "BioNTech",
    "XOM":    "Exxon Mobil",
    "CVX":    "Chevron Corp",
    "GS":     "Goldman Sachs",
    "MS":     "Morgan Stanley",
    "NFLX":   "Netflix",
    "ABNB":   "Airbnb",
    "DASH":   "DoorDash",
}


def search_tickers(query: str) -> list[tuple[str, str]]:
    """Return up to 8 (ticker, name) matches for the query."""
    if not query or len(query) < 1:
        return []
    q = query.upper().strip()
    results = []
    # Exact ticker prefix first
    for ticker, name in SEARCH_DB.items():
        base = ticker.replace(".NS", "").replace(".BO", "")
        if base.startswith(q) or ticker.startswith(q):
            results.append((ticker, name))
    # Then name keyword match
    for ticker, name in SEARCH_DB.items():
        if (ticker, name) not in results:
            if q in name.upper() or q.lower() in name.lower():
                results.append((ticker, name))
    return results[:8]

WL_IN = [
    ("RELIANCE",   "RELIANCE.NS",   "Reliance Industries"),
    ("TCS",        "TCS.NS",        "Tata Consultancy"),
    ("HDFC BK",    "HDFCBANK.NS",   "HDFC Bank"),
    ("INFOSYS",    "INFY.NS",       "Infosys"),
    ("ICICI BK",   "ICICIBANK.NS",  "ICICI Bank"),
    ("WIPRO",      "WIPRO.NS",      "Wipro"),
    ("SBI",        "SBIN.NS",       "State Bank India"),
    ("BAJFIN",     "BAJFINANCE.NS", "Bajaj Finance"),
    ("TATAMOTO",   "TATAMOTORS.NS", "Tata Motors"),
    ("ADANI ENT",  "ADANIENT.NS",   "Adani Enterprises"),
]
WL_US = [
    ("AAPL",  "AAPL",  "Apple"),
    ("MSFT",  "MSFT",  "Microsoft"),
    ("GOOGL", "GOOGL", "Alphabet"),
    ("NVDA",  "NVDA",  "Nvidia"),
    ("TSLA",  "TSLA",  "Tesla"),
    ("AMZN",  "AMZN",  "Amazon"),
    ("META",  "META",  "Meta"),
    ("NFLX",  "NFLX",  "Netflix"),
]

ALL_TICKERS = (list(INDICES.keys()) +
               [t for _, t, _ in WL_IN] +
               [t for _, t, _ in WL_US])

PERIOD_MAP = {"1D":"1d","5D":"5d","1M":"1mo","3M":"3mo","6M":"6mo","1Y":"1y","2Y":"2y"}

# ── Batch price fetch (ONE call for everything) ───────────────────────────────
@st.cache_data(ttl=120, show_spinner=False)
def load_all_quotes():
    """Download 5 days of daily data for ALL tickers in ONE request."""
    try:
        raw = yf.download(ALL_TICKERS, period="5d", interval="1d",
                          auto_adjust=True, progress=False, group_by="ticker")
        quotes = {}
        for tk in ALL_TICKERS:
            try:
                if len(ALL_TICKERS) == 1:
                    closes = raw["Close"].dropna()
                else:
                    closes = raw[tk]["Close"].dropna()
                if len(closes) < 1:
                    continue
                price = float(closes.iloc[-1])
                prev  = float(closes.iloc[-2]) if len(closes) >= 2 else price
                chg   = price - prev
                pct   = (chg / prev * 100) if prev else 0.0
                quotes[tk] = (round(price,2), round(chg,2), round(pct,2))
            except Exception:
                pass
        return quotes
    except Exception:
        return {}

@st.cache_data(ttl=120, show_spinner=False)
def load_detail(ticker: str, period: str):
    tk   = yf.Ticker(ticker)
    hist = tk.history(period=period)
    info = {}
    try:   info = tk.info
    except: pass
    news = []
    try:   news = tk.news[:6]
    except: pass
    return hist, info, news

def indicators(df):
    df = df.copy()
    df["MA20"]  = df["Close"].rolling(20).mean()
    df["MA50"]  = df["Close"].rolling(50).mean()
    df["MA200"] = df["Close"].rolling(200).mean()
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0,1e-9)
    df["RSI"]         = 100 - 100/(1+rs)
    e12               = df["Close"].ewm(span=12,adjust=False).mean()
    e26               = df["Close"].ewm(span=26,adjust=False).mean()
    df["MACD"]        = e12 - e26
    df["MACD_Sig"]    = df["MACD"].ewm(span=9,adjust=False).mean()
    df["MACD_Hist"]   = df["MACD"] - df["MACD_Sig"]
    df["BB_Mid"]      = df["Close"].rolling(20).mean()
    df["BB_Up"]       = df["BB_Mid"] + 2*df["Close"].rolling(20).std()
    df["BB_Lo"]       = df["BB_Mid"] - 2*df["Close"].rolling(20).std()
    return df

def signal(df):
    if df.empty or len(df)<20: return "HOLD","Not enough data"
    rsi   = df["RSI"].iloc[-1]  if df["RSI"].notna().any()  else 50
    price = df["Close"].iloc[-1]
    ma20  = df["MA20"].iloc[-1] if df["MA20"].notna().any() else price
    ma50  = df["MA50"].iloc[-1] if df["MA50"].notna().any() else price
    score = 0; r = []
    if   rsi<35: score+=2; r.append(f"RSI oversold ({rsi:.0f})")
    elif rsi>65: score-=2; r.append(f"RSI overbought ({rsi:.0f})")
    else:                   r.append(f"RSI neutral ({rsi:.0f})")
    if ma20>ma50: score+=1; r.append("MA20>MA50 ✓")
    else:         score-=1; r.append("MA20<MA50 ✗")
    if price>ma20: score+=1; r.append("Above MA20")
    else:          score-=1; r.append("Below MA20")
    s = "BUY" if score>=2 else ("SELL" if score<=-2 else "HOLD")
    return s, "  ·  ".join(r)

def fv(v, pre="", suf="", d=2):
    if v is None: return "—"
    try:
        n=float(v)
        if abs(n)>=1e12: return f"{pre}{n/1e12:.2f}T{suf}"
        if abs(n)>=1e9:  return f"{pre}{n/1e9:.2f}B{suf}"
        if abs(n)>=1e6:  return f"{pre}{n/1e6:.2f}M{suf}"
        return f"{pre}{n:,.{d}f}{suf}"
    except: return "—"

BG = dict(paper_bgcolor="#0b0e11",plot_bgcolor="#161b22",
          font=dict(color="#848e9c",size=11),margin=dict(l=0,r=0,t=24,b=0),
          xaxis=dict(gridcolor="#1e2329",showgrid=True,zeroline=False),
          yaxis=dict(gridcolor="#1e2329",showgrid=True,zeroline=False),
          legend=dict(bgcolor="rgba(0,0,0,0)",font_size=11))

# ── Session state ─────────────────────────────────────────────────────────────
if "sel" not in st.session_state:  st.session_state.sel  = ("RELIANCE.NS","Reliance Industries")
if "per" not in st.session_state:  st.session_state.per  = "3mo"

# ── NAV ───────────────────────────────────────────────────────────────────────
c1,c2 = st.columns([1,1])
c1.markdown("## 📈 Stock**Pulse**")
c2.markdown(
    f"<div style='text-align:right;padding-top:10px;'>"
    f"<span style='background:#0ecb81;color:#000;font-size:.68rem;font-weight:700;"
    f"padding:3px 8px;border-radius:4px;margin-right:8px;'>● LIVE</span>"
    f"<span style='color:#848e9c;font-size:.82rem;'>"
    f"🕐 {datetime.now().strftime('%d %b %Y  %H:%M:%S')}"
    f"&nbsp;&nbsp;·&nbsp;&nbsp;auto-refresh in 30s</span>"
    f"</div>",
    unsafe_allow_html=True,
)
st.markdown("<hr style='border-color:#1e2329;margin:4px 0 14px;'>",unsafe_allow_html=True)

# ── Load ALL quotes (cache busts every 30s via ttl) ───────────────────────────
with st.spinner("⚡ Loading market data…"):
    Q = load_all_quotes()

# ── INDEX BAR ─────────────────────────────────────────────────────────────────
cols = st.columns(len(INDICES))
for col,(sym,name) in zip(cols,INDICES.items()):
    p,c,pct = Q.get(sym,(None,0,0))
    with col:
        if p:
            cls = "up" if c>=0 else "down"
            arr = "▲" if c>=0 else "▼"
            st.markdown(f"""<div class="icard">
              <div class="iname">{name}</div>
              <div class="iprice">{p:,.2f}</div>
              <div class="{cls}">{arr} {abs(pct):.2f}%</div>
            </div>""",unsafe_allow_html=True)
        else:
            st.markdown(f"""<div class="icard">
              <div class="iname">{name}</div>
              <div class="iprice" style="color:#848e9c">—</div>
            </div>""",unsafe_allow_html=True)

st.markdown("<div style='height:16px'></div>",unsafe_allow_html=True)

# ── MAIN ──────────────────────────────────────────────────────────────────────
left, right = st.columns([1,2.8],gap="large")

with left:
    search = st.text_input("","",placeholder="🔍  AAPL · TCS.NS · RELIANCE.NS",
                           label_visibility="collapsed")
    tab_in, tab_us, tab_s = st.tabs(["🇮🇳 India","🇺🇸 US","🔍 Search"])

    def wl(items):
        for short,tk,full in items:
            p,c,pct = Q.get(tk,(None,0,0))
            if p is None: continue
            curr  = "₹" if ".NS" in tk or ".BO" in tk else "$"
            cls   = "up" if c>=0 else "down"
            arr   = "▲" if c>=0 else "▼"
            sel   = "sel" if st.session_state.sel[0]==tk else ""
            st.markdown(f"""<div class="wcard {sel}">
              <div><div class="wsym">{short}</div><div class="wname">{full}</div></div>
              <div><div class="wprice">{curr}{p:,.2f}</div>
                   <div class="wchg {cls}">{arr} {abs(pct):.2f}%</div></div>
            </div>""",unsafe_allow_html=True)
            if st.button(short, key=f"b_{tk}",use_container_width=True):
                st.session_state.sel = (tk, full)
                st.rerun()

    with tab_in: wl(WL_IN)
    with tab_us: wl(WL_US)
    with tab_s:
        suggestions = search_tickers(search)
        if search.strip() and suggestions:
            st.markdown(f"<div style='color:#848e9c;font-size:.72rem;margin-bottom:6px;'>"
                        f"Showing {len(suggestions)} results for \"{search}\"</div>",
                        unsafe_allow_html=True)
            for i, (tk2, fname) in enumerate(suggestions):
                curr2 = "₹" if ".NS" in tk2 or ".BO" in tk2 else "$"
                p2, c2, pct2 = Q.get(tk2, (None, 0, 0))
                cls2  = "up" if (c2 or 0) >= 0 else "down"
                arr2  = "▲" if (c2 or 0) >= 0 else "▼"
                price_html = (
                    f"<div class='wprice'>{curr2}{p2:,.2f}</div>"
                    f"<div class='wchg {cls2}'>{arr2} {abs(pct2):.2f}%</div>"
                    if p2 else
                    "<div class='wprice' style='color:#848e9c'>—</div>"
                )
                st.markdown(f"""<div class="wcard">
                  <div>
                    <div class="wsym">{tk2.replace('.NS','').replace('.BO','')}</div>
                    <div class="wname">{fname}</div>
                  </div>
                  <div>{price_html}</div>
                </div>""", unsafe_allow_html=True)
                if st.button(fname[:28], key=f"sug_{i}_{tk2}", use_container_width=True):
                    st.session_state.sel = (tk2, fname)
                    st.rerun()
        elif search.strip():
            st.markdown(f"<div style='color:#848e9c;font-size:.8rem;margin:8px 0;'>"
                        f"No matches for <b>{search}</b>. Try exact ticker (e.g. AAPL, TCS.NS)</div>",
                        unsafe_allow_html=True)
        else:
            st.markdown("<div style='color:#848e9c;font-size:.8rem;margin:8px 0;'>"
                        "Start typing a stock name or ticker…<br><br>"
                        "Examples:<br>"
                        "• <b>Adani</b> → shows all Adani stocks<br>"
                        "• <b>Tata</b> → shows all Tata stocks<br>"
                        "• <b>AAPL</b> → Apple Inc<br>"
                        "• <b>Bank</b> → all banks</div>",
                        unsafe_allow_html=True)

with right:
    ticker, name = st.session_state.sel
    curr = "₹" if ".NS" in ticker or ".BO" in ticker else "$"

    with st.spinner(f"Loading {ticker}…"):
        hist, info, news = load_detail(ticker, st.session_state.per)

    if hist.empty:
        st.error(f"No data for {ticker}"); st.stop()

    df  = indicators(hist)
    sig, sig_r = signal(df)

    p,c,pct = Q.get(ticker,(None,0,0))
    if p is None: p=float(df["Close"].iloc[-1]); c=0.0; pct=0.0
    cls = "up" if c>=0 else "down"
    arr = "▲" if c>=0 else "▼"
    bdg = f"b{sig.lower()}"

    h1,h2 = st.columns([3,1])
    with h1:
        st.markdown(f"""
        <div class="dtitle">{name} <span style="color:#848e9c;font-size:.88rem">({ticker})</span></div>
        <div class="dprice">{curr}{p:,.2f}</div>
        <div class="{cls}" style="font-size:.88rem;font-weight:500;">
          {arr} {curr}{abs(c):,.2f} ({abs(pct):.2f}%) Today
        </div>""",unsafe_allow_html=True)
    with h2:
        st.markdown(f"""<div style="text-align:right;padding-top:8px;">
          <span class="{bdg}">{sig}</span>
          <div style="font-size:.68rem;color:#848e9c;margin-top:8px;line-height:1.6;">{sig_r[:100]}</div>
        </div>""",unsafe_allow_html=True)

    st.markdown("<div style='height:6px'></div>",unsafe_allow_html=True)

    # Period buttons
    pcols = st.columns(len(PERIOD_MAP))
    for col,(lbl,val) in zip(pcols,PERIOD_MAP.items()):
        with col:
            if st.button(lbl,key=f"p_{val}"):
                st.session_state.per=val; st.rerun()

    st.markdown("<div style='height:4px'></div>",unsafe_allow_html=True)

    t_chart, t_ind, t_fund, t_news = st.tabs(["📊 Chart","📉 Indicators","📋 Fundamentals","📰 News"])

    with t_chart:
        fig = make_subplots(rows=2,cols=1,shared_xaxes=True,
                            row_heights=[.72,.28],vertical_spacing=.02)
        fig.add_trace(go.Candlestick(x=df.index,open=df["Open"],high=df["High"],
            low=df["Low"],close=df["Close"],name="Price",
            increasing_line_color="#0ecb81",decreasing_line_color="#f6465d",
            increasing_fillcolor="#0ecb81",decreasing_fillcolor="#f6465d"),row=1,col=1)
        for ma,cl in [("MA20","#f0b90b"),("MA50","#a78bfa"),("MA200","#f87171")]:
            s=df[ma].dropna()
            if not s.empty:
                fig.add_trace(go.Scatter(x=s.index,y=s,name=ma,
                    line=dict(color=cl,width=1.3,dash="dot"),opacity=.85),row=1,col=1)
        vc=["#0ecb81" if c>=o else "#f6465d" for c,o in zip(df["Close"],df["Open"])]
        fig.add_trace(go.Bar(x=df.index,y=df["Volume"],marker_color=vc,
            opacity=.55,name="Vol",showlegend=False),row=2,col=1)
        fig.update_layout(**BG,height=480,xaxis_rangeslider_visible=False)
        st.plotly_chart(fig,use_container_width=True)

    with t_ind:
        ca,cb = st.columns(2)
        with ca:
            r=df.dropna(subset=["RSI"])
            fr=go.Figure()
            fr.add_trace(go.Scatter(x=r.index,y=r["RSI"],line=dict(color="#58a6ff",width=2),name="RSI"))
            fr.add_hrect(y0=70,y1=100,fillcolor="#f6465d",opacity=.07,line_width=0)
            fr.add_hrect(y0=0,y1=30,fillcolor="#0ecb81",opacity=.07,line_width=0)
            fr.add_hline(y=70,line_color="#f6465d",line_dash="dash",line_width=1)
            fr.add_hline(y=30,line_color="#0ecb81",line_dash="dash",line_width=1)
            fr.update_layout(**BG,height=240,
                title=dict(text="RSI (14)",font=dict(color="#eaecef",size=12)))
            fr.update_yaxes(range=[0,100])
            st.plotly_chart(fr,use_container_width=True)
        with cb:
            m=df.dropna(subset=["MACD"])
            hc=["#0ecb81" if v>=0 else "#f6465d" for v in m["MACD_Hist"]]
            fm=go.Figure()
            fm.add_trace(go.Bar(x=m.index,y=m["MACD_Hist"],marker_color=hc,opacity=.7,name="Hist"))
            fm.add_trace(go.Scatter(x=m.index,y=m["MACD"],line=dict(color="#58a6ff",width=1.8),name="MACD"))
            fm.add_trace(go.Scatter(x=m.index,y=m["MACD_Sig"],
                line=dict(color="#f0b90b",width=1.8,dash="dot"),name="Signal"))
            fm.update_layout(**BG,height=240,
                title=dict(text="MACD (12,26,9)",font=dict(color="#eaecef",size=12)))
            st.plotly_chart(fm,use_container_width=True)
        b=df.dropna(subset=["BB_Up"])
        fb=go.Figure()
        fb.add_trace(go.Scatter(x=b.index,y=b["BB_Up"],name="Upper",
            line=dict(color="#a78bfa",width=1,dash="dot")))
        fb.add_trace(go.Scatter(x=b.index,y=b["BB_Lo"],name="Lower",
            fill="tonexty",fillcolor="rgba(167,139,250,.05)",
            line=dict(color="#a78bfa",width=1,dash="dot")))
        fb.add_trace(go.Scatter(x=b.index,y=b["Close"],name="Price",
            line=dict(color="#f0b90b",width=1.8)))
        fb.update_layout(**BG,height=260,
            title=dict(text="Bollinger Bands (20)",font=dict(color="#eaecef",size=12)))
        st.plotly_chart(fb,use_container_width=True)

    with t_fund:
        st.markdown("**Key Metrics**")
        m1,m2,m3,m4,m5,m6=st.columns(6)
        m1.metric("Mkt Cap",    fv(info.get("marketCap"),     pre=curr))
        m2.metric("P/E",        fv(info.get("trailingPE"),    d=1))
        m3.metric("EPS (TTM)",  fv(info.get("trailingEps"),   pre=curr))
        m4.metric("Revenue",    fv(info.get("totalRevenue"),  pre=curr))
        m5.metric("Div Yield",  fv(info.get("dividendYield"), suf="%",d=2) if info.get("dividendYield") else "—")
        m6.metric("Beta",       fv(info.get("beta"),d=2))
        st.markdown("**Profitability**")
        p1,p2,p3,p4=st.columns(4)
        p1.metric("Profit Margin",  fv(info.get("profitMargins"),  suf="%",d=1) if info.get("profitMargins") else "—")
        p2.metric("ROE",            fv(info.get("returnOnEquity"), suf="%",d=1) if info.get("returnOnEquity") else "—")
        p3.metric("ROA",            fv(info.get("returnOnAssets"), suf="%",d=1) if info.get("returnOnAssets") else "—")
        p4.metric("Debt/Equity",    fv(info.get("debtToEquity"),d=2))
        st.markdown("**Price Range**")
        q1,q2,q3,q4=st.columns(4)
        q1.metric("52W High",fv(info.get("fiftyTwoWeekHigh"),pre=curr))
        q2.metric("52W Low", fv(info.get("fiftyTwoWeekLow"), pre=curr))
        q3.metric("Day High",fv(info.get("dayHigh"),pre=curr))
        q4.metric("Day Low", fv(info.get("dayLow"), pre=curr))

    with t_news:
        if news:
            for item in news:
                title=item.get("title",""); link=item.get("link","#")
                ts=item.get("providerPublishTime",0); pub=item.get("publisher","")
                dt=datetime.fromtimestamp(ts).strftime("%b %d  %H:%M") if ts else ""
                st.markdown(f"""<div class="ncard">
                  <a href="{link}" target="_blank" style="color:#58a6ff;text-decoration:none;">
                    <div style="font-size:.87rem;font-weight:500;">{title}</div>
                  </a>
                  <div style="font-size:.7rem;color:#848e9c;margin-top:4px;">{pub} · {dt}</div>
                </div>""",unsafe_allow_html=True)
        else:
            st.info("No news found.")

# ── MOVERS ────────────────────────────────────────────────────────────────────
st.markdown("<hr style='border-color:#1e2329;margin:16px 0 10px;'>",unsafe_allow_html=True)
st.markdown("**📊 Indian Market Movers**")
moves=[(t.replace(".NS",""),*Q[t]) for _,t,_ in WL_IN if t in Q]
moves.sort(key=lambda x:x[3],reverse=True)
gc,lc=st.columns(2)
with gc:
    st.markdown("<div style='color:#0ecb81;font-weight:600;font-size:.82rem;margin-bottom:6px;'>▲ Top Gainers</div>",unsafe_allow_html=True)
    for sym,p,c,pct in moves[:4]:
        st.markdown(f"""<div style="background:#1e2329;border:1px solid #2b3139;border-radius:8px;
          padding:9px 14px;margin-bottom:5px;display:flex;justify-content:space-between;">
          <div style="font-size:.87rem;font-weight:600;color:#eaecef">{sym}</div>
          <div><div style="color:#eaecef;font-size:.85rem;font-weight:600;text-align:right">₹{p:,.2f}</div>
               <div style="color:#0ecb81;font-size:.75rem;text-align:right">▲ {abs(pct):.2f}%</div></div>
        </div>""",unsafe_allow_html=True)
with lc:
    st.markdown("<div style='color:#f6465d;font-weight:600;font-size:.82rem;margin-bottom:6px;'>▼ Top Losers</div>",unsafe_allow_html=True)
    for sym,p,c,pct in list(reversed(moves))[:4]:
        st.markdown(f"""<div style="background:#1e2329;border:1px solid #2b3139;border-radius:8px;
          padding:9px 14px;margin-bottom:5px;display:flex;justify-content:space-between;">
          <div style="font-size:.87rem;font-weight:600;color:#eaecef">{sym}</div>
          <div><div style="color:#eaecef;font-size:.85rem;font-weight:600;text-align:right">₹{p:,.2f}</div>
               <div style="color:#f6465d;font-size:.75rem;text-align:right">▼ {abs(pct):.2f}%</div></div>
        </div>""",unsafe_allow_html=True)
st.markdown("<div style='text-align:center;color:#848e9c;font-size:.7rem;margin-top:12px;'>⚠️ Educational only · Not financial advice · Yahoo Finance</div>",unsafe_allow_html=True)
