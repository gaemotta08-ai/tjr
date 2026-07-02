#!/usr/bin/env python3
"""
feed_yfinance.py — Feeder de datos en vivo NQ 1m para live_runner.py (--source csv-live).

NO toca ningún archivo de la estrategia. Solo baja velas 1m de Yahoo (NQ=F) y las
va appendeando a un CSV con el formato que espera read_1m_csv():

    timestamp,open,high,low,close,volume     (timestamp ISO tz-aware)

live_runner.py tailea ese CSV y dispara señales cuando cierra una vela de 5min.

Uso (Terminal de la Mac, dejar corriendo):
    python3 feed_yfinance.py
    python3 feed_yfinance.py --csv /ruta/NQ_live_1m.csv --poll 30

Notas:
- Yahoo da 1m con leve delay y a veces saltea velas → sirve para PRACTICAR el flujo
  en paper, NO para juzgar fills reales. Para eso hace falta el feed del broker.
- 1m en Yahoo tiene tope de 7 días de historia. Se siembra 7d para dar contexto al
  motor (WINDOW_DAYS=6) y después appendea solo lo nuevo y CERRADO.
- Ctrl+C para cortar.
"""

import os
import sys
import time
import argparse

import pandas as pd
import yfinance as yf

DEFAULT_CSV = "/Users/sebastianmotta/tjr/ENTREGA/NQ_live_1m.csv"
COLS = ["open", "high", "low", "close", "volume"]


def fetch_1m(ticker, seed):
    """Baja 1m de Yahoo y devuelve un DataFrame tz-aware con columnas open..volume."""
    period = "7d" if seed else "1d"
    df = yf.download(
        tickers=ticker, period=period, interval="1m",
        progress=False, auto_adjust=False,
    )
    if df is None or df.empty:
        return None
    # Yahoo devuelve columnas MultiIndex (Price, Ticker) → aplano al primer nivel.
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df = df.rename(columns=str.lower)
    faltan = [c for c in COLS if c not in df.columns]
    if faltan:
        print(f"[feed] faltan columnas {faltan}, salteo", flush=True)
        return None
    df = df[COLS].dropna()
    df = df[~df.index.duplicated(keep="first")].sort_index()
    return df


def last_ts_del_csv(path):
    """Devuelve el ultimo timestamp ya escrito en el CSV, o None si no existe/vacio."""
    if not os.path.exists(path):
        return None
    try:
        prev = pd.read_csv(path)
        if len(prev) == 0:
            return None
        return pd.to_datetime(prev.iloc[-1, 0], utc=True)
    except Exception:
        return None


def append_nuevas(path, df, last_ts):
    """Appendea filas nuevas y CERRADAS (excluye la ultima 1m en curso).
    Devuelve el nuevo last_ts (tz-aware UTC) o el mismo si no hubo nada."""
    if df is None or len(df) < 2:
        return last_ts
    en_curso = df.index[-1]                      # la vela mas nueva puede estar a medio formar
    idx_utc = df.index.tz_convert("UTC")
    mask = idx_utc < en_curso.tz_convert("UTC")  # solo velas ya cerradas
    if last_ts is not None:
        mask &= idx_utc > last_ts
    nuevas = df[mask]
    if len(nuevas) == 0:
        return last_ts

    out = nuevas.reset_index()
    out.columns = ["timestamp"] + COLS
    out["timestamp"] = out["timestamp"].apply(lambda t: pd.Timestamp(t).isoformat())
    escribir_header = not os.path.exists(path) or os.path.getsize(path) == 0
    out.to_csv(path, mode="a", header=escribir_header, index=False)

    nuevo_last = nuevas.index[-1].tz_convert("UTC")
    print(f"[feed] +{len(nuevas)} velas  ultima {nuevas.index[-1]}  (total nuevo hasta {nuevo_last})", flush=True)
    return nuevo_last


def main():
    ap = argparse.ArgumentParser(description="Feeder NQ 1m (Yahoo) para live_runner csv-live")
    ap.add_argument("--csv", default=DEFAULT_CSV, help="CSV destino que tailea live_runner")
    ap.add_argument("--ticker", default="NQ=F", help="Ticker Yahoo (default NQ=F)")
    ap.add_argument("--poll", type=float, default=30.0, help="Segundos entre consultas")
    args = ap.parse_args()

    print(f"[feed] destino={args.csv} ticker={args.ticker} poll={args.poll}s", flush=True)
    last_ts = last_ts_del_csv(args.csv)
    seed = last_ts is None
    if seed:
        print("[feed] sembrando 7 dias de historia (para el contexto del motor)...", flush=True)

    while True:
        try:
            df = fetch_1m(args.ticker, seed)
            last_ts = append_nuevas(args.csv, df, last_ts)
            seed = False
        except KeyboardInterrupt:
            print("\n[feed] cortado por el usuario", flush=True)
            return 0
        except Exception as e:
            print(f"[feed] error (sigo): {e}", flush=True)
        time.sleep(args.poll)


if __name__ == "__main__":
    sys.exit(main())
