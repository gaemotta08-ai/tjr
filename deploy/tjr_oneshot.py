#!/usr/bin/env python3
"""
tjr_oneshot.py — Corrida UNICA (one-shot) de señales TJR para GitHub Actions (cron).

Este script NO toca ningún archivo de la estrategia ni de la ejecución.
Es un envoltorio delgado (thin wrapper) que:

  1. Baja ~7 dias de velas NQ 1m de Yahoo (NQ=F) — mismo patron que feed_yfinance.fetch_1m.
  2. Convierte el indice a tz America/New_York (lo que espera el motor TJR).
  3. Calcula la ULTIMA vela de 5min YA CERRADA (cero look-ahead).
  4. Arma la ventana de WINDOW_DAYS dias que termina en esa vela.
  5. Reusa la logica YA TESTEADA de live_runner:
        - señal_fresca()  -> corre engine.backtest() sobre la ventana
        - _fmt_alerta()   -> arma el texto de la alerta (parciales 50/25/25 + BE)
        - enviar_alerta() -> push a ntfy.sh
  6. Deduplica con un archivo JSON de estado (set de entry_time ya alertados) que
     el workflow commitea de vuelta al repo. Asi, aunque el cron corra cada 5min,
     la misma señal NO se manda dos veces.

Diseño "cero drift": TODO el edge vive en engine.backtest(), que se importa; aca no
se reimplementa NADA de la estrategia. Si live_runner cambia, esto lo sigue.

Uso local (Mac, para testear):
    python3 deploy/tjr_oneshot.py --dry-run
    python3 deploy/tjr_oneshot.py --ntfy-topic tjralrtgae123

En GitHub Actions se corre con --ntfy-topic (o via env TJR_NTFY_TOPIC) y sin --dry-run.
Salidas de proceso: 0 = ok (haya o no señal). !=0 solo si algo se rompio feo.
"""

import argparse
import json
import os
import sys

import pandas as pd
import yfinance as yf

# --- Rutas: el repo se lleva 2_backtest/ (engine.py + data.py). live_runner necesita
#     saber donde estan ANTES de importarse. La capa de ejecucion (Fede) es OPCIONAL
#     (live_runner ya la envuelve en try/except), asi que TJR_EJ_DIR puede no existir.
HERE = os.path.dirname(os.path.abspath(__file__))          # .../ENTREGA/deploy
ENTREGA = os.path.dirname(HERE)                            # .../ENTREGA
DEFAULT_BT_DIR = os.path.join(ENTREGA, "2_backtest")

os.environ.setdefault("TJR_BT_DIR", DEFAULT_BT_DIR)
# Si TJR_EJ_DIR no se seteo, lo apuntamos a algo inexistente a proposito: los imports
# de ejecucion en live_runner caen en el except y no rompen (entorno "solo señales").
os.environ.setdefault("TJR_EJ_DIR", os.path.join(ENTREGA, "_no_exec"))

sys.path.insert(0, ENTREGA)  # para poder importar live_runner

import live_runner as lr  # noqa: E402  (usa TJR_BT_DIR ya seteado)

COLS = ["open", "high", "low", "close", "volume"]
DEFAULT_STATE = os.path.join(HERE, "estado_senales.json")


def bajar_1m(ticker):
    """Baja NQ 1m de Yahoo y devuelve df tz=NY con columnas open..volume.
    Mismo patron que feed_yfinance.fetch_1m (period 7d = tope de historia 1m de Yahoo)."""
    df = yf.download(
        tickers=ticker, period="7d", interval="1m",
        progress=False, auto_adjust=False,
    )
    if df is None or df.empty:
        return None
    # Yahoo devuelve columnas MultiIndex (Price, Ticker) -> aplano al primer nivel.
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df = df.rename(columns=str.lower)
    faltan = [c for c in COLS if c not in df.columns]
    if faltan:
        print(f"[oneshot] faltan columnas {faltan}", flush=True)
        return None
    df = df[COLS].dropna()
    df = df[~df.index.duplicated(keep="first")].sort_index()
    # El indice viene tz-aware UTC -> el motor TJR trabaja en NY.
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert(lr.NY)
    return df


