"""FORWARD TEST ACELERADO de la estrategia TJR — validación independiente del backtest.

NO toca los resultados del backtest original (lee el motor, escribe solo en forward/).

DOS VÍAS EN PARALELO:
  (1) REPLAY OOS "tipo live" estricto sobre data NO usada en optimización
      (sensibilidad fue 2020-2024 -> holdout limpio = 2025-2026 y los últimos 3 meses).
      El motor ya decide solo sobre velas CERRADAS, FVG del impulso, niveles de sesiones
      previas, un trade a la vez, swings confirmados con delay -> CERO look-ahead.
  (2) DEMO LIVE (trader_tjr_futuros.py + ejecutor de Fede) para fills/slippage REALES.
      Eso requiere una cuenta demo ProjectX/TopstepX -> CABO SUELTO marcado abajo.

STRESS: el replay se re-corre con slippage 1x / 2x / 3x ticks por lado (piso de costos).

VEREDICTO go/no-go con umbrales anclados en el slippage (la debilidad conocida).

Modos:
  python3 forward_test.py replay      # OOS estricto NQ + stress 1x/2x/3x + veredicto
  python3 forward_test.py cross-oos   # OOS cruzado en instrumentos nunca vistos (DOW/RUT)
  python3 forward_test.py score       # scorecard del demo live (cuando haya forward/slippage_live.csv)
"""
import sys, os, json
import numpy as np, pandas as pd
import data as D, engine as E, metrics as M

CFG = {"stop_anchor": "confluence", "sessions": ("ny_am", "london")}  # tuneada; NY es la mejor
FWD = "forward"; os.makedirs(FWD, exist_ok=True)

# Umbrales go/no-go (del pedido; anclados en slippage)
GO = dict(min_trades=40, min_exp_real=0.20, min_winrate=0.65,
          worst_trade_floor=-1.5, max_slip_ticks_side=1.5, review_below_exp=0.15)


def run(symbol, start, end, slip_ticks=1, commission_pts=0.5):
    df = D.load_1m(symbol)
    sl = df[(df.index >= pd.Timestamp(start, tz=D.NY)) & (df.index < pd.Timestamp(end, tz=D.NY))]
    cfg = dict(CFG, symbol=symbol, slippage_ticks=slip_ticks, commission_pts=commission_pts)
    tr, _ = E.backtest(cfg, df1m=sl)
    return tr


def block(symbol, start, end, label):
    print(f"\n--- {label}: {symbol} {start[:7]} → {end[:7]} (NY am + London) ---")
    base = run(symbol, start, end, slip_ticks=1)
    if not len(base):
        print("  sin trades en el bloque"); return None
    # OOS edge vs null (azar con misma maquinaria de salida)
    exps = [float(np.mean(E.random_entry_null(
        D.load_1m(symbol)[(D.load_1m(symbol).index >= pd.Timestamp(start, tz=D.NY)) &
                          (D.load_1m(symbol).index < pd.Timestamp(end, tz=D.NY))],
        dict(CFG, symbol=symbol), n_target=len(base), risk_samples=base.risk_pts.values, seed=s)))
        for s in range(8)]
    z = (base.R.mean() - np.mean(exps)) / (np.std(exps) + 1e-9)
    print(f"{'slippage':>10} {'n':>5} {'exp R':>7} {'win':>6} {'PF':>6} {'sumR':>7} {'maxDD':>7} {'peor':>6}")
    out = {}
    for k in [1, 2, 3]:
        tr = run(symbol, start, end, slip_ticks=k)
        m = M.metrics(tr.R)
        out[f"{k}x"] = dict(m, worst=round(float(tr.R.min()), 2),
                            slip_loss_R=round(float(tr.R[tr.R < 0].mean()), 3))
        print(f"{str(k)+'x ('+str(k)+' tk/lado)':>10} {m['n']:>5} {m['expectancy_R']:>7.3f} "
              f"{m['winrate']:>6.2f} {m['profit_factor']:>6.2f} {m['sum_R']:>7.0f} "
              f"{m['max_dd_R']:>7.1f} {tr.R.min():>6.2f}")
    print(f"  edge OOS vs azar: z={z:.1f}  ({'EDGE real' if z>2 else 'débil'})")
    out["null_z"] = round(float(z), 2)
    base.to_csv(f"{FWD}/replay_{symbol}_{label}.csv", index=False)
    return out


