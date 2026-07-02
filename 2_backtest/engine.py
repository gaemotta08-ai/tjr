"""Motor de backtest de la estrategia mecanica de TJR (SMC/ICT).
Deterministico y SIN look-ahead. Implementa pseudocodigo.py:
  killzone -> barrido de liquidez (sweep) -> break of structure (BOS, por cierre)
  -> entrada limite en FVG -> stop estructural del lado del barrido
  -> TP escalonado a liquidez opuesta con parciales 50/25/25 -> breakeven tras TP1.
Resultados en multiplos de R (riesgo inicial), netos de costos (slippage+comision).
"""
import numpy as np
import pandas as pd
import data as D

DEFAULT = dict(
    symbol="NQ", entry_tf="5min",
    sessions=("london", "ny_am"),
    swing_k=2, swing_lookback=30, tick=0.25,
    sweep_min_ticks=1, bos_max_bars=12,
    fvg_entry_frac=0.5, entry_valid_bars=12,
    stop_anchor="sweep", stop_buffer_ticks=4, min_stop_ticks=8,
    tp_mode="liquidity", tp_R=(1.0, 2.0, 3.0), tp_fracs=(0.5, 0.25, 0.25),
    use_be=True, be_after_tp=1, trail_after_tp=2,
    bias_filter="none",
    slippage_ticks=1, commission_pts=0.5,   # NQ: ~$5 RT + spread (en puntos)
    max_hold_bars=78,           # ~media sesion en 5m; cierra al final si sigue
    max_trades_per_day=4,
    no_overlap=True,            # un trade a la vez (evita dupes correlacionados)
)


def swing_points(df, k):
    h = df["high"].values; l = df["low"].values
    n = len(df); sh = np.zeros(n, bool); sl = np.zeros(n, bool)
    for i in range(k, n - k):
        if h[i] == max(h[i - k:i + k + 1]) and h[i] >= h[i - 1]:
            sh[i] = True
        if l[i] == min(l[i - k:i + k + 1]) and l[i] <= l[i - 1]:
            sl[i] = True
    return sh, sl


def h1_bias(df1m):
    """Bias HTF en 1H por estructura HH/HL (+1 up, -1 down, 0 indef)."""
    h1 = D.resample(df1m, "60min")
    sh, sl = swing_points(h1, 2)
    H = h1["high"].values; L = h1["low"].values
    out = np.zeros(len(h1), int)
    last_sh = prev_sh = last_sl = prev_sl = None; cur = 0
    for i in range(len(h1)):
        if sh[i]: prev_sh, last_sh = last_sh, H[i]
        if sl[i]: prev_sl, last_sl = last_sl, L[i]
        if None not in (last_sh, prev_sh, last_sl, prev_sl):
            if last_sh > prev_sh and last_sl > prev_sl: cur = 1
            elif last_sh < prev_sh and last_sl < prev_sl: cur = -1
        out[i] = cur
    return pd.Series(out, index=h1.index)


_CACHE = {}
def _prep(df1m, entry_tf, swing_k):
    """Precompute cacheado: resample + sesiones + swings + niveles de sesion."""
    key = (id(df1m), len(df1m), entry_tf, swing_k)
    if key in _CACHE:
        return _CACHE[key]
    etf = D.resample(df1m, entry_tf)
    SS = D.tag_session(etf.index)
    SHv, SLv = swing_points(etf, swing_k)
    slv = D.session_levels(df1m)
    ctx = dict(etf=etf, SS=SS, SHv=SHv, SLv=SLv, slv=slv,
               days_sorted=slv.index.get_level_values(0).unique(),
               norm=etf.index.normalize())
    if len(_CACHE) > 24: _CACHE.clear()
    _CACHE[key] = ctx
    return ctx


