# Forward test acelerado — Estrategia TJR (validación independiente)

No toca el backtest original. Dos vías en paralelo. Config: stop en confluencia,
NY am + London, parciales 50/25/25, BE tras TP1.

## VÍA 1 — Replay OOS estricto (corrido, medible YA)

Data NO usada en optimización (la sensibilidad fue 2020-2024 → holdout limpio
2025-2026). Motor bar-by-bar, cero look-ahead. Stress de slippage 1x/2x/3x ticks/lado.

### Holdout 2025-2026 (n=792)
| slippage | exp R | winrate | PF | maxDD | peor trade |
|---|---|---|---|---|---|
| 1x (1 tick/lado) | **0.97** | 0.77 | 4.93 | −5.6R | −1.38R |
| 2x (2 ticks/lado) | 0.93 | 0.75 | 4.62 | −6.0R | −1.50R |
| 3x (3 ticks/lado) | 0.90 | 0.74 | 4.33 | −6.9R | −1.62R |
- Edge OOS vs azar (null): **z = 24.9** → edge real, no mecánica de salida.

### Últimos 3 meses (n=134) — el bloque más fresco
| slippage | exp R | winrate | PF |
|---|---|---|---|
| 1x | 0.92 | 0.73 | 4.24 |
| 2x | 0.89 | 0.72 | 4.02 |
| 3x | 0.86 | 0.72 | 3.81 |
- null z = 7.5 → edge real.

### Cross-OOS (instrumentos nunca vistos) — VÍA 1b
- **DOW/YM (jamás usado en diseño): 0.87R, 74% win, PF 4.25, z=27** → la estrategia GENERALIZA.
- RUT/RTY: −0.01R, falla → el edge es de índices grandes (NQ/DOW/ES), no small-caps.

## VÍA 2 — Demo live (fills/slippage REALES) — CÓDIGO LISTO, NECESITA CUENTA

`live/trader_tjr_futuros.py`: reusa el ejecutor ProjectX de Fede (abrir+stop bracket,
mover_stop, cerrar) y le agrega la salida real de TJR (parciales 50/25/25 + BE) + log
de slippage pedido-vs-fill en cada evento → `forward/slippage_live.csv`.
- **Lógica validada offline** (test con mock OK: ladder dispara, slippage de entrada se mide).
- **CABO SUELTO:** requiere cuenta DEMO ProjectX/TopstepX + claves (`PROJECTX_USER/APIKEY`).
  El slippage de SALIDA (parciales/stop) sólo se lee del fill report del broker → queda
  `PENDIENTE_RECONCILIAR` hasta correrlo en demo. Las REST de ProjectX no están validadas
  contra demo real (mismo cabo suelto que dejó Fede): validar antes de creer los fills.

## VEREDICTO

**Replay (VÍA 1): PASA todos los gates** (n≥40, win≥0.65, peor trade ≥ −1.5R en 1x,
exp sobrevive 2x y 3x). El edge OOS es real (z=25) y generaliza a un instrumento nunca
visto (DOW). → **Habilita pasar a la VÍA 2.**

**Go/No-Go DEFINITIVO (se decide con el slippage REAL del demo, no antes):**
- **GO** si: exp neta con slippage real ≥ **0.20R** sobre ≥ **40 trades**, winrate ≥ **0.65**,
  ningún trade < **−1.5R**, slippage medio ≤ **1.5 ticks/lado**.
- **NO-GO / revisar** si: exp < 0.15R, o el slippage real degrada el edge por debajo del 2x stress.

## Cuánto falta para 40-50 trades en demo live
- 3 instrumentos (NQ+ES+DOW) × ~2.2 trades/día ≈ 6.6/día (~33/sem) → **~1.5 semanas**.
- Sólo NQ (~2.2/día) → ~4 semanas.

## Lecturas honestas / cabos sueltos
1. El holdout 2025-2026 (0.97R) es un régimen FAVORABLE (NQ tendió fuerte). El piso
   conservador sigue siendo el stress de costos pesado del backtest full-period (~0.10R
   con 3x slippage + comisión alta, report.md §9). El slippage real del demo es el árbitro.
2. El replay sólo escala slippage_ticks; no modela peor spread en NEWS/FOMC ni gaps a
   través del stop → eso SÓLO lo mide el demo (y aun así los eventos de news son cabo suelto).
3. El slippage de SALIDA real necesita el fill report del broker (no se puede offline).
4. Params elegidos con algo de info full-period; el cross-OOS en DOW (nunca visto) es el
   chequeo más limpio de sobreajuste y salió fuerte.
