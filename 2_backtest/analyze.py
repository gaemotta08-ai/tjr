"""Analisis exhaustivo de la estrategia TJR: full + sectorizado, con controles
de overfitting (IS/OOS, walk-forward, sensibilidad, null de Monte Carlo) y
Monte Carlo de riesgo (equity/drawdown/ruina + prob. de pasar prop firm).
Escribe out/report.json, out/report.md y graficos. Pensado para correr en background;
va volcando resultados a disco a medida que avanza."""
import json, time, sys
import numpy as np, pandas as pd
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAVE_PLT = True
except Exception as _e:
    HAVE_PLT = False
    print("WARN: matplotlib no disponible, se exportan CSV en vez de PNG:", _e)
import data as D, engine as E, metrics as M

OUT = "out"
T0 = time.time()
def log(*a):
    print(f"[{time.time()-T0:6.0f}s]", *a, flush=True)

REPORT = {}
def save():
    with open(f"{OUT}/report.json", "w") as f:
        json.dump(REPORT, f, indent=1, default=str)

YEARS = list(range(2017, 2027))
def yslice(df, y0, y1):
    return df[(df.index >= pd.Timestamp(f"{y0}-01-01", tz=D.NY)) &
              (df.index < pd.Timestamp(f"{y1}-01-01", tz=D.NY))]

# --------------------------------------------------------------------------
def run_symbol(sym, cfg=None):
    df = D.load_1m(sym)
    tr, _ = E.backtest(cfg or {}, df1m=df)
    return df, tr

def sector_table(tr, by):
    g = tr.groupby(by).R
    out = {}
    for k, v in g:
        m = M.metrics(v)
        out[str(k)] = {x: m[x] for x in ["n", "expectancy_R", "winrate", "profit_factor", "sum_R", "max_dd_R"]}
    return out

# === 1. BASELINE full-period NQ + ES ======================================
def stage_baseline():
    log("STAGE 1: baseline full-period NQ + ES")
    data = {}
    for sym in ["NQ", "ES"]:
        df, tr = run_symbol(sym)
        tr.to_csv(f"{OUT}/trades_{sym}.csv", index=False)
        data[sym] = (df, tr)
        REPORT.setdefault("baseline", {})[sym] = dict(
            overall=M.metrics(tr.R),
            by_year={str(y): M.metrics(tr[tr.date.dt.year == y].R) for y in YEARS},
            by_session=sector_table(tr, "session"),
            by_direction=sector_table(tr, "direction"),
            by_exit=tr.exit_reason.value_counts().to_dict(),
        )
        log(f"  {sym}: {M.metrics(tr.R)}")
    save()
    return data

# === 2. NULL de Monte Carlo (edge real vs mecanica de salida) =============
def stage_null(data):
    log("STAGE 2: null de entrada aleatoria (20 seeds) por simbolo")
    for sym, (df, tr) in data.items():
        exps = []
        for s in range(20):
            r = E.random_entry_null(df, n_target=len(tr), risk_samples=tr.risk_pts.values, seed=s)
            exps.append(float(np.mean(r)))
        exps = np.array(exps)
        real = float(tr.R.mean())
        z = (real - exps.mean()) / (exps.std() + 1e-9)
        REPORT.setdefault("null_test", {})[sym] = dict(
            real_expectancy_R=round(real, 4),
            null_mean=round(float(exps.mean()), 4), null_sd=round(float(exps.std()), 4),
            null_p95=round(float(np.percentile(exps, 95)), 4),
            z_score=round(float(z), 2),
            veredicto="edge real (z>3)" if z > 3 else ("debil" if z > 1.5 else "sin edge sobre null"),
        )
        log(f"  {sym}: real={real:.3f} null={exps.mean():.3f}+-{exps.std():.3f} z={z:.1f}")
    save()

