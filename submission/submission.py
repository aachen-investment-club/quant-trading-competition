from __future__ import annotations
import numpy as np
import pandas as pd

# The starter kit exposes this interface; if your path differs, adjust the import.
from src.interfaces import Strategy
from src.features import sma  # simple moving average helper


# ---------- Feature engineering utilities ----------
def _safe_pct_change(s: pd.Series, periods: int = 1) -> pd.Series:
    return s.astype(float).pct_change(periods=periods).replace([np.inf, -np.inf], np.nan).fillna(0.0)

def _rolling_zscore(s: pd.Series, window: int) -> pd.Series:
    r = s.rolling(window)
    mean = r.mean()
    std = r.std(ddof=0).replace(0, np.nan)
    return (s - mean) / std

def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    up = (delta.clip(lower=0)).ewm(alpha=1/window, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/window, adjust=False).mean()
    rs = up / (down.replace(0, np.nan))
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)

def _atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    close = df["close"].astype(float)
    high = df["high"].astype(float) if "high" in df else close
    low = df["low"].astype(float) if "low" in df else close
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window).mean().bfill()


# ===================================================
# 1) RULE-BASED STRATEGY (SMA crossover + ATR filter)
# ===================================================
class SmaAtrStrategy(Strategy):
    """
    Long when fast SMA > slow SMA and volatility (ATR) is not extremely high.
    Flat when they’re close (dead zone) or ATR too high.
    Short when fast < slow (symmetrically).
    """

    def __init__(self, fast: int = 10, slow: int = 50, atr_win: int = 14, z_dead: float = 0.25, atr_cap: float = 0.01):
        self.fast = fast
        self.slow = slow
        self.atr_win = atr_win
        self.z_dead = z_dead
        self.atr_cap = atr_cap  # cap as fraction of price (e.g., 1%)

    def fit(self, df: pd.DataFrame) -> None:
        # Nothing to fit for rules-based; keep last price for ATR normalization
        self._last_price = float(df["close"].iloc[-1])

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        px = df["close"].astype(float)
        fast_sma = sma(px, self.fast)
        slow_sma = sma(px, self.slow)
        spread = fast_sma - slow_sma
        z = _rolling_zscore(spread, window=self.slow).fillna(0.0)

        atr_abs = _atr(df, self.atr_win)
        # normalize ATR by price level
        atr_norm = (atr_abs / px).fillna(0.0)

        # dead-zone around zero to reduce churn
        raw = np.where(z > self.z_dead, 1, np.where(z < -self.z_dead, -1, 0))

        # suppress positions when volatility is too high
        raw = np.where(atr_norm > self.atr_cap, 0, raw)

        sig = pd.Series(raw, index=df.index, name="signal").astype(int)
        # evaluator applies the next-bar execution lag, so emit current-bar intent
        return sig


# ===================================================
# 2) ML STRATEGY (Logistic Regression on handcrafted features)
# ===================================================
class MLLogitStrategy(Strategy):
    """
    Binary classifier predicts next-bar up/down using simple price-derived features.
    Outputs {-1, 0, 1} with confidence thresholds to reduce churn.
    """

    def __init__(self, up_th: float = 0.55, dn_th: float = 0.45, lookahead: int = 1, seed: int = 42):
        # thresholds on predicted probability of "up"
        self.up_th = up_th
        self.dn_th = dn_th
        self.lookahead = lookahead
        self.seed = seed
        self._clf = None
        self._scaler = None
        self._feature_cols = None
        self._const_proba = 0.5

    def _make_features(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        ret1 = _safe_pct_change(close, 1)
        ret2 = _safe_pct_change(close, 2)
        ret5 = _safe_pct_change(close, 5)
        mom5 = close / close.shift(5) - 1.0
        vol10 = _safe_pct_change(close, 1).rolling(10).std().fillna(0.0)
        z20 = _rolling_zscore(close, 20).fillna(0.0)
        rsi14 = _rsi(close, 14)
        fast = sma(close, 10)
        slow = sma(close, 50)
        x = pd.DataFrame({
            "ret1": ret1,
            "ret2": ret2,
            "ret5": ret5,
            "mom5": mom5.fillna(0.0),
            "vol10": vol10,
            "z20": z20,
            "rsi14": rsi14,
            "sma10_minus_50": (fast - slow) / close.replace(0, np.nan),
        }, index=df.index).replace([np.inf, -np.inf], 0.0).fillna(0.0)
        return x

    def fit(self, df: pd.DataFrame) -> None:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        x = self._make_features(df)
        y = (df["close"].shift(-self.lookahead) > df["close"]).astype(int)  # next-bar up?
        mask = y.notna()
        x_train, y_train = x[mask], y[mask].astype(int)
        self._feature_cols = x.columns.tolist()

        if x_train.empty:
            self._clf = None
            self._scaler = None
            self._const_proba = 0.5
            return

        scaler = StandardScaler()
        x_train_scaled = scaler.fit_transform(x_train)

        if len(np.unique(y_train)) < 2:
            self._clf = None
            self._scaler = scaler
            self._const_proba = 0.5
            return

        clf = LogisticRegression(
            penalty="l2",
            C=1.0,
            solver="lbfgs",
            max_iter=1000,
            random_state=self.seed,
            n_jobs=None
        )
        try:
            clf.fit(x_train_scaled, y_train.values)
        except ValueError:
            self._clf = None
            self._scaler = scaler
            self._const_proba = 0.5
            return

        self._clf = clf
        self._scaler = scaler
        self._const_proba = None

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        if self._feature_cols is None:
            self.fit(df)
        if self._feature_cols is None:
            raise RuntimeError("Call fit() before generate_signals().")

        x = self._make_features(df)[self._feature_cols]
        if self._clf is not None:
            x_scaled = self._scaler.transform(x)
            proba_up = pd.Series(self._clf.predict_proba(x_scaled)[:, 1], index=df.index)
        else:
            proba_up = pd.Series(self._const_proba, index=df.index, dtype=float)

        sig = pd.Series(0, index=df.index, dtype=int)
        sig[proba_up > self.up_th] = 1
        sig[proba_up < self.dn_th] = -1
        sig.name = "signal"
        return sig


# ===================================================
# 3) SIMPLE COMBINER (optional)
#    Averages ML and SMA signals; keeps 0 if they disagree.
# ===================================================
class CombinedStrategy(Strategy):
    def __init__(self, ml: Strategy, rules: Strategy):
        self.ml = ml
        self.rules = rules

    def fit(self, df: pd.DataFrame) -> None:
        if hasattr(self.ml, "fit"):
            self.ml.fit(df)
        if hasattr(self.rules, "fit"):
            self.rules.fit(df)

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        s1 = self.ml.generate_signals(df).astype(int)
        s2 = self.rules.generate_signals(df).astype(int)
        # If both agree -> trade; if they disagree -> flat; if one is flat -> take the other.
        combined = np.where(s1 == s2, s1, np.where(s1 == 0, s2, np.where(s2 == 0, s1, 0)))
        return pd.Series(combined, index=df.index, name="signal").astype(int)


# Factory for the evaluator
def build_strategy() -> Strategy:
    """
    Return the strategy the evaluator should use.
    Choose one of:
      - SmaAtrStrategy()
      - MLLogitStrategy()
      - CombinedStrategy(MLLogitStrategy(), SmaAtrStrategy())
    """
    # Choose the combined model for a stronger baseline:
    return CombinedStrategy(MLLogitStrategy(up_th=0.55, dn_th=0.45),
                            SmaAtrStrategy(fast=10, slow=50, atr_win=14, z_dead=0.20, atr_cap=0.015))
