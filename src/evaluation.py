import pandas as pd
import numpy as np

def compute_returns(df: pd.DataFrame, price_col: str = "close") -> pd.Series:
    px = df[price_col].astype(float)
    ret = px.pct_change().fillna(0.0)
    return ret

def apply_signals_to_returns(returns: pd.Series, signals: pd.Series, cost_bps: float = 1.0) -> pd.Series:
    """Position returns with simple cost model.
    - signals in {-1,0,+1} (position for *next* bar)
    - transaction cost applied on signal *changes* (in basis points)
    """
    signals = signals.reindex(returns.index).fillna(0).astype(float)
    pos = signals.shift(1).fillna(0.0)  # enter next bar
    strat_ret = pos * returns

    # transaction cost on changes in position (turnover)
    turnover = (signals.diff().abs().fillna(0.0))
    costs = turnover * (cost_bps / 10000.0)
    strat_ret_after_cost = strat_ret - costs
    return strat_ret_after_cost

def sharpe(returns: pd.Series, periods_per_year: int = 252*24, eps: float = 1e-12) -> float:
    # hourly -> approx 252 trading days * 24 hours
    mu = returns.mean() * periods_per_year
    sigma = returns.std(ddof=1) * np.sqrt(periods_per_year)
    if not np.isfinite(sigma) or sigma < eps:
        return 0.0
    return float(mu / sigma)

def max_drawdown(cum_returns: pd.Series) -> float:
    if cum_returns.empty:
        return 0.0
    roll_max = cum_returns.cummax()
    with np.errstate(divide='ignore', invalid='ignore'):
        dd = cum_returns / roll_max - 1.0
    dd = dd.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return float(dd.min())

def evaluate(signals: pd.Series, df: pd.DataFrame, price_col: str = "close", cost_bps: float = 1.0) -> dict:
    ret = compute_returns(df, price_col=price_col)
    aligned_signals = signals.reindex(ret.index).fillna(0.0)
    strat = apply_signals_to_returns(ret, aligned_signals, cost_bps=cost_bps).fillna(0.0)
    cum = (1.0 + strat).cumprod()

    ann_return = float((cum.iloc[-1] ** (252 * 24 / len(cum)) - 1.0)) if len(cum) > 0 else 0.0
    vol = strat.std(ddof=1)
    if not np.isfinite(vol):
        vol = 0.0
    ann_vol = float(vol * np.sqrt(252 * 24))
    sharpe_ratio = sharpe(strat)
    drawdown = max_drawdown(cum)
    total_return = float(cum.iloc[-1] - 1.0) if len(cum) > 0 else 0.0
    turnover = float(aligned_signals.diff().abs().fillna(0.0).sum())

    metrics = {
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "sharpe": sharpe_ratio,
        "max_drawdown": drawdown,
        "total_return": total_return,
        "turnover": turnover
    }
    metrics["score"] = metrics["sharpe"]
    return metrics
