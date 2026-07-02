"""
live_runner.py — Loop de DATOS EN VIVO para el forward-test de TJR.

Es la pieza que faltaba: conecta datos que se actualizan en tiempo real → el motor
TJR (engine.py) → la ejecución de futuros ya validada (ejecutor_futuros.py +
trader_real_futuros.py). NO reescribe la estrategia ni el ejecutor: los importa
tal cual y los orquesta.

CÓMO GENERA SEÑAL SIN TOCAR EL MOTOR (★ el truco):
  engine.backtest() es BATCH (procesa un DataFrame entero). Para vivo NO lo reescribo:
  en cada cierre de vela de 5min re-corro backtest() sobre una VENTANA CORTA (~6 días)
  que termina en la vela recién cerrada. Si aparece un trade cuyo entry_time es esa
  vela → es una señal FRESCA → la disparo. Reusa 100% del código de señal ya testeado
  (mismo sweep→BOS→FVG→stop), cero look-ahead (la ventana solo tiene velas cerradas).

SEGURIDAD:
  - Por defecto corre en PAPER (ejecutor simulado local, SIN internet ni credenciales).
    Sirve para (a) replay acelerado out-of-sample y (b) validar todo el cableado hoy.
  - --demo usa la API demo de Tradovate (requiere env vars). --live está bloqueado
    salvo que se pase --confirmo-live-real (cuenta real = la de la mamá).
  - KILL SWITCH: si aparece el archivo KILL_SWITCH en la carpeta, aplana todo y frena.
    Es el ÚNICO punto de control humano.

USO:
  # replay acelerado sobre la cola out-of-sample (paper, offline):
  python3 live_runner.py --source replay --symbol NQ --start 2026-04-01
  # vivo desde un CSV que un feed externo va appendeando (paper):
  python3 live_runner.py --source csv-live --csv /ruta/NQ_live_1m.csv
  # matar en caliente:  touch /Users/sebastianmotta/tjr/ENTREGA/KILL_SWITCH
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

import pandas as pd

# ── rutas de los proyectos existentes (no se tocan, solo se importan) ──────────
# En la Mac usan el default. En un server (Oracle/Linux) se sobreescriben con las
# env vars TJR_BT_DIR / TJR_EJ_DIR sin tocar nada del codigo.
BT_DIR = os.environ.get("TJR_BT_DIR", "/Users/sebastianmotta/tjr/ENTREGA/2_backtest")          # engine.py + data.py
EJ_DIR = os.environ.get("TJR_EJ_DIR", "/Users/sebastianmotta/Desktop/HANDOFF_fede/ejecucion")  # ejecutor + trader
for _d in (BT_DIR, EJ_DIR):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import data as tjr_data          # noqa: E402  (load_1m, resample, NY)
import engine as tjr_engine      # noqa: E402  (backtest, DEFAULT)

# La capa de ejecucion (Fede) es OPCIONAL: solo hace falta para correr en modo
# ejecucion/paper con run(). En un entorno "solo senales" (ej: GitHub Actions, que
# reusa senal_fresca/_fmt_alerta/enviar_alerta) no esta presente y no debe romper el
# import del modulo. Si falta, run()/PaperEjecutor no se pueden usar, pero el resto si.
try:
    from ejecutor_futuros import EjecutorFuturos, MICRO, PUNTO, TICK  # noqa: E402
    from trader_real_futuros import TraderRealFuturos                 # noqa: E402
    _EJECUCION_OK = True
except ImportError as _e:
    EjecutorFuturos = None
    TraderRealFuturos = None
    MICRO = {}
    PUNTO = {}
    TICK = {}
    _EJECUCION_OK = False
    _EJECUCION_ERR = _e

NY = tjr_data.NY
HERE = os.path.dirname(os.path.abspath(__file__))
KILL_FILE = os.path.join(HERE, "KILL_SWITCH")
DECISIONS_LOG = os.path.join(HERE, "live_decisiones.csv")
TRADES_LOG = os.path.join(HERE, "live_trades_paper.csv")

WINDOW_DAYS = 6          # ventana de 1m que se le pasa al motor en cada cierre
SIGNAL_LOOKBACK = 3      # una señal es "fresca" si su entry_time está en las últimas N velas 5min
BAR = pd.Timedelta("5min")


# ══════════════════════════════════════════════════════════════════════════════
# EJECUTOR PAPER — simula fills/stops/targets local. Implementa la MISMA interfaz
# que EjecutorFuturos para que TraderRealFuturos lo use sin cambiarle nada.
# ══════════════════════════════════════════════════════════════════════════════
class PaperEjecutor:
    def __init__(self, equity=50000.0, slippage_ticks=1.0):
        self.equity = float(equity)
        self.slip_ticks = float(slippage_ticks)
        self._pos = {}      # inst -> dict posición abierta
        self.cerrados = []  # historial de trades resueltos (para el reporte)

    def balance(self):
        return self.equity

    def posicion(self, inst):
        return self._pos.get(inst)

    def contratos_por_riesgo(self, symbol, equity, riesgo_pct, stop_pts, max_contratos=None):
        # reusa EXACTO el sizing testeado del ejecutor real (no depende de self)
        return EjecutorFuturos.contratos_por_riesgo(
            self, symbol, equity, riesgo_pct, stop_pts, max_contratos)

    def abrir(self, inst, lado, contratos, stop_price, target_price=None, entry_ref=None):
        # fill simulado = precio pedido + slippage ADVERSO de slip_ticks
        tick = TICK.get(inst, 0.25)
        slip = self.slip_ticks * tick
        base = entry_ref if entry_ref is not None else stop_price
        fill = base + slip if lado == "long" else base - slip
        self._pos[inst] = {"symbol": inst, "lado": lado, "contratos": contratos,
                           "entrada": round(fill, 4), "stop": stop_price,
                           "target": target_price, "abierto_ts": None}
        return {"orderId": f"PAPER-{len(self.cerrados)+1}", "fill": fill}

    def mover_stop(self, inst, nuevo_stop):
        if inst in self._pos:
            self._pos[inst]["stop"] = nuevo_stop
        return {"symbol": inst, "nuevo_stop": nuevo_stop}

    def cerrar(self, inst, precio=None, motivo="manual"):
        pos = self._pos.pop(inst, None)
        if not pos:
            return {"estado": "ya estaba flat"}
        px = precio if precio is not None else pos["entrada"]
        self._resolver(pos, px, motivo)
        return {"symbol": inst, "cerrado": pos["contratos"]}

    def reconciliar(self, inst, esperado):
        real = self.posicion(inst)
        if esperado is None and real is None:
            return True, "ambos flat"
        if bool(esperado) != bool(real):
            return False, "MISMATCH pos/flat"
        return True, "coinciden"

    # ── simulación de salida (stop/target) sobre cada vela nueva ───────────────
    def check_exits(self, bar_high, bar_low, ts):
        """Resuelve posiciones abiertas si la vela toca stop o target."""
        for inst, pos in list(self._pos.items()):
            stop, tgt, lado = pos["stop"], pos["target"], pos["lado"]
            golpe = None
            if lado == "long":
                if bar_low <= stop:            golpe = (stop, "stop")
                elif tgt and bar_high >= tgt:  golpe = (tgt, "target")
            else:  # short
                if bar_high >= stop:           golpe = (stop, "stop")
                elif tgt and bar_low <= tgt:   golpe = (tgt, "target")
            if golpe:
                self._pos.pop(inst)
                self._resolver(pos, golpe[0], golpe[1], ts)

    def _resolver(self, pos, px, motivo, ts=None):
        lado, entry = pos["lado"], pos["entrada"]
        signo = 1 if lado == "long" else -1
        stop_pts = abs(entry - pos["stop"]) or 1e-9
        r = signo * (px - entry) / stop_pts
        usd = signo * (px - entry) * PUNTO.get(pos["symbol"], 1.0) * pos["contratos"]
        self.equity += usd
        rec = {"ts": ts, "inst": pos["symbol"], "lado": lado, "entrada": round(entry, 2),
               "salida": round(px, 2), "motivo": motivo, "R": round(r, 3),
               "usd": round(usd, 2), "equity": round(self.equity, 2)}
        self.cerrados.append(rec)
        _append_csv(TRADES_LOG, rec)


# ══════════════════════════════════════════════════════════════════════════════
# FUENTES DE DATOS 1m (tz America/New_York, formato de data.py)
# ══════════════════════════════════════════════════════════════════════════════
def read_1m_csv(path):
    """Parsea un CSV timestamp,open,high,low,close,volume → 1m tz=NY (igual que load_1m)."""
    df = pd.read_csv(path)
    tcol = df.columns[0]
    ts = pd.to_datetime(df[tcol], utc=True)
    df = df.rename(columns={tcol: "ts"})
    df["ts"] = ts.dt.tz_convert(NY)
    df = df.set_index("ts").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df[~df.index.duplicated(keep="first")]


def replay_bars(data_path, start=None):
    """Generador que emite cierres de vela 5min sobre la cola histórica (out-of-sample).
    En cada paso devuelve (t_close_5m, window_1m) simulando 'solo velas cerradas'."""
    df1m = read_1m_csv(data_path)
    if start:
        df1m = df1m[df1m.index >= pd.Timestamp(start, tz=NY)]
    bars5 = tjr_data.resample(df1m, "5min")
    warm = int(pd.Timedelta(days=WINDOW_DAYS) / BAR)  # saltea el calentamiento
    for t_close in bars5.index[warm:]:
        avail_end = t_close + BAR                      # la 5min cierra recién acá
        win_start = avail_end - pd.Timedelta(days=WINDOW_DAYS)
        window = df1m[(df1m.index >= win_start) & (df1m.index < avail_end)]
        if len(window) < 50:
            continue
        yield t_close, window


def csv_live_bars(path, poll=5.0):
    """Generador vivo: tailea un CSV que un feed externo va appendeando. Dispara cuando
    detecta que cerró una nueva vela de 5min (aparece el primer 1m de la 5min siguiente)."""
    ultimo = None
    while True:
        if not os.path.exists(path):
            time.sleep(poll); continue
        try:
            df1m = read_1m_csv(path)
        except Exception:
            time.sleep(poll); continue
        if len(df1m) < 50:
            time.sleep(poll); continue
        last_ts = df1m.index[-1]
        cerrada = last_ts.floor("5min") - BAR   # la última 5min COMPLETA
        if ultimo is None or cerrada > ultimo:
            ultimo = cerrada
            avail_end = cerrada + BAR
            win_start = avail_end - pd.Timedelta(days=WINDOW_DAYS)
            window = df1m[(df1m.index >= win_start) & (df1m.index < avail_end)]
            yield cerrada, window
        time.sleep(poll)


# ══════════════════════════════════════════════════════════════════════════════
# DETECCIÓN DE SEÑAL FRESCA (re-backtest sobre la ventana)
# ══════════════════════════════════════════════════════════════════════════════
def señal_fresca(cfg, window, t_close, ya_disparadas):
    """Corre el motor sobre la ventana y devuelve la señal cuya entry_time es reciente
    (últimas SIGNAL_LOOKBACK velas) y todavía no disparada. None si no hay."""
    try:
        df_tr, _ = tjr_engine.backtest(cfg=cfg, df1m=window)
    except Exception as e:
        print(f"[{t_close}] motor error: {e}")
        return None
    if df_tr is None or len(df_tr) == 0:
        return None
    df_tr = df_tr.sort_values("entry_time")
    corte = t_close + BAR - SIGNAL_LOOKBACK * BAR
    for _, row in df_tr.iterrows():
        et = pd.Timestamp(row["entry_time"])
        if et.tzinfo is None:
            et = et.tz_localize(NY)
        if et < corte:
            continue
        key = et.isoformat()
        if key in ya_disparadas:
            continue
        d = row["direction"]
        lado = d if d in ("long", "short") else ("long" if float(d) > 0 else "short")
        return {"key": key, "entry_time": et, "lado": lado,
                "entry": float(row["entry"]), "stop": float(row["stop"])}
    return None


# ══════════════════════════════════════════════════════════════════════════════
# LOOP PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════
def run(args):
    if not _EJECUCION_OK:
        print("BLOQUEADO: falta la capa de ejecucion (ejecutor_futuros / "
              "trader_real_futuros). run() necesita TJR_EJ_DIR apuntando a "
              f"la carpeta ejecucion/. Detalle: {_EJECUCION_ERR}")
        return
    cfg = dict(tjr_engine.DEFAULT)
    cfg["symbol"] = args.symbol

    # --- ejecutor según modo ---
    if args.mode == "paper":
        ej = PaperEjecutor(equity=args.equity, slippage_ticks=args.slippage_ticks)
        print(f"MODO PAPER (simulado, offline) · equity ${args.equity:,.0f} · "
              f"slippage {args.slippage_ticks} ticks")
    else:
        demo = (args.mode == "demo")
        if not demo and not args.confirmo_live_real:
            print("BLOQUEADO: --live requiere --confirmo-live-real (cuenta real).")
            return
        ej = EjecutorFuturos(demo=demo)   # autentica con env vars TRADOVATE_*
        print(f"MODO {'DEMO' if demo else 'LIVE-REAL'} vía Tradovate")

    trader = TraderRealFuturos(ej, riesgo=args.riesgo, max_dia=args.max_dia,
                               usar_micro=args.micro, max_contratos=args.max_contratos)

    # --- fuente de datos ---
    if args.source == "replay":
        fuente = replay_bars(os.path.join(args.data, f"{args.symbol}_1m.csv"), start=args.start)
    else:
        fuente = csv_live_bars(args.csv, poll=args.poll)

    ya = set()
    n_señales = 0
    # --- freno diario por perdida bruta (config validada por Monte Carlo) ---
    n_frenos = 0
    perdida_dia = {}            # fecha NY -> perdida BRUTA acumulada en R
    n_cerrados_vistos = 0       # cuantos trades cerrados ya contabilizamos
    risk_ref = args.equity * args.riesgo   # 1R en USD (0.5% de $50k = $250)
    stop_R = args.stop_diario_r
    if stop_R > 0:
        print(f"Freno diario ACTIVO: cortar entradas tras -{stop_R:.0f}R de perdida "
              f"bruta en el dia (~${stop_R * risk_ref:,.0f}).")
    else:
        print("Freno diario DESACTIVADO (--stop-diario-R 0).")
    if args.ntfy_topic or args.alerta_webhook:
        destinos = []
        if args.ntfy_topic:
            destinos.append(f"ntfy topic '{args.ntfy_topic}'")
        if args.alerta_webhook:
            destinos.append("webhook")
        print("Alertas al celular ACTIVAS: " + " + ".join(destinos))
    else:
        print("Alertas al celular DESACTIVADAS (pasa --ntfy-topic <topic> para activarlas).")
    print(f"Arrancado. Kill switch: touch {KILL_FILE}\n" + "-" * 60)

    for t_close, window in fuente:
        # 0) kill switch: aplanar todo y salir
        if os.path.exists(KILL_FILE):
            inst = MICRO.get(args.symbol, args.symbol) if args.micro else args.symbol
            if ej.posicion(inst):
                ej.cerrar(inst)
            print(f"[{t_close}] KILL SWITCH detectado → aplanado y frenado.")
            break

        # 1) en paper, resolver stops/targets con la última vela cerrada
        if isinstance(ej, PaperEjecutor) and len(window):
            b = window.iloc[-1]
            ej.check_exits(float(b["high"]), float(b["low"]), t_close)

        # 1b) contabilizar perdida bruta del dia de los trades recien cerrados.
        # (solo paper: EjecutorFuturos no expone .cerrados; en demo/live habria
        #  que alimentar esto con eventos de fill del broker)
        cerrados = getattr(ej, "cerrados", None)
        if cerrados is not None and len(cerrados) > n_cerrados_vistos:
            for c in cerrados[n_cerrados_vistos:]:
                if c.get("ts") is not None and c.get("R", 0.0) < 0:
                    d = pd.Timestamp(c["ts"]).tz_convert(NY).date()
                    perdida_dia[d] = perdida_dia.get(d, 0.0) + (-c["R"])
            n_cerrados_vistos = len(cerrados)

        # 2) buscar señal fresca re-corriendo el motor
        sig = señal_fresca(cfg, window, t_close, ya)
        if not sig:
            continue
        ya.add(sig["key"])
        # freno diario: si ya perdimos stop_R en bruto hoy, no tomar mas entradas
        dia = sig["entry_time"].tz_convert(NY).date()
        if stop_R > 0 and perdida_dia.get(dia, 0.0) >= stop_R:
            n_frenos += 1
            _append_csv(DECISIONS_LOG, {
                "ts": t_close, "entry_time": sig["entry_time"], "symbol": args.symbol,
                "lado": sig["lado"], "entry": round(sig["entry"], 2),
                "stop": round(sig["stop"], 2), "accion": "FRENO_DIARIO"})
            print(f"[{t_close}] FRENO DIARIO ({perdida_dia[dia]:.1f}R perdidos hoy) "
                  f"→ salteo señal {sig['lado']} @ {sig['entry']:.2f}")
            continue
        day = sig["entry_time"].normalize()
        r = trader.procesar(day, args.symbol, sig["lado"], sig["entry"], sig["stop"])
        n_señales += 1
        # Plan escalonado 50/25/25 a 1R/2R/3R + breakeven tras TP1. Replica la gestion
        # del backtest (parciales + BE) sobre la que se mide el edge; los TP a liquidez
        # exactos viven en el motor y no se devuelven por señal, asi que se aproximan por R.
        risk_pts = abs(sig["entry"] - sig["stop"])
        sgn = 1 if sig["lado"] == "long" else -1
        tp1 = sig["entry"] + sgn * 1 * risk_pts
        tp2 = sig["entry"] + sgn * 2 * risk_pts
        tp3 = sig["entry"] + sgn * 3 * risk_pts
        _append_csv(DECISIONS_LOG, {
            "ts": t_close, "entry_time": sig["entry_time"], "symbol": args.symbol,
            "lado": sig["lado"], "entry": round(sig["entry"], 2),
            "stop": round(sig["stop"], 2),
            "tp1": round(tp1, 2), "tp2": round(tp2, 2), "tp3": round(tp3, 2),
            "accion": str(r)})
        print(f"[{t_close}] SEÑAL {sig['lado']} @ {sig['entry']:.2f} "
              f"stop {sig['stop']:.2f} TP1 {tp1:.2f} TP2 {tp2:.2f} TP3 {tp3:.2f} → {r}")
        # push al celular con los niveles exactos (no frena el loop si falla la red)
        titulo, cuerpo = _fmt_alerta(args.symbol, sig["lado"], sig["entry"], sig["stop"],
                                     tp1, tp2, tp3, t_close)
        enviar_alerta(args.ntfy_topic, args.alerta_webhook, titulo, cuerpo)

    # --- cierre ---
    print("-" * 60)
    print(f"Fin. Señales: {n_señales} · frenos diarios: {n_frenos}")
    if isinstance(ej, PaperEjecutor):
        cer = ej.cerrados
        if cer:
            rs = [c["R"] for c in cer]
            wins = sum(1 for x in rs if x > 0)
            print(f"Paper: {len(cer)} trades · exp {sum(rs)/len(rs):+.3f}R · "
                  f"win {wins/len(cer):.0%} · equity ${ej.equity:,.0f}")
    print(trader.resumen_slippage())


def _fmt_alerta(symbol, lado, entry, stop, tp1, tp2, tp3, t_close):
    """Arma titulo (ASCII, para el header de ntfy) y cuerpo de la alerta.
    Manda el plan escalonado completo para que mama arme el bracket con parciales:
    50% a TP1, 25% a TP2, 25% a TP3, y stop a breakeven cuando toca TP1."""
    direccion = "LONG" if lado == "long" else "SHORT"
    riesgo_pts = abs(entry - stop)
    titulo = f"TJR {symbol} {direccion} @ {entry:.2f}"
    cuerpo = (
        f"{direccion} {symbol}\n"
        f"Entry:  {entry:.2f}\n"
        f"Stop:   {stop:.2f}  ({riesgo_pts:.1f} pts)\n"
        f"TP1 50%: {tp1:.2f}  (1R)\n"
        f"TP2 25%: {tp2:.2f}  (2R)\n"
        f"TP3 25%: {tp3:.2f}  (3R)\n"
        f">> stop a BREAKEVEN al tocar TP1\n"
        f"Senal:  {t_close}"
    )
    return titulo, cuerpo


def enviar_alerta(ntfy_topic, webhook, titulo, cuerpo):
    """Manda la alerta a ntfy.sh y/o a un webhook JSON generico.
    Todo va envuelto en try/except: una falla de red NUNCA frena el loop."""
    if ntfy_topic:
        try:
            req = urllib.request.Request(
                f"https://ntfy.sh/{ntfy_topic}",
                data=cuerpo.encode("utf-8"),
                headers={"Title": titulo, "Priority": "high", "Tags": "chart_with_upwards_trend"},
            )
            urllib.request.urlopen(req, timeout=8)
        except Exception as e:  # noqa: BLE001
            print(f"  (aviso: fallo ntfy: {e})")
    if webhook:
        try:
            payload = json.dumps({"titulo": titulo, "texto": cuerpo}).encode("utf-8")
            req = urllib.request.Request(
                webhook, data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=8)
        except Exception as e:  # noqa: BLE001
            print(f"  (aviso: fallo webhook: {e})")


def _append_csv(path, row):
    existe = os.path.exists(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if not existe:
            w.writeheader()
        w.writerow(row)


def main():
    p = argparse.ArgumentParser(description="Forward-test en vivo de TJR (datos → motor → ejecución)")
    p.add_argument("--source", choices=["replay", "csv-live"], default="replay")
    p.add_argument("--symbol", default="NQ")
    p.add_argument("--start", default=None, help="replay: fecha inicio out-of-sample (YYYY-MM-DD)")
    p.add_argument("--data", default="/Users/sebastianmotta/Documents/Gae Lab/Trading/Fede_Ecces/bot_fede/data",
                   help="replay: carpeta con los CSV {symbol}_1m.csv")
    p.add_argument("--csv", default=None, help="csv-live: ruta del CSV que appendea el feed")
    p.add_argument("--poll", type=float, default=5.0, help="csv-live: segundos entre chequeos")
    p.add_argument("--mode", choices=["paper", "demo", "live"], default="paper")
    p.add_argument("--confirmo-live-real", action="store_true", help="destraba --mode live (cuenta real)")
    p.add_argument("--equity", type=float, default=50000.0)
    p.add_argument("--riesgo", type=float, default=0.005, help="riesgo por trade (0.005 = 0.5%%)")
    p.add_argument("--stop-diario-R", type=float, default=3.0, dest="stop_diario_r",
                   help="freno diario: cortar entradas del dia tras esta perdida BRUTA en R "
                        "(0 = desactivado). Default 3R = la config validada por Monte Carlo.")
    p.add_argument("--max-dia", type=int, default=4, dest="max_dia")
    p.add_argument("--max-contratos", type=int, default=20, dest="max_contratos")
    p.add_argument("--micro", action="store_true", default=True, help="operar el micro (MNQ) en cuenta chica")
    p.add_argument("--slippage-ticks", type=float, default=1.0, dest="slippage_ticks",
                   help="paper: ticks de slippage adverso simulado")
    p.add_argument("--ntfy-topic", default=os.environ.get("TJR_NTFY_TOPIC"), dest="ntfy_topic",
                   help="ntfy.sh: topic al que mandar la alerta al celular "
                        "(o env TJR_NTFY_TOPIC). Sin esto, no manda push.")
    p.add_argument("--alerta-webhook", default=os.environ.get("TJR_ALERTA_WEBHOOK"), dest="alerta_webhook",
                   help="URL de un webhook JSON generico (Telegram/Discord/etc) "
                        "o env TJR_ALERTA_WEBHOOK. Opcional.")
    args = p.parse_args()
    if args.source == "csv-live" and not args.csv:
        p.error("--source csv-live requiere --csv <ruta>")
    run(args)


if __name__ == "__main__":
    main()
