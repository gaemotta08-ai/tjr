"""senales_live.py — FORWARD TEST de SEÑALES (gratis, sin broker/API/plata).

Idea del usuario: el bot genera señales en vivo, se GUARDAN (no se ejecutan), y
después comparamos si las señales reales siguen al backtest (mismo winrate/expectancy).
Testea el EDGE hacia adelante. NO mide slippage (eso es la cuenta paga).

Datos gratis vía yfinance (NQ=F / ES=F / YM=F, 5m). Reusa el MISMO engine.py
(cero drift). Cada señal queda con 'primera_vez_vista' = prueba de que se logueó
en vivo y no con el diario del lunes.

Uso (correr 1x por día, o por cron tras el cierre):
  python3 senales_live.py pull       # baja las velas nuevas
  python3 senales_live.py log        # genera y guarda señales nuevas + resuelve las viejas
  python3 senales_live.py score      # compara las señales vivas vs el backtest -> ¿sigue o no?
  python3 senales_live.py all        # pull + log + score
"""
import sys, os
import numpy as np, pandas as pd
import data as D, engine as E, metrics as M

CFG = {"stop_anchor": "confluence", "sessions": ("ny_am", "london")}
SYMS = {"NQ": ("NQ=F", 0.25), "ES": ("ES=F", 0.25), "YM": ("YM=F", 1.0)}
FWD = "forward"; LD = f"{FWD}/live_data"; os.makedirs(LD, exist_ok=True)
REG = f"{FWD}/senales_live.csv"

# baseline del backtest tuneado (para la comparación)
def _bt_ci():
    bt = pd.read_csv("out/trades_tuned_confluence.csv")["R"].values
    rng = np.random.default_rng(0)
    means = [rng.choice(bt, size=120, replace=True).mean() for _ in range(2000)]
    return dict(exp=float(np.mean(bt)), win=float((bt > 0).mean()),
                exp_lo=float(np.percentile(means, 5)), exp_hi=float(np.percentile(means, 95)))


def pull():
    import yfinance as yf
    for sym, (tk, _) in SYMS.items():
        d = yf.download(tk, period="60d", interval="5m", progress=False, auto_adjust=False)
        if not len(d):
            print(f"  {sym}: sin datos"); continue
        d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
        d = d.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        d.index = pd.to_datetime(d.index, utc=True).tz_convert(D.NY)
        d.index.name = "ts"
        path = f"{LD}/{sym}.csv"
        if os.path.exists(path):
            old = pd.read_csv(path, index_col=0, parse_dates=True)
            old.index = pd.to_datetime(old.index, utc=True).tz_convert(D.NY)
            d = pd.concat([old, d])
            d = d[~d.index.duplicated(keep="last")].sort_index()
        d.to_csv(path)
        print(f"  {sym}: {len(d)} velas 5m  ({d.index[0].date()} → {d.index[-1].date()})")


def _load(sym):
    df = pd.read_csv(f"{LD}/{sym}.csv", index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert(D.NY)
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def log():
    # registro previo (preserva 'primera_vez_vista')
    reg = pd.read_csv(REG) if os.path.exists(REG) else pd.DataFrame()
    vistos = set(zip(reg["symbol"], reg["entry_time"])) if len(reg) else set()
    now = pd.Timestamp.now('UTC').tz_convert(D.NY).strftime("%Y-%m-%d %H:%M")
    nuevas = []
    for sym, (_, tick) in SYMS.items():
        if not os.path.exists(f"{LD}/{sym}.csv"): continue
        df = _load(sym)
        # engine sobre velas 5m (entry_tf=5min -> resample identidad). Cero look-ahead.
        tr, _ = E.backtest(dict(CFG, symbol=sym, entry_tf="5min", tick=tick), df1m=df)
        for _, r in tr.iterrows():
            key = (sym, str(r["entry_time"]))
            if key in vistos: continue
            nuevas.append(dict(symbol=sym, direction=r["direction"], entry=round(r["entry"], 2),
                               stop=round(r["stop"], 2), risk_pts=round(r["risk_pts"], 2),
                               R=round(float(r["R"]), 3), exit_reason=r["exit_reason"],
                               tps_hit=int(r["tps_hit"]), entry_time=str(r["entry_time"]),
                               exit_time=str(r["exit_time"]), primera_vez_vista=now))
    out = pd.concat([reg, pd.DataFrame(nuevas)], ignore_index=True) if len(nuevas) else reg
    if len(out): out.to_csv(REG, index=False)
    print(f"log: {len(nuevas)} señales NUEVAS guardadas (total acumulado: {len(out)})")
    if nuevas:
        for n in nuevas[-6:]:
            print(f"   {n['symbol']} {n['direction']:5} entry {n['entry']} R={n['R']:+.2f} "
                  f"({n['exit_reason']}) [{n['entry_time'][:16]}]")


def score():
    if not os.path.exists(REG):
        print("Todavía no hay señales. Corré 'pull' y 'log' cada día unas semanas."); return
    s = pd.read_csv(REG)
    ci = _bt_ci()
    # FORWARD PURO = señales vistas <= 1 día después de su entrada (no hindsight)
    fs = pd.to_datetime(s["primera_vez_vista"], errors="coerce").dt.normalize()
    et = pd.to_datetime(s["entry_time"], utc=True, errors="coerce").dt.tz_localize(None).dt.normalize()
    s["forward_puro"] = (fs - et).dt.days <= 1
    fwd = s[s["forward_puro"]]
    m = M.metrics(s["R"]); mf = M.metrics(fwd["R"])
    print("=== ¿LAS SEÑALES EN VIVO SIGUEN AL BACKTEST? ===")
    print(f"  BACKTEST baseline: exp={round(ci['exp'],3)}R (banda 90%: {round(ci['exp_lo'],2)}..{round(ci['exp_hi'],2)}R) | win={round(ci['win'],3)}")
    print(f"\n  TOTAL (incl. backfill de los últimos 60d = bonus, pero es hindsight):")
    print(f"    n={m['n']} | exp={m['expectancy_R']}R | win={m['winrate']} | PF={m['profit_factor']}")
    for sym, g in s.groupby("symbol"):
        mm = M.metrics(g["R"]); print(f"      {sym}: n={mm['n']} exp={mm['expectancy_R']}R win={mm['winrate']}")
    print(f"\n  ⭐ FORWARD PURO (señales guardadas EN VIVO, antes de saber el resultado):")
    print(f"    n={mf['n']} | exp={mf['expectancy_R']}R | win={mf['winrate']} | PF={mf['profit_factor']}")
    if mf["n"] < 40:
        print(f"    ⏳ Faltan ({mf['n']}/40). Corré 'pull' + 'log' cada día ~2-3 semanas y se llena solo.")
    else:
        sigue = (mf["expectancy_R"] >= ci["exp_lo"] and 0.55 <= mf["winrate"] <= 0.90)
        print(f"    >>> {'✅ SIGUE al backtest' if sigue else '⚠️ NO sigue — expectancy en vivo por debajo del backtest -> revisar'}")
    print("\n  (Valida el EDGE a futuro. El SLIPPAGE real es el OTRO test, con cuenta paga.)")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("pull", "all"): print("PULL:"); pull()
    if mode in ("log", "all"): log()
    if mode in ("score", "all"): score()
