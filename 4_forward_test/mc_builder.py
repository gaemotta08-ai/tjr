#!/usr/bin/env python3
"""
Monte Carlo dias-para-pasar vs reglas MFFU $50K Builder.
Bootstrap por DIA (remuestrea dias reales completos del paper forward-test)
para preservar el clustering intradia y la distribucion de trades/dia.

Reglas Builder (evaluacion):
  target = +$3,000
  max drawdown = $2,000  (modo EOD, trailing sobre balance de cierre, se congela en el balance inicial)
  daily loss limit = $1,000  (HARD: tocarlo = cuenta reprobada)
  sin consistency rule en evaluacion
Uso: python3 mc_builder.py
"""
import pandas as pd, numpy as np, os

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "..", "live_trades_paper.csv")

START = 50_000.0
TARGET = 3_000.0
MAXDD = 2_000.0
DAILY_LIMIT = 1_000.0
N_SIMS = 50_000
MAX_DAYS = 120           # horizonte de evaluacion
rng = np.random.default_rng(42)

df = pd.read_csv(CSV)
df["ts"] = pd.to_datetime(df["ts"], utc=True)
df["day"] = df["ts"].dt.tz_convert("America/New_York").dt.date
# lista de dias reales, cada uno = secuencia ordenada de R
dias = [g["R"].values for _, g in df.groupby("day")]
n_dias = len(dias)


def simular(risk_usd, self_stop_R=None, cap_trades=None):
    """Devuelve dict con probabilidades y dias-para-pasar."""
    resultados = []  # 'pass' / 'bust' / 'timeout'
    dias_pasar = []
    for _ in range(N_SIMS):
        eq = START
        peak = START
        dd_line = START - MAXDD
        estado = "timeout"
        for d in range(1, MAX_DAYS + 1):
            seq = dias[rng.integers(n_dias)]
            if cap_trades is not None:
                seq = seq[:cap_trades]
            pnl_dia = 0.0
            perd_dia = 0.0
            for R in seq:
                usd = R * risk_usd
                eq += usd
                pnl_dia += usd
                if usd < 0:
                    perd_dia += -usd
                # firm daily loss limit -> bust inmediato
                if pnl_dia <= -DAILY_LIMIT:
                    estado = "bust"; break
                # firm max drawdown intradia
                if eq <= dd_line:
                    estado = "bust"; break
                # freno propio: cortar el dia tras perder self_stop_R en R
                if self_stop_R is not None and perd_dia >= self_stop_R * risk_usd:
                    break
            if estado == "bust":
                break
            # cierre de dia: actualizar trailing EOD dd (se congela en START)
            if eq > peak:
                peak = eq
            dd_line = min(max(dd_line, eq - MAXDD), START)
            if eq <= dd_line:
                estado = "bust"; break
            # target?
            if eq - START >= TARGET:
                estado = "pass"; dias_pasar.append(d); break
        resultados.append(estado)
    r = np.array(resultados)
    dp = np.array(dias_pasar)
    return {
        "p_pass": (r == "pass").mean(),
        "p_bust": (r == "bust").mean(),
        "p_timeout": (r == "timeout").mean(),
        "dias_mediana": float(np.median(dp)) if len(dp) else None,
        "dias_p90": float(np.percentile(dp, 90)) if len(dp) else None,
        "dias_peor": float(dp.max()) if len(dp) else None,
    }


def linea(nombre, res):
    md = res["dias_mediana"]; p90 = res["dias_p90"]
    md = f"{md:.0f}" if md else "-"
    p90 = f"{p90:.0f}" if p90 else "-"
    print(f"{nombre:<42} pass={res['p_pass']*100:5.1f}%  bust={res['p_bust']*100:5.1f}%  "
          f"timeout={res['p_timeout']*100:4.1f}%  dias(mediana/p90)={md}/{p90}")


print(f"Dias reales en el pool: {n_dias}  |  sims: {N_SIMS}  |  horizonte: {MAX_DAYS} dias\n")
print("=== SIN freno propio (opera todo el dia como en el paper) ===")
linea("riesgo 0.5% ($250/R)", simular(250))
linea("riesgo 1.0% ($500/R)", simular(500))

print("\n=== CON freno propio: cortar el dia tras -3R de perdida ===")
linea("riesgo 0.5% ($250/R), stop -3R", simular(250, self_stop_R=3))
linea("riesgo 1.0% ($500/R), stop -3R", simular(500, self_stop_R=3))

print("\n=== CON freno propio -2R + cap 4 trades/dia ===")
linea("riesgo 0.5% ($250/R), stop -2R, cap4", simular(250, self_stop_R=2, cap_trades=4))
linea("riesgo 1.0% ($500/R), stop -2R, cap4", simular(500, self_stop_R=2, cap_trades=4))

print("\n=== CON freno propio -3R + cap 6 trades/dia (recomendado a evaluar) ===")
linea("riesgo 0.5% ($250/R), stop -3R, cap6", simular(250, self_stop_R=3, cap_trades=6))