# === 3. ABLACIONES de componentes (sectorizado) ===========================
def stage_ablations():
    log("STAGE 3: ablaciones de componentes (NQ full)")
    df = D.load_1m("NQ")
    variants = {
        "base (liquidity TP, BE, no bias, 5m)": {},
        "+ bias filter HTF (h1)": {"bias_filter": "h1"},
        "TP por R fijo [1,2,3] (en vez de liquidez)": {"tp_mode": "R"},
        "sin breakeven (use_be=False)": {"use_be": False},
        "stop en confluencia (no en sweep)": {"stop_anchor": "confluence"},
        "entry TF 15m": {"entry_tf": "15min"},
        "solo London": {"sessions": ("london",)},
        "solo NY am": {"sessions": ("ny_am",)},
        "sin parciales (todo a TP-final, 1 contrato)": {"tp_fracs": (0.0, 0.0, 1.0)},
    }
    res = {}
    for name, cfg in variants.items():
        tr, _ = E.backtest(cfg, df1m=df)
        res[name] = M.metrics(tr.R)
        log(f"  {name}: n={res[name]['n']} exp={res[name]['expectancy_R']} "
            f"win={res[name]['winrate']} pf={res[name]['profit_factor']} sumR={res[name]['sum_R']}")
    REPORT["ablations_NQ"] = res
    save()

# === 4. IS / OOS y WALK-FORWARD ===========================================
def stage_walkforward():
    log("STAGE 4: IS/OOS + walk-forward (NQ)")
    df = D.load_1m("NQ")
    # IS 2017-2021 / OOS 2022-2026
    is_tr, _ = E.backtest({}, df1m=yslice(df, 2017, 2022))
    oos_tr, _ = E.backtest({}, df1m=yslice(df, 2022, 2027))
    REPORT["is_oos"] = dict(
        in_sample_2017_2021=M.metrics(is_tr.R),
        out_of_sample_2022_2026=M.metrics(oos_tr.R),
        degradacion_expectancy=round(M.metrics(oos_tr.R)["expectancy_R"] -
                                     M.metrics(is_tr.R)["expectancy_R"], 4),
    )
    log(f"  IS exp={M.metrics(is_tr.R)['expectancy_R']} | OOS exp={M.metrics(oos_tr.R)['expectancy_R']}")
    # Walk-forward anclado: para cada ano test, optimiza tp_mode/bias/stop sobre lo previo
    grid = [{}, {"bias_filter": "h1"}, {"tp_mode": "R"}, {"stop_anchor": "confluence"},
            {"use_be": False}]
    wf = []
    for ytest in range(2019, 2027):
        train = yslice(df, 2017, ytest)
        best = None
        for cfg in grid:
            tr, _ = E.backtest(cfg, df1m=train)
            e = M.metrics(tr.R)["expectancy_R"] if len(tr) else -9
            if best is None or e > best[1]:
                best = (cfg, e)
        test_tr, _ = E.backtest(best[0], df1m=yslice(df, ytest, ytest + 1))
        mt = M.metrics(test_tr.R)
        wf.append(dict(year=ytest, best_cfg=str(best[0]), train_exp=round(best[1], 3),
                       test_n=mt["n"], test_exp=mt["expectancy_R"], test_win=mt["winrate"],
                       test_sumR=mt["sum_R"]))
        log(f"  WF {ytest}: cfg={best[0]} train_exp={best[1]:.3f} -> test_exp={mt['expectancy_R']} (n={mt['n']})")
    REPORT["walk_forward"] = wf
    oos_exps = [w["test_exp"] for w in wf if w["test_n"] > 10]
    REPORT["walk_forward_resumen"] = dict(
        anios=len(oos_exps), media_test_exp=round(float(np.mean(oos_exps)), 4),
        anios_positivos=int(sum(e > 0 for e in oos_exps)),
        peor_anio=round(float(min(oos_exps)), 4), mejor_anio=round(float(max(oos_exps)), 4))
    save()

# === 5. SENSIBILIDAD de parametros (plateau vs spike = overfit) ===========
def stage_sensitivity():
    log("STAGE 5: sensibilidad de parametros (NQ 2020-2024)")
    df = yslice(D.load_1m("NQ"), 2020, 2025)
    sweeps = {
        "swing_k": [1, 2, 3, 4],
        "bos_max_bars": [6, 9, 12, 18, 24],
        "fvg_entry_frac": [0.0, 0.25, 0.5, 0.75, 1.0],
        "stop_buffer_ticks": [0, 2, 4, 8, 12],
        "entry_valid_bars": [6, 9, 12, 18, 24],
        "sweep_min_ticks": [0, 1, 2, 4],
        "swing_lookback": [15, 20, 30, 40, 60],
    }
    res = {}
    for param, vals in sweeps.items():
        row = {}
        for v in vals:
            tr, _ = E.backtest({param: v}, df1m=df)
            m = M.metrics(tr.R)
            row[str(v)] = dict(n=m["n"], exp=m["expectancy_R"], win=m["winrate"],
                               pf=m["profit_factor"], sumR=m["sum_R"])
        res[param] = row
        exps = [row[str(v)]["exp"] for v in vals]
        log(f"  {param}: exps={[round(e,3) for e in exps]} (rango {min(exps):.3f}-{max(exps):.3f})")
    REPORT["sensitivity_NQ_2020_2024"] = res
    save()