def backtest(cfg=None, df1m=None, start=None, end=None):
    c = dict(DEFAULT); c.update(cfg or {})
    if df1m is None:
        df1m = D.load_1m(c["symbol"])
    if start: df1m = df1m[df1m.index >= pd.Timestamp(start, tz=D.NY)]
    if end:   df1m = df1m[df1m.index <= pd.Timestamp(end, tz=D.NY)]

    ctx = _prep(df1m, c["entry_tf"], c["swing_k"])
    etf = ctx["etf"]; SS = ctx["SS"]; SHv = ctx["SHv"]; SLv = ctx["SLv"]
    O, H, L, C = (etf[x].values for x in ("open", "high", "low", "close"))
    DT = etf.index
    n = len(etf)
    tick = c["tick"]; slip = c["slippage_ticks"] * tick

    bias_s = h1_bias(df1m) if c["bias_filter"] == "h1" else None
    bias_idx = bias_s.index.values if bias_s is not None else None
    bias_val = bias_s.values if bias_s is not None else None

    slv = ctx["slv"]
    days_sorted = ctx["days_sorted"]
    norm = ctx["norm"]

    def prior_levels(day):
        lv_h, lv_l = [], []
        pdys = days_sorted[days_sorted < day]
        if len(pdys):
            sub = slv.loc[pdys[-1]]
            lv_h.append(float(sub["hi"].max())); lv_l.append(float(sub["lo"].min()))
            for s in ("asia", "london", "ny_am", "ny_pm"):
                if s in sub.index:
                    lv_h.append(float(sub.loc[s, "hi"])); lv_l.append(float(sub.loc[s, "lo"]))
        if day in days_sorted:
            sub = slv.loc[day]
            for s in ("asia", "london"):
                if s in sub.index:
                    lv_h.append(float(sub.loc[s, "hi"])); lv_l.append(float(sub.loc[s, "lo"]))
        return lv_h, lv_l

    def bias_at(ts):
        if bias_val is None: return 0
        k = np.searchsorted(bias_idx, np.datetime64(ts.tz_convert("UTC").tz_localize(None)), "right") - 1
        return int(bias_val[k]) if k >= 0 else 0

    trades = []
    day_count = {}
    cur_day = None; cur_lvh = cur_lvl = None
    block_until = -1
    kconf = c["swing_k"]   # delay de confirmacion de swing (anti look-ahead)

    for i in range(c["swing_lookback"], n - 2):
        if SS[i] not in c["sessions"]:
            continue
        if c["no_overlap"] and i <= block_until:
            continue
        day = norm[i]
        if day != cur_day:
            cur_day = day; cur_lvh, cur_lvl = prior_levels(day)
        if day_count.get(day, 0) >= c["max_trades_per_day"]:
            continue

        # solo swings YA CONFIRMADOS (j + k <= i)  -> sin look-ahead
        w0 = i - c["swing_lookback"]
        rec_sh = [H[j] for j in range(w0, i - kconf) if SHv[j]]
        rec_sl = [L[j] for j in range(w0, i - kconf) if SLv[j]]
        highs = cur_lvh + rec_sh
        lows = cur_lvl + rec_sl

        swept_high = None
        for p in highs:
            if H[i] > p + c["sweep_min_ticks"] * tick and C[i] < p:
                swept_high = p if swept_high is None else max(swept_high, p)
        swept_low = None
        for p in lows:
            if L[i] < p - c["sweep_min_ticks"] * tick and C[i] > p:
                swept_low = p if swept_low is None else min(swept_low, p)

        for direction, swept in (("short", swept_high), ("long", swept_low)):
            if swept is None:
                continue
            if c["bias_filter"] != "none":
                b = bias_at(DT[i])
                if direction == "short" and b >= 0: continue
                if direction == "long" and b <= 0: continue
            tr = _run_setup(i, direction, swept, O, H, L, C, SHv, SLv,
                            highs, lows, c, tick, slip, n)
            if tr:
                tr["date"] = day; tr["session"] = SS[i]
                tr["entry_time"] = DT[tr["entry_i"]]; tr["exit_time"] = DT[tr["exit_i"]]
                trades.append(tr)
                day_count[day] = day_count.get(day, 0) + 1
                block_until = tr["exit_i"]
                break

    cols = ["date", "session", "direction", "entry", "stop", "risk_pts",
            "entry_time", "exit_time", "entry_i", "exit_i", "R", "tps_hit",
            "exit_reason", "mae_R", "mfe_R"]
    df = pd.DataFrame(trades)
    if len(df):
        df = df[cols]
    return df, etf


def _find_fvg(bos_i, direction, H, L, n, frac):
    # FVG del impulso de ruptura: triplete (a,b,c) con c<=bos_i (SIN look-ahead).
    # Busca el gap mas cercano al BOS hacia atras.
    for c_ in range(bos_i, max(1, bos_i - 4), -1):
        a, cc = c_ - 2, c_
        if a < 0: continue
        if direction == "short" and L[a] > H[cc]:
            top, bot = L[a], H[cc]; return bot + frac * (top - bot)
        if direction == "long" and H[a] < L[cc]:
            bot, top = H[a], L[cc]; return bot + frac * (top - bot)
    return None


