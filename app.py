import math
import numpy as np
import pandas as pd
import plotly.express as px
from scipy.stats import norm
import streamlit as st
import yfinance as yf

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="VRP Wheel Backtester", layout="wide")
st.title("Volatility Risk Premium (VRP) & Wheel State Machine")
st.markdown("Developed for MicroStrategy (MSTR) as a proxy for leveraged BTC equities.")

# --- SIDEBAR PARAMETERS ---
st.sidebar.header("Strategy Parameters")
MIN_VRP = st.sidebar.slider("Min VRP Hurdle (Spread)", min_value=0.0, max_value=0.50, value=0.12, step=0.01)
OTM_PCT = st.sidebar.slider("Out-of-The-Money % (Strike)", min_value=0.05, max_value=0.30, value=0.15, step=0.01)
HOLDING_DAYS = st.sidebar.slider("Holding Period (Trading Days)", min_value=5, max_value=45, value=21, step=1)
RISK_FREE_RATE = 0.045
T = HOLDING_DAYS / 252.0

# --- DATA ENGINE (Cached for speed) ---
@st.cache_data
def load_data():
    raw = yf.download("MSTR", period="3y", interval="1d", progress=False)

    # Flatten yfinance MultiIndex columns if present
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    # Build clean dataframe and force native floats
    df = pd.DataFrame(index=raw.index)
    df["Close"] = raw["Close"].squeeze().astype(float)
    df["Log_Return"] = np.log(df["Close"] / df["Close"].shift(1))
    df["RV_20"] = df["Log_Return"].rolling(window=20).std(ddof=1) * np.sqrt(252)
    df["Modeled_IV"] = df["RV_20"] + 0.22  # Synthetic baseline IV buffer
    df["VRP_Spread"] = df["Modeled_IV"] - df["RV_20"]
    return df.dropna()

df = load_data()

# --- PRICING ENGINES ---
def black_scholes_put(S, K, T, sigma, r):
    if T <= 0 or sigma <= 0: return max(0.0, K - S)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return float(K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1))

def black_scholes_call(S, K, T, sigma, r):
    if T <= 0 or sigma <= 0: return max(0.0, S - K)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return float(S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2))

# --- FINITE STATE MACHINE LOOP ---
portfolio_state = "CASH"
cost_basis = 0.0
trades = []
in_trade_until_idx = -1

dates = df.index
closes = df["Close"].values
vrp_spreads = df["VRP_Spread"].values
modeled_ivs = df["Modeled_IV"].values
total_bars = len(df)

for i in range(total_bars - HOLDING_DAYS):
    if i <= in_trade_until_idx:
        continue

    # Force extraction as standard Python floats to prevent numpy scalar crashes
    spot_entry = float(closes[i])
    iv = float(modeled_ivs[i])
    exit_idx = i + HOLDING_DAYS
    spot_exit = float(closes[exit_idx])

    if portfolio_state == "CASH":
        if vrp_spreads[i] >= MIN_VRP:
            strike = spot_entry * (1.0 - OTM_PCT)
            premium = black_scholes_put(spot_entry, strike, T, iv, RISK_FREE_RATE)

            if spot_exit >= strike:
                pnl = premium
                outcome = "WIN (PUT OTM)"
            else:
                cost_basis = strike - premium
                pnl = 0.0
                outcome = "ASSIGNED -> STATE 1"
                portfolio_state = "LONG_ASSET"

            trades.append({"Date": dates[exit_idx], "State": "CASH (Put)", "Spot_Entry": spot_entry, "Strike": strike, "Premium": premium, "Cost_Basis": (cost_basis if portfolio_state == "LONG_ASSET" else 0.0), "PnL": pnl, "Outcome": outcome})
            in_trade_until_idx = exit_idx

    elif portfolio_state == "LONG_ASSET":
        strike = max(spot_entry * (1.0 + OTM_PCT), cost_basis)
        premium = black_scholes_call(spot_entry, strike, T, iv, RISK_FREE_RATE)
        cost_basis -= premium

        if spot_exit < strike:
            pnl = premium
            outcome = "CALL OTM -> LOWERED BASIS"
        else:
            pnl = strike - cost_basis
            outcome = "CALLED AWAY -> RESET TO CASH"
            portfolio_state = "CASH"
            cost_basis = 0.0

        trades.append({"Date": dates[exit_idx], "State": "LONG (Call)", "Spot_Entry": spot_entry, "Strike": strike, "Premium": premium, "Cost_Basis": cost_basis, "PnL": pnl, "Outcome": outcome})
        in_trade_until_idx = exit_idx

# --- DASHBOARD VISUALIZATION ---
if trades:
    trade_df = pd.DataFrame(trades)
    trade_df["Cumulative_PnL"] = trade_df["PnL"].cumsum()

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Trades Executed", len(trade_df))
    col2.metric("Cumulative PnL (per share)", f"${trade_df['Cumulative_PnL'].iloc[-1]:.2f}")
    col3.metric("Cycles in Wheel Defense", len(trade_df[trade_df["State"] == "LONG (Call)"]))

    st.subheader("Cumulative Strategy PnL")
    fig = px.line(trade_df, x="Date", y="Cumulative_PnL", title="Wheel State Machine Equity Curve", markers=True)
    st.plotly_chart(fig, width="stretch")

    st.subheader("Trade Ledger")
    st.dataframe(
        trade_df.style.format({"Spot_Entry": "${:.2f}", "Strike": "${:.2f}", "Premium": "${:.2f}", "Cost_Basis": "${:.2f}", "PnL": "${:.2f}", "Cumulative_PnL": "${:.2f}"}),
        width="stretch"
    )
else:
    st.warning("No trades triggered. Try lowering the MIN_VRP hurdle.")