# === 6. MONTE CARLO de riesgo + PROP FIRM =================================
def stage_montecarlo(data):
    log("STAGE 6: Monte Carlo de riesgo + prop firm (HyroTrader)")
    for sym, (df, tr) in data.items():
        R = tr.R.values
        mc = M.mc_bootstrap(R, n_paths=10000)
        REPORT.setdefault("montecarlo", {})[sym] = {k: v for k, v in mc.items() if not k.startswith("_")}
        # prop firm: HyroTrader aprox -> target 8% fase1, daily loss 5%, max dd 10%
        for rpt in [0.0025, 0.005, 0.01]:
            pf = M.prop_firm_sim(R, risk_per_trade=rpt, trades_per_day=2,
                                 profit_target=0.08, daily_loss=0.05, max_dd=0.10, n_paths=8000)
            REPORT.setdefault("prop_firm", {}).setdefault(sym, {})[f"risk_{rpt}"] = pf
            log(f"  {sym} risk/trade={rpt:.2%}: pass={pf['prob_pass']:.2%} "
                f"bust_daily={pf['prob_bust_daily']:.2%} bust_dd={pf['prob_bust_maxdd']:.2%}")
        log(f"  {sym} MC bootstrap: final p5={mc['final_p5']} p50={mc['final_p50']} p95={mc['final_p95']} "
            f"| maxDD p50={mc['maxdd_p50']} p95(peor5%)={mc['maxdd_p95']}")
    save()
    return data

# === 7. GRAFICOS ==========================================================
def stage_plots(data):
    log("STAGE 7: graficos / export equity")
    for sym, (df, tr) in data.items():
        eq, dd = M.equity_dd(tr.R)
        # siempre exportar equity como CSV (independiente de matplotlib)
        pd.DataFrame({"entry_time": tr.entry_time.values, "R": tr.R.values,
                      "equity_R": eq.values, "drawdown_R": dd.values}).to_csv(
            f"{OUT}/equity_{sym}.csv", index=False)
    if not HAVE_PLT:
        log("  matplotlib no disponible -> solo CSV de equity")
        return
    for sym, (df, tr) in data.items():
        eq, dd = M.equity_dd(tr.R)
        fig, ax = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        ax[0].plot(tr.entry_time.values, eq.values); ax[0].set_title(f"{sym} equity (R acumulado) - estrategia TJR")
        ax[0].grid(alpha=.3)
        ax[1].fill_between(tr.entry_time.values, dd.values, 0, color="red", alpha=.4)
        ax[1].set_title("Drawdown (R)"); ax[1].grid(alpha=.3)
        fig.tight_layout(); fig.savefig(f"{OUT}/equity_{sym}.png", dpi=90); plt.close(fig)
        # Monte Carlo fan
        mc = M.mc_bootstrap(tr.R.values, n_paths=2000)
        fig, ax = plt.subplots(1, 2, figsize=(11, 4))
        ax[0].hist(mc["_finals"], bins=60, color="steelblue"); ax[0].axvline(0, color="k", ls="--")
        ax[0].set_title(f"{sym} MC: PnL final (R) - {2000} paths")
        ax[1].hist(mc["_maxdd"], bins=60, color="indianred")
        ax[1].set_title(f"{sym} MC: max drawdown (R)")
        fig.tight_layout(); fig.savefig(f"{OUT}/montecarlo_{sym}.png", dpi=90); plt.close(fig)
    log("  graficos guardados")

# --------------------------------------------------------------------------
if __name__ == "__main__":
    stages = sys.argv[1:] or ["all"]
    data = stage_baseline()
    if "all" in stages:
        stage_null(data)
        stage_ablations()
        stage_walkforward()
        stage_sensitivity()
        stage_montecarlo(data)
        stage_plots(data)
    log("LISTO. report.json escrito.")
