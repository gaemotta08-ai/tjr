# Estrategia TJR — extracción + backtest + plan de fondeo (handoff)

Paquete listo para retomar en otro chat. Todo hecho sobre la estrategia del trader
**TJR** (SMC/ICT), extraída de su canal de YouTube y backtesteada en futuros NQ.

## TL;DR (lo que se concluyó)
- **Estrategia:** killzones London/NY → barrido de liquidez → break of structure (cierre)
  → entrada en FVG (50%) → **stop estructural del lado del barrido** → TP a liquidez
  opuesta escalonado (parciales 50/25/25) → **breakeven tras TP1**.
- **Backtest NQ 2017-2026 (9,5 años):** +0,40 R/trade, 72% win, PF 2,84, maxDD −16R.
  **Edge real validado** (null de Monte Carlo z=13), sin overfitting (sensibilidad plana,
  walk-forward 8/8 años OOS positivos, shorts también ganan). ES es marginal.
- **Caveat:** scalper de winrate alto y edge chico → **sensible a costos** (con 3× slippage
  cae a 0,10R). Falta forward test en vivo. Riesgo de cola (gaps/news) no modelado.
- **Mejoras testeadas:** stop en confluencia (mejor, 0,57R) y sesión NY > London.
- **Plan de fondeo:** TJR/NQ NO va en HyroTrader (cripto). Con firma **1-step de futuros**
  + estrategia tuneada + 0,5-0,6% riesgo → **1er payout en ~9 semanas** (sin forward test),
  ~$2.250 en cuenta $50k. Mejor firma para esta estrategia: **Alpha Futures Premium**.

## Qué hay en cada carpeta

### 1_estrategia/
- `estrategia.json` — spec mecánico de TJR (reglas que repite en ≥3 videos vs ruido),
  con foco en salidas (stop/TP/breakeven) y citas textuales.
- `pseudocodigo.py` — la estrategia como pseudocódigo Python (compila).

### 2_backtest/
- `report.md` — **EMPEZÁ POR ACÁ.** Reporte completo: rendimiento, por año/sesión/dirección,
  validación de edge (null), overfitting (IS/OOS, walk-forward, sensibilidad), ablaciones,
  Monte Carlo de riesgo, prob. de pasar prop firm, stress de costos, conclusiones.
- `report.json` / `cost_stress.json` — los números crudos.
- Código del motor (reproducible): `data.py` (carga/resampleo), `engine.py` (detectores SMC
  + backtest + null), `metrics.py`, `analyze.py` (corre todo el análisis), `plan.py` y
  `plan2.py` (simulación del plan de fondeo y comparación de firmas).
- `trades_NQ.csv`, `trades_tuned_confluence.csv`, `equity_NQ.csv` — trades y curva.

### 3_firmas/
- `firms_1step.md` — 6 prop firms de futuros 1-step con reglas oficiales (jun-2026):
  Alpha Futures, MyFundedFutures, Take Profit Trader, Apex, Topstep, Tradeify. Tabla
  comparativa + ranking para esta estrategia.

## Para reproducir el backtest (otro chat / otra máquina)
Necesita datos 1-min de NQ/ES (no incluidos por tamaño, ~200MB c/u). En esta máquina están en
`~/Desktop/estrategia fede secees/bot_fede/data/NQ_1m.csv` (formato: timestamp,open,high,low,close,volume).
Ajustar `DATA_DIR` en `data.py`. Luego: `python3 analyze.py all` (genera report.json),
`python3 plan2.py` (plan de fondeo). Requiere pandas, numpy, scipy.

## Pendiente / próximos pasos
1. Forward test / paper 1-2 meses antes de plata real.
2. Re-correr con data del broker propio (rollovers correctos).
3. Stress de slippage 2-3× como piso de costos.
4. (Opcional) re-correr TJR en BTC si se quiere usar HyroTrader.
5. Plan multi-cuenta para escalar el ingreso (no más % por cuenta).