def _run_setup(i, direction, swept, O, H, L, C, SHv, SLv, highs, lows, c, tick, slip, n):
    # extremo real del barrido + swing de referencia para BOS (confirmado)
    kc = c["swing_k"]
    if direction == "short":
        sweep_extreme = max(H[i], swept)
        ref = next((L[j] for j in range(i - kc, max(0, i - c["swing_lookback"]), -1) if SLv[j]), None)
    else:
        sweep_extreme = min(L[i], swept)
        ref = next((H[j] for j in range(i - kc, max(0, i - c["swing_lookback"]), -1) if SHv[j]), None)
    if ref is None: return None

    bos_i = None
    for j in range(i + 1, min(n, i + 1 + c["bos_max_bars"])):
        if (direction == "short" and C[j] < ref) or (direction == "long" and C[j] > ref):
            bos_i = j; break
    if bos_i is None: return None

    entry = _find_fvg(bos_i, direction, H, L, n, c["fvg_entry_frac"])
    if entry is None: return None

    if direction == "short":
        stop = (sweep_extreme + c["stop_buffer_ticks"] * tick) if c["stop_anchor"] == "sweep" \
            else entry + 0.5 * (sweep_extreme - entry) + c["stop_buffer_ticks"] * tick
        if (stop - entry) < c["min_stop_ticks"] * tick: stop = entry + c["min_stop_ticks"] * tick
        tlist = sorted([p for p in lows if p < entry], reverse=True)
    else:
        stop = (sweep_extreme - c["stop_buffer_ticks"] * tick) if c["stop_anchor"] == "sweep" \
            else entry - 0.5 * (entry - sweep_extreme) - c["stop_buffer_ticks"] * tick
        if (entry - stop) < c["min_stop_ticks"] * tick: stop = entry - c["min_stop_ticks"] * tick
        tlist = sorted([p for p in highs if p > entry])

    risk = abs(entry - stop)
    if risk <= 0: return None

    if c["tp_mode"] == "R":
        tps = [entry + (-1 if direction == "short" else 1) * R * risk for R in c["tp_R"]]
    else:
        tps = (tlist + [None, None, None])[:3]
        for k_ in range(3):
            if tps[k_] is None:
                R = c["tp_R"][k_]
                tps[k_] = entry + (-1 if direction == "short" else 1) * R * risk

    # ---- fill de la orden limite (retroceso al FVG) ----
    f = None
    for j in range(bos_i + 1, min(n, bos_i + 1 + c["entry_valid_bars"])):
        if direction == "short" and H[j] >= entry: f = j; break
        if direction == "long" and L[j] <= entry: f = j; break
    if f is None: return None

    return _manage(direction, entry, stop, tps, risk, f, H, L, C, SHv, SLv, c, tick, slip, n)


def _manage(direction, entry, stop, tps, risk, f, H, L, C, SHv, SLv, c, tick, slip, n):
    """Gestion de salida compartida: parciales 50/25/25, BE tras TP1,
    trailing tras TP2, stop conservador (stop antes que TP en la misma vela)."""
    fr = c["tp_fracs"]
    pos = 1.0; realized = 0.0; cur_stop = stop; tps_hit = 0
    mae = 0.0; mfe = 0.0
    exit_i = f; reason = "open"

    for j in range(f, min(n, f + c["max_hold_bars"])):
        if direction == "short":
            mfe = max(mfe, (entry - L[j]) / risk); mae = min(mae, (entry - H[j]) / risk)
        else:
            mfe = max(mfe, (H[j] - entry) / risk); mae = min(mae, (L[j] - entry) / risk)

        hit_stop = (H[j] >= cur_stop) if direction == "short" else (L[j] <= cur_stop)
        if hit_stop and j > f:
            px = (cur_stop + slip) if direction == "short" else (cur_stop - slip)
            realized += pos * ((entry - px) if direction == "short" else (px - entry))
            exit_i = j; reason = "be" if tps_hit >= c["be_after_tp"] and c["use_be"] else "stop"
            pos = 0.0; break

        while tps_hit < 3:
            tp = tps[tps_hit]
            reached = (L[j] <= tp) if direction == "short" else (H[j] >= tp)
            if not reached: break
            frac = fr[tps_hit]
            px = (tp + slip) if direction == "short" else (tp - slip)
            realized += frac * ((entry - px) if direction == "short" else (px - entry))
            pos -= frac; tps_hit += 1
            if c["use_be"] and tps_hit == c["be_after_tp"]:
                cur_stop = entry
            if tps_hit == c["trail_after_tp"]:
                if direction == "short":
                    sw = next((H[k] for k in range(j, f, -1) if SHv[k]), cur_stop)
                    cur_stop = min(cur_stop, sw)
                else:
                    sw = next((L[k] for k in range(j, f, -1) if SLv[k]), cur_stop)
                    cur_stop = max(cur_stop, sw)
            if pos <= 1e-9:
                exit_i = j; reason = "tp_full"; break
        if pos <= 1e-9:
            if reason == "open": reason = "tp_full"
            exit_i = j; break
    if reason == "open":
        jx = min(n - 1, f + c["max_hold_bars"] - 1); px = C[jx]
        realized += pos * ((entry - px) if direction == "short" else (px - entry))
        exit_i = jx; reason = "time"

    R = realized / risk - c["commission_pts"] / risk
    return dict(direction=direction, entry=entry, stop=stop, risk_pts=risk,
                entry_i=f, exit_i=exit_i, R=float(R), tps_hit=tps_hit,
                exit_reason=reason, mae_R=float(mae), mfe_R=float(mfe))


