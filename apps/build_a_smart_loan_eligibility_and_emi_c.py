import streamlit as st
import pandas as pd
import numpy as np
import altair as alt

st.set_page_config(page_title="Loan Eligibility & EMI Calculator", page_icon="🏦", layout="wide")

# ── Styling ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.result-card {
    background: #f0fdf4; border: 2px solid #86efac;
    border-radius: 14px; padding: 20px; text-align: center;
}
.reject-card {
    background: #fef2f2; border: 2px solid #fca5a5;
    border-radius: 14px; padding: 20px; text-align: center;
}
</style>
""", unsafe_allow_html=True)

st.title("🏦 Smart Loan Eligibility & EMI Calculator")
st.caption("Get instant loan eligibility assessment and full EMI breakdown")

# ── Input form ────────────────────────────────────────────────────────────────
with st.form("loan_form"):
    st.subheader("📋 Your Financial Profile")
    c1, c2 = st.columns(2)
    with c1:
        income          = st.number_input("Monthly Income (₹)", min_value=0, value=80000, step=1000)
        existing_debts  = st.number_input("Existing Monthly Debts (₹)", min_value=0, value=5000, step=500)
        credit_score    = st.slider("Credit Score", 300, 900, 720)
    with c2:
        employment_type = st.selectbox("Employment Type",
                                       ["Salaried", "Self-Employed", "Business Owner", "Freelancer"])
        loan_amount     = st.number_input("Requested Loan Amount (₹)", min_value=10000, value=500000, step=10000)
        loan_tenure_yrs = st.slider("Loan Tenure (years)", 1, 30, 5)

    submitted = st.form_submit_button("🔍 Check Eligibility & Calculate EMI",
                                      use_container_width=True, type="primary")

if submitted:
    # ── Eligibility logic ──────────────────────────────────────────────────────
    dti         = (existing_debts / income * 100) if income > 0 else 100   # debt-to-income %
    max_emi_cap = income * 0.50                                              # 50% EMI cap

    # Interest rate by employment + credit score
    base_rate = {"Salaried": 8.5, "Self-Employed": 9.5,
                 "Business Owner": 10.0, "Freelancer": 11.0}.get(employment_type, 10.0)
    if credit_score >= 750:   rate = base_rate - 0.5
    elif credit_score >= 700: rate = base_rate
    elif credit_score >= 650: rate = base_rate + 1.0
    elif credit_score >= 600: rate = base_rate + 2.5
    else:                     rate = base_rate + 4.0

    monthly_rate  = rate / 12 / 100
    n             = loan_tenure_yrs * 12
    if monthly_rate > 0:
        emi = loan_amount * monthly_rate * (1 + monthly_rate)**n / ((1 + monthly_rate)**n - 1)
    else:
        emi = loan_amount / n

    total_payment  = emi * n
    total_interest = total_payment - loan_amount
    max_loan       = max_emi_cap * ((1 + monthly_rate)**n - 1) / (monthly_rate * (1 + monthly_rate)**n) if monthly_rate > 0 else max_emi_cap * n

    # Eligibility rules
    eligible = (
        credit_score >= 600
        and dti <= 40
        and emi <= max_emi_cap
        and income >= 20000
    )
    reasons = []
    if credit_score < 600:     reasons.append(f"Credit score {credit_score} below minimum (600)")
    if dti > 40:               reasons.append(f"Debt-to-income ratio {dti:.1f}% exceeds 40%")
    if emi > max_emi_cap:      reasons.append(f"EMI ₹{emi:,.0f} exceeds 50% income cap ₹{max_emi_cap:,.0f}")
    if income < 20000:         reasons.append(f"Monthly income ₹{income:,} below minimum ₹20,000")

    # Risk category
    if credit_score >= 750 and dti <= 20:   risk = "Low Risk 🟢"
    elif credit_score >= 650 and dti <= 35: risk = "Medium Risk 🟡"
    else:                                   risk = "High Risk 🔴"

    # ── Results ────────────────────────────────────────────────────────────────
    st.divider()

    if eligible:
        st.markdown(f"""
        <div class="result-card">
            <div style="font-size:2rem;">✅</div>
            <div style="font-size:1.4rem;font-weight:800;color:#166534;margin:8px 0;">LOAN APPROVED</div>
            <div style="color:#15803d;">You qualify for this loan. Risk: {risk}</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="reject-card">
            <div style="font-size:2rem;">❌</div>
            <div style="font-size:1.4rem;font-weight:800;color:#991b1b;margin:8px 0;">NOT ELIGIBLE</div>
            <div style="color:#b91c1c;">{'  |  '.join(reasons)}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── KPI strip ─────────────────────────────────────────────────────────────
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Monthly EMI",      f"₹{emi:,.0f}")
    m2.metric("Interest Rate",    f"{rate:.2f}%")
    m3.metric("Total Interest",   f"₹{total_interest:,.0f}")
    m4.metric("Total Payment",    f"₹{total_payment:,.0f}")
    m5.metric("Max Loan Eligible",f"₹{max_loan:,.0f}")

    st.divider()

    # ── Amortisation chart ────────────────────────────────────────────────────
    st.subheader("📈 Amortisation Schedule")
    balance, rows = loan_amount, []
    for month in range(1, n + 1):
        interest_part  = balance * monthly_rate
        principal_part = emi - interest_part
        balance        = max(balance - principal_part, 0)
        rows.append({"Month": month, "Principal": round(principal_part, 2),
                     "Interest": round(interest_part, 2), "Balance": round(balance, 2)})

    df = pd.DataFrame(rows)

    tab1, tab2 = st.tabs(["📊 Balance Over Time", "📋 Full Schedule"])
    with tab1:
        bal_chart = alt.Chart(df).mark_area(opacity=0.7, color="#4f46e5").encode(
            x=alt.X("Month:Q", title="Month"),
            y=alt.Y("Balance:Q", title="Outstanding Balance (₹)"),
            tooltip=["Month","Balance","Principal","Interest"],
        ).properties(height=320)
        st.altair_chart(bal_chart, use_container_width=True)

        # Principal vs Interest bar (yearly)
        df["Year"] = ((df["Month"] - 1) // 12) + 1
        yearly = df.groupby("Year")[["Principal","Interest"]].sum().reset_index()
        yearly_melt = yearly.melt("Year", var_name="Type", value_name="Amount")
        bar2 = alt.Chart(yearly_melt).mark_bar().encode(
            x="Year:O", y="Amount:Q",
            color=alt.Color("Type:N", scale=alt.Scale(
                domain=["Principal","Interest"], range=["#4f46e5","#f97316"])),
            tooltip=["Year","Type","Amount"],
        ).properties(height=280, title="Yearly Principal vs Interest")
        st.altair_chart(bar2, use_container_width=True)

    with tab2:
        st.dataframe(df[["Month","Principal","Interest","Balance"]].style.format({
            "Principal": "₹{:,.0f}", "Interest": "₹{:,.0f}", "Balance": "₹{:,.0f}"
        }), use_container_width=True, hide_index=True)
