"""PLAN PROFESIONAL: minimizar tiempo desde HOY (sin forward test) hasta el 1er
payout, eligiendo firma + riesgo optimo y la estrategia tuneada (stop confluencia).
Compara arquetipos reales de prop firms de FUTUROS (NQ) vs el 2-step cripto.
Bootstrap por DIA (respeta correlacion intradia y la regla de consistencia).
Numeros de firmas = arquetipos 2025-26, VERIFICAR promos vigentes.
"""
import numpy as np, pandas as pd

# Serie de R por dia-calendario de la estrategia tuneada (stop confluencia, NY+London)
tr = pd.read_csv("out/trades_tuned_confluence.csv")
tr["d"] = pd.to_datetime(tr["date"], utc=True).dt.date
daily = tr.groupby("d").R.sum()
full = pd.bdate_range(daily.index.min(), daily.index.max())
DAILY_R = daily.reindex(full.date, fill_value=0.0).values   # incluye dias sin trade
print(f"Estrategia tuneada (stop confluencia): {DAILY_R.mean():.2f} R/dia, "
      f"peor dia {DAILY_R.min():.2f} R, {len(DAILY_R)} dias")

def sim_phase(rng, risk, target, dd, dd_type="trailing", daily_limit=None,
              consistency=None, min_days=0, max_days=500):
    """Opera dias (sampleando R diario real) hasta llegar a target. Devuelve (dias, ok)."""
    bal = 0.0; peak = 0.0; best = 0.0
    for day in range(1, max_days + 1):
        dR = float(rng.choice(DAILY_R))
        d_pnl = risk * dR
        bal += d_pnl
        peak = max(peak, bal)
        best = max(best, d_pnl)
        # daily loss
        if daily_limit is not None and d_pnl <= -daily_limit:
            return day, False
        # drawdown
        floor = (peak - dd) if dd_type == "trailing" else (-dd)
        if bal <= floor:
            return day, False
        if bal >= target and day >= min_days:
            if consistency is None or best <= consistency * bal:
                return day, True
    return max_days, False

# ---- Arquetipos de firma (cuenta $50k de referencia) ----
ACC = 50000
FIRMS = {
 "HyroTrader 2-step (cripto, ACTUAL)": dict(
    phases=[("P1", 0.10), ("P2", 0.05)], dd=0.10, dd_type="trailing",
    daily=0.05, consist_eval=0.40, funded_target=0.05, funded_min=14,
    consist_funded=0.40, split=0.80, cost=0),  # costo cripto aparte
 "1-step trailing (Apex-style)": dict(
    phases=[("eval", 0.06)], dd=0.05, dd_type="trailing",
    daily=None, consist_eval=None, funded_target=0.05, funded_min=8,
    consist_funded=0.30, split=0.90, cost=180),
 "1-step static-DD (MFFU-style)": dict(
    phases=[("eval", 0.06)], dd=0.05, dd_type="static",
    daily=None, consist_eval=None, funded_target=0.05, funded_min=5,
    consist_funded=0.20, split=0.90, cost=165),
 "Instant funding (Tradeify-style, SIN eval)": dict(
    phases=[], dd=0.05, dd_type="trailing",
    daily=None, consist_eval=None, funded_target=0.04, funded_min=10,
    consist_funded=0.20, split=0.90, cost=450),
}

def sim_firm(f, risk, n=20000, seed=1):
    rng = np.random.default_rng(seed)
    dd, ddt, daily = f["dd"], f["dd_type"], f["daily"]
    total_days = []; ok = 0
    for _ in range(n):
        d = 0; alive = True
        for _, tgt in f["phases"]:
            dd_, okp = sim_phase(rng, risk, tgt, dd, ddt, daily, f["consist_eval"])
            d += dd_
            if not okp: alive = False; break
        if not alive:
            continue
        df_, okf = sim_phase(rng, risk, f["funded_target"], dd, ddt, daily,
                             f["consist_funded"], min_days=f["funded_min"])
        if not okf:
            continue
        ok += 1; total_days.append(d + df_)
    if not total_days:
        return None
    td = np.array(total_days)
    return dict(prob_payout=ok / n, d50=np.percentile(td, 50), d25=np.percentile(td, 25),
                d75=np.percentile(td, 75))

print(f"\nObjetivo: MIN tiempo desde compra del challenge -> 1er payout (SIN forward test).")
print(f"Cuenta ref ${ACC:,}. Tiempo en SEMANAS calendario (dias habiles/5).\n")
hdr = f"{'FIRMA':40} {'riesgo':>6} {'P(payout)':>9} {'sem p50':>8} {'rango':>11} {'costo':>6} {'payout$':>8}"
print(hdr); print("-"*len(hdr))
best_overall = None
for name, f in FIRMS.items():
    # buscar riesgo que minimiza tiempo con prob_payout>=0.85
    rows = []
    for risk in [0.0025, 0.004, 0.005, 0.006, 0.008, 0.01]:
        r = sim_firm(f, risk)
        if r: rows.append((risk, r))
    # elegir el de menor d50 con prob>=0.85 (si ninguno, el de mayor prob)
    feas = [(rk, r) for rk, r in rows if r["prob_payout"] >= 0.85]
    pick = min(feas, key=lambda x: x[1]["d50"]) if feas else max(rows, key=lambda x: x[1]["prob_payout"])
    rk, r = pick
    payout = ACC * f["funded_target"] * f["split"]
    wk = lambda d: d/5
    print(f"{name:40} {rk:>6.2%} {r['prob_payout']:>9.0%} "
          f"{wk(r['d50']):>8.1f} {wk(r['d25']):.1f}-{wk(r['d75']):.1f}{'':3} "
          f"${f['cost']:>5} ${payout:>7,.0f}")
    if (best_overall is None or wk(r['d50']) < best_overall[1]) and r['prob_payout'] >= 0.85:
        best_overall = (name, wk(r['d50']), rk, payout, f['cost'])

print(f"\n>>> MAS RAPIDO (prob>=85%): {best_overall[0]} a {best_overall[2]:.2%} riesgo")
print(f"    1er payout en ~{best_overall[1]:.1f} semanas, ${best_overall[3]:,.0f} (costo cuenta ${best_overall[4]}).")

# Costo y payout por tamano de cuenta para la mejor firma 1-step/instant
print("\nPayout y costo por tamano de cuenta (instant funding, +4% x 90% split):")
for acc in [25000, 50000, 100000, 150000]:
    print(f"  ${acc:>7,}: 1er payout ~${acc*0.04*0.9:>6,.0f}  (costo cuenta ~${int(acc/50000*450)})")
