# Volatility Risk Premium (VRP) Harvesting Engine & Wheel State Machine

## Executive Summary
This repository contains a discrete-time, path-dependent quantitative backtesting engine designed to harvest the Volatility Risk Premium (VRP). The system algorithmically underwrites variance (selling options) on MicroStrategy (`MSTR`) as a deep-history proxy for the 2x-leveraged ETF `MSTU`. 

Instead of relying on directional price prediction, the strategy generates alpha by systematically exploiting the spread between Implied Volatility ($\sigma_{IV}$) and Realized Volatility ($\sigma_{RV}$). To defend against secular market drawdowns, the core execution engine utilizes a Finite State Machine (FSM) to transition from cash-secured put selling into a cost-basis-floor Covered Call protocol (The Wheel), effectively transforming realized crash losses into active inventory management.

## The Quantitative Edge

### 1. Volatility Risk Premium (VRP) Hurdle
The algorithm does not blindly sell theta. Trades are strictly gated by a positive expected value ($+EV$) statistical hurdle:
$$\text{VRP Spread} = \sigma_{IV} - \sigma_{RV} \ge 0.12$$
*   **Realized Volatility ($\sigma_{RV}$):** Calculated using continuous log returns ($\ln(S_t / S_{t-1})$) over a 20-trading-day rolling window, annualized, and adjusted with Bessel's correction (`ddof=1`) to eliminate sample variance bias.
*   **Implied Volatility ($\sigma_{IV}$):** Option market pricing for forward-looking variance. 

### 2. Analytical Black-Scholes Pricing
Contract premiums are priced dynamically using the European Black-Scholes analytical formula. 
*   Time to maturity is strictly annualized by trading days ($T = \frac{21}{252}$) rather than calendar days to properly align continuous diffusion assumptions with equity market hours.
*   Risk-free collateral yield ($r = 0.045$) is incorporated to discount forward asset prices accurately.

## The Finite State Machine (Execution Architecture)

Retail backtesters evaluate trades in a vacuum, leading to inaccurate liquidations. This engine employs path dependency, tracking `portfolio_state` and continuous `cost_basis`.

### State 0: Cash (Short Variance)
*   **Action:** Sells 15% out-of-the-money puts when the VRP hurdle is cleared.
*   **Settlement:** If the put expires in-the-money (breached), the algorithm *does not* realize a liquidation loss. It models institutional inventory acquisition. 
*   **Transition:** `Cost Basis = Strike - Premium Collected`. Switches to **State 1**.

### State 1: Long Asset (Inventory Defense)
*   **Action:** Writes covered calls against the assigned inventory. 
*   **The Quantitative Floor:** To prevent whipsaw permanent capital loss during a rebound, the call strike ($K_{call}$) uses a strict boundary condition:
    $$K_{call} = \max(\text{Spot} \times 1.15, \text{Cost Basis})$$
*   **Continuous Decay:** Every premium harvested lowers the effective cost basis ($\text{Cost Basis}_{t+1} = \text{Cost Basis}_t - \text{Premium}$). If the stock breaches the call strike, shares are called away for a localized capital gain, and the system reverts to **State 0**.

## Known Structural Limitations & Future Architecture

This v1.0 backtest intentionally runs on a rigid, discrete 21-day evaluation jump to establish a baseline performance benchmark. Stress testing across 3 years of macro data revealed the primary strategy vulnerability during deep secular drawdowns (e.g., Mid-2026):

*   **The Capital Lockup Trap:** When the asset drops $>2\sigma$ below the cost basis, the $\max()$ strike floor forces the engine to write deep OTM calls with near-zero Delta, effectively halting premium generation and locking collateral.
*   **Next-Generation Deployment (v2.0):** The upcoming live-execution risk tool for `MSTU` will transition from discrete jumps to a **Daily Path Evaluation Engine**. This unlocks two critical institutional defense mechanisms:
    1.  **Adaptive Delta Overrides:** Writing numerical 0.20 Delta calls when stranded below basis, paired with upside long-call hedges (bear credit spreads) to defend against whipsaw rips.
    2.  **200% Stop-Loss Buyback Protocol:** Executing immediate short-option buybacks if the underlying asset goes parabolic before expiration, absorbing a contained options loss while letting the underlying equity ride uncapped.

---
**Author:** Joseph Hickson  
**Institution:** University of Wisconsin–Madison | Wisconsin School of Business  
*Developed for Traders at Wisconsin quantitative interview presentation.*