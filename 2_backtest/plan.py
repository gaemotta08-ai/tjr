"""Simulacion Monte Carlo del PLAN EJECUTADO: forward test -> challenge 2-step
(reglas estilo HyroTrader) -> cuenta fondeada -> primer payout.
Usa la distribucion de R REAL del backtest de NQ (edge validado).
Responde: despues de cuanto tiempo hay primer payout.
"""
import numpy as np, pandas as pd

R = pd.read_csv("out/trades_NQ.csv")["R"].values  # edge validado NQ

# --- Reglas HyroTrader (de memoria del usuario) ---
P1_TARGET   = 0.10     # fase 1: +10%
P2_TARGET   = 0.05     # fase 2: +5%
DAILY_LOSS  = 0.05     # DD diario 5%
MAX_DD      = 0.10     # DD total 10% (trailing desde el pico)
CONSISTENCY = 0.40     # ningun dia > 40% del profit total
# Funded: supuestos razonables (ajustar a la firma)
FUNDED_PAYOUT_PROFIT = 0.05   # primer retiro al llegar a +5% en la fondeada
FUNDED_MIN_DAYS      = 14      # minimo de dias operados antes del 1er retiro
PROFIT_SPLIT         = 0.80    # 80% para el trader

TRADES_PER_DAY = 2
TRADING_DAYS_MONTH = 21
FORWARD_TEST_WEEKS = 8         # gate previo (calendario fijo, no se simula PnL)


def sim_phase(rng, target, risk, consistency=True, max_days=400):
    """Opera dias hasta llegar al target o reventar. Devuelve (dias, resultado)."""
    bal = 1.0; peak = 1.0; best_day = 0.0; profit = 0.0
    for day in range(1, max_days + 1):
        day0 = bal
        for _ in range(TRADES_PER_DAY):
            bal += risk * float(rng.choice(R)) * day0   # riesgo fijo sobre balance del dia
            peak = max(peak, bal)
            if (peak - bal) >= MAX_DD:
                return day, "bust_dd"
        day_pnl = bal - day0
        best_day = max(best_day, day_pnl)
        if (day0 - bal) >= DAILY_LOSS:
            return day, "bust_daily"
        profit = bal - 1.0
        if profit >= target:
            # regla de consistencia 40%: el mejor dia no puede ser > 40% del profit
            if (not consistency) or (best_day <= CONSISTENCY * profit):
                return day, "pass"
            # si rompe consistencia, sigue operando para diluir ese dia
    return max_days, "timeout"


def sim_plan(risk, n_paths=20000, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n_paths):
        d1, r1 = sim_phase(rng, P1_TARGET, risk)
        if r1 != "pass":
            rows.append((r1, d1, None, None)); continue
        d2, r2 = sim_phase(rng, P2_TARGET, risk)
        if r2 != "pass":
            rows.append((r2, d1 + d2, None, None)); continue
        # fondeada: operar hasta primer payout (profit + min dias), respetando DD
        df, rf = sim_phase(rng, FUNDED_PAYOUT_PROFIT, risk, consistency=False)
        if rf != "pass":
            rows.append(("bust_funded", d1 + d2 + df, None, None)); continue
        dfund = max(df, FUNDED_MIN_DAYS)
        rows.append(("payout", d1 + d2 + dfund, d1 + d2, dfund))
    return rows


def summarize(rows, risk):
    n = len(rows)
    payout = [r for r in rows if r[0] == "payout"]
    p_pass_p1 = sum(1 for r in rows if r[1] is not None and r[0] not in ("bust_dd", "bust_daily") or r[0] == "payout")
    # contadores por resultado final
    from collections import Counter
    c = Counter(r[0] for r in rows)
    prob_payout = len(payout) / n
    days_total = np.array([r[1] for r in payout]) if payout else np.array([np.nan])
    def wk(d): return d / 5.0  # dias operativos -> semanas calendario (5 dias/sem)
    res = dict(
        risk=f"{risk:.2%}",
        prob_llega_a_payout=round(prob_payout, 3),
        prob_revienta=round(sum(v for k, v in c.items() if k.startswith("bust")) / n, 3),
        sem_total_p50=round(FORWARD_TEST_WEEKS + wk(np.nanpercentile(days_total, 50)), 1),
        sem_total_p25=round(FORWARD_TEST_WEEKS + wk(np.nanpercentile(days_total, 25)), 1),
        sem_total_p75=round(FORWARD_TEST_WEEKS + wk(np.nanpercentile(days_total, 75)), 1),
        sem_challenge_a_payout_p50=round(wk(np.nanpercentile(days_total, 50)), 1),
    )
    return res, c


if __name__ == "__main__":
    print(f"Edge NQ: expectancy={R.mean():.3f}R, winrate={(R>0).mean():.1%}, n={len(R)}")
    print(f"Forward test previo: {FORWARD_TEST_WEEKS} semanas (gate)")
    print(f"Reglas: P1 +10%, P2 +5%, DD diario 5%, DD total 10%, consistencia 40%, 2-step sin limite.")
    print(f"Funded: 1er payout a +{FUNDED_PAYOUT_PROFIT:.0%} y min {FUNDED_MIN_DAYS} dias, split {PROFIT_SPLIT:.0%}.")
    print(f"~{TRADES_PER_DAY} trades/dia.\n")
    print(f"{'riesgo':>7} | {'P(payout)':>9} | {'P(revienta)':>11} | "
          f"{'sem.total p50':>12} | {'rango p25-p75':>14} | {'challenge->payout p50':>20}")
    for risk in [0.0025, 0.005, 0.0075, 0.01]:
        rows = sim_plan(risk, n_paths=20000, seed=1)
        res, c = summarize(rows, risk)
        print(f"{res['risk']:>7} | {res['prob_llega_a_payout']:>9} | {res['prob_revienta']:>11} | "
              f"{res['sem_total_p50']:>12} | {res['sem_total_p25']}-{res['sem_total_p75']:>8} | "
              f"{res['sem_challenge_a_payout_p50']:>20}")
    # ejemplo de $ en el primer payout segun tamano de cuenta
    print("\nPrimer payout en $ (= +5% fondeada x 80% split):")
    for acct in [5000, 10000, 25000, 50000, 100000]:
        print(f"  cuenta ${acct:>6,}: ~${acct*FUNDED_PAYOUT_PROFIT*PROFIT_SPLIT:>6,.0f}")
