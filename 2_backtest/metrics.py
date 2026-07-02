"""Metricas, curva de equity, drawdown, Monte Carlo y simulacion prop-firm."""
import numpy as np
import pandas as pd


def metrics(R: pd.Series) -> dict:
    R = pd.Series(R).dropna().astype(float)
    n = len(R)
    if n == 0:
        return dict(n=0)
    wins = R[R > 0]; losses = R[R < 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
    eq = R.cumsum()
    peak = eq.cummax(); dd = eq - peak
    # Sharpe por-trade anualizado (aprox; ~252*? trades/ano se ajusta afuera)
    sharpe = R.mean() / R.std() if R.std() > 0 else 0.0
    return dict(
        n=n,
        expectancy_R=round(R.mean(), 4),
        winrate=round((R > 0).mean(), 4),
        avg_win=round(wins.mean(), 3) if len(wins) else 0.0,
        avg_loss=round(losses.mean(), 3) if len(losses) else 0.0,
        profit_factor=round(pf, 3),
        sum_R=round(R.sum(), 1),
        sharpe_per_trade=round(sharpe, 4),
        max_dd_R=round(dd.min(), 1),
        ret_dd=round(R.sum() / abs(dd.min()), 2) if dd.min() < 0 else np.inf,
    )


def equity_dd(R):
    eq = pd.Series(R).cumsum()
    dd = eq - eq.cummax()
    return eq, dd


def mc_bootstrap(R, n_paths=5000, seed=7):
    """Monte Carlo por remuestreo (bootstrap) de la secuencia de trades.
    Devuelve distribuciones de PnL final y max drawdown (en R)."""
    rng = np.random.default_rng(seed)
    R = np.asarray(R, float); n = len(R)
    finals = np.empty(n_paths); maxdd = np.empty(n_paths)
    for k in range(n_paths):
        s = rng.choice(R, size=n, replace=True)
        eq = np.cumsum(s)
        finals[k] = eq[-1]
        maxdd[k] = (eq - np.maximum.accumulate(eq)).min()
    pct = lambda a, q: round(float(np.percentile(a, q)), 1)
    return dict(
        final_p5=pct(finals, 5), final_p50=pct(finals, 50), final_p95=pct(finals, 95),
        final_mean=round(float(finals.mean()), 1),
        prob_final_neg=round(float((finals < 0).mean()), 4),
        maxdd_p50=pct(maxdd, 50), maxdd_p95=pct(maxdd, 5), maxdd_worst=round(float(maxdd.min()), 1),
        _finals=finals, _maxdd=maxdd,
    )


def prop_firm_sim(R, risk_per_trade=0.005, trades_per_day=2,
                  profit_target=0.08, daily_loss=0.05, max_dd=0.10,
                  start=1.0, n_paths=5000, seed=11, max_days=60):
    """Simula la regla de una prop firm (estilo HyroTrader) por Monte Carlo.
    risk_per_trade: fraccion de la cuenta arriesgada por trade (R=1 -> pierde esto).
    Devuelve prob de PASAR (llegar a profit_target sin violar daily_loss ni max_dd).
    """
    rng = np.random.default_rng(seed)
    R = np.asarray(R, float)
    passed = busted_daily = busted_dd = timeout = 0
    days_to_pass = []
    for k in range(n_paths):
        bal = start; peak = start; alive = True
        for day in range(max_days):
            day_start = bal
            day_pnl = 0.0
            for _ in range(trades_per_day):
                r = rng.choice(R)
                bal += risk_per_trade * r * day_start   # riesgo fijo sobre balance del dia
                day_pnl += risk_per_trade * r
                peak = max(peak, bal)
                # max drawdown (trailing desde pico)
                if (peak - bal) / start >= max_dd:
                    busted_dd += 1; alive = False; break
            if not alive: break
            # daily loss limit
            if (day_start - bal) / start >= daily_loss:
                busted_daily += 1; alive = False; break
            if (bal - start) / start >= profit_target:
                passed += 1; days_to_pass.append(day + 1); alive = False; break
        if alive:
            timeout += 1
    return dict(
        prob_pass=round(passed / n_paths, 4),
        prob_bust_daily=round(busted_daily / n_paths, 4),
        prob_bust_maxdd=round(busted_dd / n_paths, 4),
        prob_timeout=round(timeout / n_paths, 4),
        median_days_to_pass=int(np.median(days_to_pass)) if days_to_pass else None,
    )
