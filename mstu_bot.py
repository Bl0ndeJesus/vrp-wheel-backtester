import yfinance as yf
import numpy as np
import pandas as pd
import math
from scipy.stats import norm
from datetime import datetime
import requests

# --- MSTU LEVERAGE CALIBRATIONS ---
TICKER = "MSTU"
MIN_VRP = 0.25
OTM_PCT = 0.25
HOLDING_DAYS = 21
RISK_FREE_RATE = 0.045
T = HOLDING_DAYS / 252.0

# Paste your webhook URL inside the quotes below
import os

# Try to get the webhook from GitHub Secrets, fallback to the hardcoded one for local testing
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1551079193108815924/tdey6478nNnw1_mUhZYacO0pzJqC9sm-Th6lZTml8Mlxqs9DwKQ5dmvBGyGcFOxF-JAZ")
def black_scholes_put(S, K, T, sigma, r):
    if T <= 0 or sigma <= 0: return max(0.0, K - S)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return float(K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1))

def send_discord_alert(message):
    if DISCORD_WEBHOOK_URL:
        payload = {"content": message}
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        
        # Optional: Print the server response so you know it actually went through
        if response.status_code == 204:
            print("✅ Discord Webhook delivered successfully.")
        else:
            print(f"⚠️ Discord Webhook failed with status code: {response.status_code}")

def run_daily_scan():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Pinging Yahoo Finance for live {TICKER} data...")
    
    raw = yf.download(TICKER, period="3mo", interval="1d", progress=False)
    
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
        
    df = pd.DataFrame(index=raw.index)
    df["Close"] = raw["Close"].squeeze().astype(float)
    df["Log_Return"] = np.log(df["Close"] / df["Close"].shift(1))
    df["RV_20"] = df["Log_Return"].rolling(window=20).std(ddof=1) * np.sqrt(252)
    
    df = df.dropna()
    latest_data = df.iloc[-1]
    
    spot_price = float(latest_data["Close"])
    rv_20 = float(latest_data["RV_20"])
    current_iv = rv_20 + 0.28 
    vrp = current_iv - rv_20
    strike = spot_price * (1.0 - OTM_PCT)
    theoretical_premium = black_scholes_put(spot_price, strike, T, current_iv, RISK_FREE_RATE)
    
    # Format the message for Discord
    discord_msg = f"**📊 Daily VRP Scan: {TICKER}**\n"
    discord_msg += f"Spot Price: `${spot_price:.2f}`\n"
    discord_msg += f"RV20: `{rv_20 * 100:.2f}%` | IV: `{current_iv * 100:.2f}%`\n"
    discord_msg += f"VRP Spread: `{vrp * 100:.2f}%`\n\n"

    if vrp >= MIN_VRP:
        discord_msg += f"🟢 **SIGNAL DETECTED (VRP > {MIN_VRP*100:.0f}%)**\n"
        discord_msg += f"**ACTION:** SELL {HOLDING_DAYS}-Day Put\n"
        discord_msg += f"**STRIKE:** `${strike:.2f}` (25% OTM)\n"
        discord_msg += f"**TARGET PREMIUM:** `${theoretical_premium:.2f}`"
    else:
        discord_msg += f"🔴 **NO SIGNAL** (VRP Hurdle not met. Hold cash.)"
        
    print(discord_msg) # Still print to terminal so you can see it
    send_discord_alert(discord_msg)
    print("Alert sent to Discord.")

if __name__ == "__main__":
    run_daily_scan()