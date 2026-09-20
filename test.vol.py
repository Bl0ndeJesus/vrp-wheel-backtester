import numpy as np
import pandas as pd
import yfinance as yf
import math
from scipy.stats import norm

# 1. download 1 year of daily trading bars
raw_data = yf.download("MSTR", period="3y", interval="1d", progress=False)

# 2. Inspect the structure of what came back
df= pd.DataFrame({"Close": raw_data["Close"]["MSTR"]})

#3 Vectorize yesterday's close alongside today's close
df["Yesterday_Close"] = df["Close"].shift(1)

# 4. compute continuous logarithmic returns: ln(P_t / P_{t-1})
df["Log_Return"] = np.log(df["Close"] / df["Yesterday_Close"])

# 5. Drop the first row (since Day 1 has no 'Yesterday') and inspect
df_clean = df.dropna()
print(df_clean.head(5))

# 6. scale by sqrt(252) to annualize
df["RV_20"] = (
    df["Log_Return"].rolling(window=20).std(ddof=1) * math.sqrt(252)
)

#Inspect the last 5 days
print(df[["Close", "Log_Return", "RV_20"]].tail(5))

# 7. Model structural Implied Volatility (IV trades at an empirical premium to RV)
df["Modeled_IV"] = df["RV_20"] * 1.22

# 8. Compute the volatiility Risk Premium spread (IV - RV)
df["VRP_Spread"] = df["Modeled_IV"] - df["RV_20"]

# Inspect the most recent volatility regime
print(df[["Close", "RV_20", "Modeled_IV", "VRP_Spread"]].tail(5))