def replay():
    print("=" * 78)
    print("VÍA 1 — REPLAY OUT-OF-SAMPLE ESTRICTO (NQ, data NO usada en optimización)")
    print("Optimización (sensibilidad) fue 2020-2024. Holdout limpio: 2025-2026.")
    print("=" * 78)
    res = {}
    res["holdout_2025_2026"] = block("NQ", "2025-01-01", "2026-06-13", "holdout25_26")
    res["ultimos_3_meses"] = block("NQ", "2026-03-13", "2026-06-13", "ult3m")
    # veredicto provisional (sobre el replay; el FINAL necesita slippage real del demo)
    print("\n" + "=" * 78); print("VEREDICTO PROVISIONAL (sobre replay; falta slippage real del demo)")
    print("=" * 78)
    h = res["holdout_2025_2026"]
    for k in ["1x", "2x", "3x"]:
        m = h[k]
        print(f"  slippage {k}: exp={m['expectancy_R']}R  win={m['winrate']}  "
              f"PF={m['profit_factor']}  peor={m['worst']}R")
    e1, e2, e3 = h["1x"]["expectancy_R"], h["2x"]["expectancy_R"], h["3x"]["expectancy_R"]
    win = h["1x"]["winrate"]; worst = h["1x"]["worst"]; n = h["1x"]["n"]
    print(f"\n  Gates (sobre holdout 2025-2026, n={n}):")
    g = []
    g.append(("n>=40", n >= GO["min_trades"]))
    g.append(("winrate>=0.65", win >= GO["min_winrate"]))
    g.append(("peor trade>=-1.5R", worst >= GO["worst_trade_floor"]))
    g.append(("exp 1x>=0.20R", e1 >= GO["min_exp_real"]))
    g.append(("exp 2x>=0.15R (sobrevive stress)", e2 >= GO["review_below_exp"]))
    g.append(("exp 3x>0 (piso)", e3 > 0))
    for name, ok in g:
        print(f"   [{'OK' if ok else 'X '}] {name}")
    ok = all(v for _, v in g)
    print(f"\n  >>> REPLAY: {'PASA — habilita pasar a la VÍA 2 (demo live para slippage real)' if ok else 'NO PASA / revisar'}")
    print("  El go/no-go DEFINITIVO se decide con el slippage REAL del demo (vía 2):")
    print(f"    GO si: exp neta con slippage real >= {GO['min_exp_real']}R sobre >= {GO['min_trades']} trades,")
    print(f"           winrate >= {GO['min_winrate']}, ningún trade < {GO['worst_trade_floor']}R, slippage <= {GO['max_slip_ticks_side']} tk/lado.")
    json.dump(res, open(f"{FWD}/replay.json", "w"), indent=1, default=str)
    # tiempo para juntar 40-50 trades en demo live
    print("\n  Ritmo demo live (3 instrumentos NQ/ES/DOW × ~2.2 trades/día c/u ≈ 6.6/día,")
    print("  ~33/semana): 40-50 trades en ~1.5 semanas; sólo NQ (~2.2/día): ~4 semanas.")


def cross_oos(start="2023-01-01", end="2027-01-01"):
    print("=== VÍA 1b — OOS CRUZADO (instrumentos NUNCA vistos: DOW, RUT) ===")
    print(f"{'instr':5} {'n':>5} {'exp R':>7} {'win':>6} {'PF':>6} {'null z':>7} {'tipo':>22}")
    rows = {}
    for sym in ["NQ", "ES", "DOW", "RUT"]:
        df = D.load_1m(sym)
        sl = df[(df.index >= pd.Timestamp(start, tz=D.NY)) & (df.index < pd.Timestamp(end, tz=D.NY))]
        tr, _ = E.backtest(dict(CFG, symbol=sym), df1m=sl)
        m = M.metrics(tr.R)
        exps = [float(np.mean(E.random_entry_null(sl, dict(CFG, symbol=sym),
                 n_target=len(tr), risk_samples=tr.risk_pts.values, seed=s))) for s in range(8)]
        z = (m["expectancy_R"] - np.mean(exps)) / (np.std(exps) + 1e-9)
        tipo = "diseño" if sym in ("NQ", "ES") else "NUNCA visto (OOS puro)"
        rows[sym] = dict(metrics=m, null_z=round(float(z), 2), tipo=tipo)
        print(f"{sym:5} {m['n']:>5} {m['expectancy_R']:>7.3f} {m['winrate']:>6.2f} "
              f"{m['profit_factor']:>6.2f} {z:>7.1f} {tipo:>22}")
    json.dump(rows, open(f"{FWD}/cross_oos.json", "w"), indent=1, default=str)


def score():
    p = f"{FWD}/slippage_live.csv"
    p2 = os.path.expanduser("~/Desktop/HANDOFF_fede/ejecucion/data/slippage_live.csv")
    src = p if os.path.exists(p) else (p2 if os.path.exists(p2) else None)
    if not src:
        print("Sin slippage_live.csv todavía. CABO SUELTO: corré la VÍA 2 (demo live) para generarlo.")
        print("Ver trader_tjr_futuros.py — necesita cuenta demo ProjectX/TopstepX + claves.")
        return
    sl = pd.read_csv(src)
    print(f"=== SLIPPAGE REAL (demo live): {len(sl)} trades ===")
    print(f"  slippage medio: {sl['slippage_pts'].mean():+.3f} pts ({sl['slippage_pts'].mean()/0.25:+.2f} ticks)")
    print(f"  backtest asumió: ~1 tick/lado + 0.5pt comisión")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "replay"
    {"replay": replay, "cross-oos": cross_oos, "score": score}.get(mode, replay)()