def random_entry_null(df1m, cfg=None, n_target=None, risk_samples=None, seed=1):
    """NULL de Monte Carlo: entradas ALEATORIAS en velas de killzone, direccion
    aleatoria, MISMA logica de salida (stop/TP-R/BE) y misma distribucion de riesgo.
    Si el setup real (sweep+BOS+FVG) tiene edge direccional, debe SUPERAR a esto."""
    c = dict(DEFAULT); c.update(cfg or {})
    ctx = _prep(df1m, c["entry_tf"], c["swing_k"])
    etf = ctx["etf"]; SS = ctx["SS"]; SHv = ctx["SHv"]; SLv = ctx["SLv"]
    H, L, C = (etf[x].values for x in ("high", "low", "close"))
    n = len(etf); tick = c["tick"]; slip = c["slippage_ticks"] * tick
    rng = np.random.default_rng(seed)
    kz = np.array([i for i in range(c["swing_lookback"], n - c["max_hold_bars"] - 2)
                   if SS[i] in c["sessions"]])
    if n_target is None: n_target = len(kz) // 20
    n_target = min(n_target, len(kz))
    risk_samples = np.asarray(risk_samples) if risk_samples is not None else np.array([15.0])
    out = []
    picks = rng.choice(kz, size=n_target, replace=False); picks.sort()
    last = -1
    for i in picks:
        if i <= last: continue
        direction = "short" if rng.random() < 0.5 else "long"
        entry = C[i]
        risk = float(rng.choice(risk_samples))
        stop = entry + risk if direction == "short" else entry - risk
        tps = [entry + (-1 if direction == "short" else 1) * R * risk for R in c["tp_R"]]
        f = i + 1
        if f >= n: continue
        tr = _manage(direction, entry, stop, tps, risk, f, H, L, C, SHv, SLv, c, tick, slip, n)
        if tr:
            out.append(tr["R"]); last = tr["exit_i"]
    return np.array(out)


if __name__ == "__main__":
    import sys, time
    cfg = {}
    if len(sys.argv) > 1: cfg["symbol"] = sys.argv[1]
    t0 = time.time()
    df1m = D.load_1m(cfg.get("symbol", "NQ"))
    sl = df1m[(df1m.index >= pd.Timestamp("2023-01-01", tz=D.NY)) &
              (df1m.index < pd.Timestamp("2024-01-01", tz=D.NY))]
    tr, etf = backtest(cfg, df1m=sl)
    print(f"slice 2023 {cfg.get('symbol','NQ')}: {len(tr)} trades en {time.time()-t0:.1f}s")
    if len(tr):
        import numpy as np
        print("expectancy R:", round(tr.R.mean(), 3), "| winrate:",
              round((tr.R > 0).mean(), 3), "| sum R:", round(tr.R.sum(), 1),
              "| profit factor:", round(tr.R[tr.R>0].sum()/abs(tr.R[tr.R<0].sum()), 2))
        print("riesgo_pts: med", round(tr.risk_pts.median(),1), "| p10",
              round(tr.risk_pts.quantile(.1),1), "p90", round(tr.risk_pts.quantile(.9),1))
        print("R: min", round(tr.R.min(),2), "p5", round(tr.R.quantile(.05),2),
              "med", round(tr.R.median(),2), "p95", round(tr.R.quantile(.95),2), "max", round(tr.R.max(),2))
        print("exit reasons:", tr.exit_reason.value_counts().to_dict())
        print("por sesion:", tr.groupby("session").R.agg(["count","mean"]).round(3).to_dict())
        print("por direccion:", tr.groupby("direction").R.agg(["count","mean"]).round(3).to_dict())