def black_scholes_put(
        S: float, K: float, T: float, sigma: float, r: float = 0.045
) -> float:
    """ Calculates the theoretical European put price using the analytical Black-Scholes formula."""
    # 1. Edge case safety: Zero time or zero volatility
    if T <= 0 or sigma <= 0:
        return max(0.0, K - S)

    # 2. Standardized distnace metrics (d1 and d2)
    d1 = (math.log(S / K) + (r +0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    # 3. Put the option analytical pricing equation
    put_price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return float(put_price)

def black_scholes_call(
        S: float, K: float, T: float, sigma: float, r: float = 0.045
) -> float:
    """ Calculates the theoretical European call price using the analytical Black-Scholes formula."""
    # 1. Edge case safety: Zero time or zero volatility
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K)

    # 2. Standardized distance metrics (d1 and d2)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    # 3. Call option analytical pricing equation
    call_price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return float(call_price)






# Test the pricer on the latest data row
latest_spot = df["Close"].iloc[-1]
latest_iv = df["Modeled_IV"].iloc[-1]

# Define a 30-calendar-day (21 trading days) put contract, 15% out-of-the-money
T = 21 /252.0
strike = latest_spot * 0.85

premium = black_scholes_put(
    S=latest_spot, K=strike, T=T, sigma=latest_iv, r=0.045
)
roc_pct = (premium / strike) * 100

print(f"\n--- Synthetic Cash Secrued Put Pricing Test ---")
print(f"Current Spot ($S$)     : ${latest_spot:.2f}")
print(f"Strike Price ($K$)     : ${strike:.2f} (15% OTM)")
print(f"Time to Exp ($T$)     : {T:.4f} years (~1 month)")
print(f"Implied Vol ($\\sigma$) : {latest_iv*100:.2f}%")
print(f"Theoretical Premium   : ${premium:.2f} per share")
print(f"Return on Collateral  : {roc_pct:.2f}% in 1 month")

# -----------------------------------------------------------------------------#

call_strike = latest_spot * 1.15

call_premium = black_scholes_call(
    S=latest_spot, K=call_strike, T=T, sigma=latest_iv, r=0.045
)
call_roc_pct = (call_premium / latest_spot) * 100.0

print(f"\n--- Synthetic Covered Call Pricing Test ---")
print(f"Current Spot ($S$)     : ${latest_spot:.2f}")
print(f"Call Strike ($K$)     : ${call_strike:.2f} (15% OTM)")
print(f"Theoretical Premium   : ${call_premium:.2f} per share")
print(f"Yield on Share Basis  : {call_roc_pct:.2f}% in 1 month")

# --- STEP 4: HISTORICAL SIMULATION ENGINE ---

# Strategy Parameters
HOLDING_DAYS = 21  # 21 trading days ≈ 1 calendar month
MIN_VRP = 0.12  # 12% minimum spread hurdle for put entry
OTM_PCT = 0.15  # 15% out-of-the-money buffer
RISK_FREE_RATE = 0.045
T = HOLDING_DAYS / 252.0

# 1. State Tracking Variables
portfolio_state = "CASH"  # State 0: "CASH", State 1: "LONG_ASSET"
cost_basis = 0.0
trades = []
in_trade_until_idx = -1

# Extract vectorized data arrays
dates = df.index
closes = df["Close"].values
vrp_spreads = df["VRP_Spread"].values
modeled_ivs = df["Modeled_IV"].values

total_bars = len(df)

for i in range(total_bars - HOLDING_DAYS):
    # Enforce capital lock until the active 21-day contract expires
    if i <= in_trade_until_idx:
        continue

    spot_entry = closes[i]
    iv = modeled_ivs[i]
    entry_date = dates[i].strftime("%Y-%m-%d")

    exit_idx = i + HOLDING_DAYS
    exit_date = dates[exit_idx].strftime("%Y-%m-%d")
    spot_exit = closes[exit_idx]

    # =========================================================================
    # STATE 0: CASH (SELLING CASH-SECURED PUTS)
    # =========================================================================
    if portfolio_state == "CASH":
        current_vrp = vrp_spreads[i]

        # Scan for entry signal: Is the Volatility Risk Premium wide enough?
        if current_vrp >= MIN_VRP:
            strike = spot_entry * (1.0 - OTM_PCT)
            premium = black_scholes_put(
                spot_entry, strike, T, iv, r=RISK_FREE_RATE
            )

            if spot_exit >= strike:
                # OTM Expiration: Keep 100% premium, stay in State 0
                pnl = premium
                roc_pct = (pnl / strike) * 100.0
                outcome = "WIN (PUT OTM)"
            else:
                # ITM Breach: Take delivery of shares, enter State 1
                # Initial cost basis = Strike paid minus upfront put premium collected
                cost_basis = strike - premium
                pnl = 0.0  # No realized cash loss; inventory acquired
                roc_pct = 0.0
                outcome = "ASSIGNED -> ENTER STATE 1"
                portfolio_state = "LONG_ASSET"

            trades.append(
                {
                    "Entry_Date": entry_date,
                    "Exit_Date": exit_date,
                    "State": "CASH (Put)",
                    "Spot_Entry": round(spot_entry, 2),
                    "Strike": round(strike, 2),
                    "Spot_Exit": round(spot_exit, 2),
                    "Premium": round(premium, 2),
                    "Cost_Basis": round(cost_basis, 2),
                    "PnL": round(pnl, 2),
                    "ROC_Pct": round(roc_pct, 2),
                    "Outcome": outcome,
                }
            )
            in_trade_until_idx = exit_idx

    # =========================================================================
    # STATE 1: LONG ASSET (SELLING COVERED CALLS)
    # =========================================================================
    elif portfolio_state == "LONG_ASSET":
        # Strike Selection: 15% above spot, but NEVER below cost basis
        target_strike = spot_entry * (1.0 + OTM_PCT)
        strike = max(target_strike, cost_basis)

        premium = black_scholes_call(
            spot_entry, strike, T, iv, r=RISK_FREE_RATE
        )

        # Harvesting call premium immediately drives down the effective cost basis
        cost_basis -= premium

        if spot_exit < strike:
            # OTM Expiration: Keep shares, keep premium, stay in State 1
            pnl = premium
            roc_pct = (premium / spot_entry) * 100.0
            outcome = "CALL OTM -> LOWERED BASIS"
        else:
            # ITM Assignment: Shares called away at strike price!
            # Total trade PnL = Strike price sold minus current cost basis
            pnl = strike - cost_basis
            roc_pct = (pnl / cost_basis) * 100.0
            outcome = "CALLED AWAY -> RESET TO CASH"
            portfolio_state = "CASH"
            cost_basis = 0.0

        trades.append(
            {
                "Entry_Date": entry_date,
                "Exit_Date": exit_date,
                "State": "LONG (Call)",
                "Spot_Entry": round(spot_entry, 2),
                "Strike": round(strike, 2),
                "Spot_Exit": round(spot_exit, 2),
                "Premium": round(premium, 2),
                "Cost_Basis": round(cost_basis, 2),
                "PnL": round(pnl, 2),
                "ROC_Pct": round(roc_pct, 2),
                "Outcome": outcome,
            }
        )
        in_trade_until_idx = exit_idx

# Convert to DataFrame and display all cycles
wheel_df = pd.DataFrame(trades)
print(f"\n--- Complete Wheel Backtest Ledger ---")
print(f"Total Completed Cycles: {len(wheel_df)}")
print(wheel_df.to_string(index=False))