def cargar_estado(path):
    """Devuelve el set de keys (entry_time isoformat) ya alertadas."""
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("alertadas", []))
    except Exception as e:
        print(f"[oneshot] no pude leer estado ({e}), arranco vacio", flush=True)
        return set()


def guardar_estado(path, ya):
    """Persiste el set (ordenado, y recortado a las ultimas 500 para no crecer infinito)."""
    keys = sorted(ya)
    if len(keys) > 500:
        keys = keys[-500:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"alertadas": keys}, f, indent=2)


def main():
    ap = argparse.ArgumentParser(description="One-shot de señales TJR (GitHub Actions cron)")
    ap.add_argument("--symbol", default="NQ", help="Simbolo (default NQ)")
    ap.add_argument("--ticker", default="NQ=F", help="Ticker Yahoo (default NQ=F)")
    ap.add_argument("--ntfy-topic", default=os.environ.get("TJR_NTFY_TOPIC", "tjralrtgae123"),
                    help="Topic de ntfy.sh (o env TJR_NTFY_TOPIC)")
    ap.add_argument("--webhook", default=os.environ.get("TJR_WEBHOOK"),
                    help="Webhook JSON opcional")
    ap.add_argument("--state", default=DEFAULT_STATE, help="Archivo JSON de dedup")
    ap.add_argument("--dry-run", action="store_true",
                    help="Detecta y muestra la señal pero NO manda ntfy ni escribe estado")
    args = ap.parse_args()

    # 1) Datos
    df1m = bajar_1m(args.ticker)
    if df1m is None or len(df1m) < 50:
        n = 0 if df1m is None else len(df1m)
        print(f"[oneshot] datos insuficientes ({n} velas), salgo sin señal", flush=True)
        return 0

    # 2) Ultima vela de 5min YA CERRADA + ventana de WINDOW_DAYS (mismo contrato que csv-live)
    last_ts = df1m.index[-1]
    cerrada = last_ts.floor("5min") - lr.BAR
    win_start = cerrada - pd.Timedelta(days=lr.WINDOW_DAYS)
    avail_end = cerrada + lr.BAR
    window = df1m[(df1m.index >= win_start) & (df1m.index < avail_end)]
    if len(window) < 50:
        print(f"[oneshot] ventana chica ({len(window)} velas) hasta {cerrada}, salgo", flush=True)
        return 0

    # 3) Estado de dedup
    ya = cargar_estado(args.state)

    # 4) Config del motor (identico a live_runner.run: dict(DEFAULT) + symbol)
    cfg = dict(lr.tjr_engine.DEFAULT)
    cfg["symbol"] = args.symbol

    # 5) Detectar señal fresca (reusa 100% el codigo testeado)
    sig = lr.señal_fresca(cfg, window, cerrada, ya)
    if sig is None:
        print(f"[oneshot] {cerrada}  sin señal fresca", flush=True)
        return 0

    # 6) TP escalonados 1R/2R/3R (mismo calculo que live_runner.run, lineas ~359-363)
    risk_pts = abs(sig["entry"] - sig["stop"])
    sgn = 1 if sig["lado"] == "long" else -1
    tp1 = sig["entry"] + sgn * 1 * risk_pts
    tp2 = sig["entry"] + sgn * 2 * risk_pts
    tp3 = sig["entry"] + sgn * 3 * risk_pts

    titulo, cuerpo = lr._fmt_alerta(
        args.symbol, sig["lado"], sig["entry"], sig["stop"], tp1, tp2, tp3, cerrada
    )

    print(f"[oneshot] SEÑAL {titulo}", flush=True)
    print(cuerpo, flush=True)

    if args.dry_run:
        print("[oneshot] --dry-run: NO mando ntfy ni escribo estado", flush=True)
        return 0

    # 7) Push + persistir dedup
    lr.enviar_alerta(args.ntfy_topic, args.webhook, titulo, cuerpo)
    ya.add(sig["key"])
    guardar_estado(args.state, ya)
    print(f"[oneshot] alerta enviada y estado guardado ({len(ya)} keys)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
