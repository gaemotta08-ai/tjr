# Backtest exhaustivo — Estrategia mecanica de TJR (SMC/ICT)

Datos: NQ y ES futuros, 1-min, 2017-2026 (~9.5 anios). Entradas en killzones London + NY am. Resultados en multiplos de R (riesgo inicial), netos de costos (comision 0.5pt + slippage 1 tick/lado). Sin look-ahead (swings confirmados, FVG solo del impulso, niveles de dias/sesiones previas). Un trade a la vez.

## 1. Resumen ejecutivo
- **NQ (full):** n=5191 | exp=0.3962R | win=0.7241 | PF=2.84 | sumR=2056.9 | maxDD=-16.3R | ret/DD=126.25
- **ES (full):** n=4993 | exp=0.0566R | win=0.5177 | PF=1.236 | sumR=282.7 | maxDD=-99.5R | ret/DD=2.84
- **Edge real vs azar:** NQ z=13.2 (edge real (z>3)); ES z=10.28 (edge real (z>3)).
- **IS vs OOS (NQ):** in-sample exp=0.2516R, out-of-sample exp=0.5545R (degradacion 0.3029R).
- **Walk-forward:** 8/8 anios OOS positivos, media test exp=0.6835R, peor anio=0.264R.

## 2. Robustez temporal (por anio)
### NQ
| anio | n | exp R | winrate | PF | sumR |
|---|---|---|---|---|---|
| 2017 | 466 | 0.02 | 0.5043 | 1.076 | 9.3 |
| 2018 | 531 | 0.328 | 0.6723 | 2.438 | 174.2 |
| 2019 | 561 | 0.2296 | 0.6684 | 2.074 | 128.8 |
| 2020 | 585 | 0.3086 | 0.7402 | 2.383 | 180.5 |
| 2021 | 569 | 0.333 | 0.7592 | 2.682 | 189.5 |
| 2022 | 581 | 0.6047 | 0.7642 | 3.783 | 351.3 |
| 2023 | 568 | 0.3443 | 0.7588 | 2.685 | 195.5 |
| 2024 | 546 | 0.5891 | 0.7711 | 3.786 | 321.6 |
| 2025 | 542 | 0.5531 | 0.8118 | 4.006 | 299.8 |
| 2026 | 242 | 0.8525 | 0.7893 | 4.873 | 206.3 |

### ES
| anio | n | exp R | winrate | PF | sumR |
|---|---|---|---|---|---|
| 2017 | 419 | -0.1402 | 0.2912 | 0.469 | -58.7 |
| 2018 | 509 | 0.013 | 0.4381 | 1.053 | 6.6 |
| 2019 | 537 | -0.0865 | 0.3315 | 0.67 | -46.4 |
| 2020 | 546 | 0.0924 | 0.5696 | 1.372 | 50.4 |
| 2021 | 540 | 0.0072 | 0.5 | 1.028 | 3.9 |
| 2022 | 591 | 0.1368 | 0.6582 | 1.594 | 80.8 |
| 2023 | 527 | 0.0717 | 0.5389 | 1.284 | 37.8 |
| 2024 | 526 | 0.1037 | 0.5456 | 1.512 | 54.5 |
| 2025 | 550 | 0.1665 | 0.6545 | 1.779 | 91.5 |
| 2026 | 248 | 0.2512 | 0.6492 | 2.166 | 62.3 |

## 3. Sectorizado (sesion y direccion)
### NQ
**by_session:**
- london: n=2522 | exp=0.3308R | win=0.6816 | PF=2.422 | sumR=834.4 | maxDD=-25.4R | ret/DD=None
- ny_am: n=2669 | exp=0.458R | win=0.7643 | PF=3.301 | sumR=1222.5 | maxDD=-9.8R | ret/DD=None
**by_direction:**
- long: n=2507 | exp=0.4241R | win=0.7403 | PF=3.132 | sumR=1063.2 | maxDD=-6.1R | ret/DD=None
- short: n=2684 | exp=0.3702R | win=0.709 | PF=2.604 | sumR=993.7 | maxDD=-20.1R | ret/DD=None
- exits: {'be': 2644, 'tp_full': 1574, 'stop': 947, 'time': 26}

### ES
**by_session:**
- london: n=2432 | exp=-0.0205R | win=0.4457 | PF=0.921 | sumR=-49.8 | maxDD=-103.6R | ret/DD=None
- ny_am: n=2561 | exp=0.1298R | win=0.5861 | PF=1.584 | sumR=332.5 | maxDD=-37.8R | ret/DD=None
**by_direction:**
- long: n=2423 | exp=0.064R | win=0.5225 | PF=1.28 | sumR=155.0 | maxDD=-47.8R | ret/DD=None
- short: n=2570 | exp=0.0497R | win=0.5132 | PF=1.198 | sumR=127.8 | maxDD=-61.2R | ret/DD=None
- exits: {'be': 2439, 'tp_full': 1740, 'stop': 783, 'time': 31}

## 4. Validacion de edge (null de Monte Carlo)
Entrada aleatoria con la MISMA logica de salida (stop/TP-R/BE). Si el setup sweep+BOS+FVG no aportara, no superaria a esto.
- **NQ:** real=0.3962R vs null=0.1362+-0.0197R (p95=0.1646) -> z=13.2 -> edge real (z>3)
- **ES:** real=0.0566R vs null=-0.1326+-0.0184R (p95=-0.111) -> z=10.28 -> edge real (z>3)

## 5. Controles de overfitting
### IS / OOS
- In-sample 2017-2021: n=2712 | exp=0.2516R | win=0.6755 | PF=2.123 | sumR=682.3 | maxDD=-16.3R | ret/DD=41.88
- Out-of-sample 2022-2026: n=2479 | exp=0.5545R | win=0.7773 | PF=3.692 | sumR=1374.6 | maxDD=-8.3R | ret/DD=164.77
### Walk-forward (optimiza sobre pasado, evalua sobre anio siguiente)
| anio test | mejor cfg train | train exp | test n | test exp | test win |
|---|---|---|---|---|---|
| 2019 | {'stop_anchor': 'confluence'} | 0.242 | 566 | 0.264 | 0.6201 |
| 2020 | {'stop_anchor': 'confluence'} | 0.25 | 590 | 0.4861 | 0.7017 |
| 2021 | {'stop_anchor': 'confluence'} | 0.314 | 578 | 0.5107 | 0.718 |
| 2022 | {'stop_anchor': 'confluence'} | 0.356 | 586 | 0.8356 | 0.7338 |
| 2023 | {'stop_anchor': 'confluence'} | 0.44 | 575 | 0.4837 | 0.7183 |
| 2024 | {'stop_anchor': 'confluence'} | 0.446 | 555 | 0.8354 | 0.7297 |
| 2025 | {'stop_anchor': 'confluence'} | 0.495 | 548 | 0.8684 | 0.7701 |
| 2026 | {'stop_anchor': 'confluence'} | 0.536 | 244 | 1.1838 | 0.7582 |

### Sensibilidad de parametros (NQ 2020-2024)
Plateau ancho = robusto; pico aislado = overfit.
- **swing_k:** 1=0.448, 2=0.4347, 3=0.4547, 4=0.4437  (rango 0.4347..0.4547)
- **bos_max_bars:** 6=0.4346, 9=0.4284, 12=0.4347, 18=0.4218, 24=0.4173  (rango 0.4173..0.4347)
- **fvg_entry_frac:** 0.0=0.4693, 0.25=0.4203, 0.5=0.4347, 0.75=0.4272, 1.0=0.4024  (rango 0.4024..0.4693)
- **stop_buffer_ticks:** 0=0.4724, 2=0.4516, 4=0.4347, 8=0.4119, 12=0.3802  (rango 0.3802..0.4724)
- **entry_valid_bars:** 6=0.4114, 9=0.4164, 12=0.4347, 18=0.447, 24=0.445  (rango 0.4114..0.447)
- **sweep_min_ticks:** 0=0.431, 1=0.4347, 2=0.4408, 4=0.4459  (rango 0.431..0.4459)
- **swing_lookback:** 15=0.5167, 20=0.4831, 30=0.4347, 40=0.4422, 60=0.448  (rango 0.4347..0.5167)

## 6. Ablaciones de componentes (NQ full)
| variante | n | exp R | winrate | PF | sumR | maxDD |
|---|---|---|---|---|---|---|
| base (liquidity TP, BE, no bias, 5m) | 5191 | 0.3962 | 0.7241 | 2.84 | 2056.9 | -16.3 |
| + bias filter HTF (h1) | 2761 | 0.3184 | 0.741 | 2.609 | 879.2 | -18.2 |
| TP por R fijo [1,2,3] (en vez de liquidez) | 4951 | 0.2687 | 0.6928 | 1.813 | 1330.2 | -42.2 |
| sin breakeven (use_be=False) | 4937 | 0.4064 | 0.5702 | 2.416 | 2006.5 | -19.8 |
| stop en confluencia (no en sweep) | 5253 | 0.5658 | 0.6868 | 3.106 | 2972.0 | -25.4 |
| entry TF 15m | 2366 | 0.652 | 0.8339 | 5.467 | 1542.7 | -8.7 |
| solo London | 2525 | 0.3298 | 0.6808 | 2.416 | 832.8 | -27.0 |
| solo NY am | 2782 | 0.4543 | 0.7664 | 3.293 | 1263.9 | -9.7 |
| sin parciales (todo a TP-final, 1 contrato) | 5191 | 0.4004 | 0.3134 | 2.527 | 2078.4 | -32.9 |

## 7. Monte Carlo de riesgo
- **NQ:** PnL final (R) p5=1839.0 / p50=2053.5 / p95=2289.3; prob final<0 = 0.0; maxDD mediana=-10.4R, peor 5%=-14.6R, peor absoluto=-27.1R.
- **ES:** PnL final (R) p5=175.8 / p50=282.8 / p95=393.1; prob final<0 = 0.0; maxDD mediana=-27.3R, peor 5%=-44.2R, peor absoluto=-98.6R.

## 8. Probabilidad de pasar prop firm (estilo HyroTrader)
Modelo: target +8%, daily loss 5%, max DD 10%, 2 trades/dia, 60 dias. Por Monte Carlo i.i.d. sobre la distribucion de R. (Ajustar a params exactos de tu firma.)
### NQ
| riesgo/trade | prob pasar | bust daily | bust maxDD | timeout | dias medianos |
|---|---|---|---|---|---|
| 0.0025 | 0.7923 | 0.0 | 0.0 | 0.2077 | 37 |
| 0.005 | 0.9729 | 0.0 | 0.0 | 0.0271 | 22 |
| 0.01 | 0.992 | 0.0 | 0.0053 | 0.0027 | 12 |

### ES
| riesgo/trade | prob pasar | bust daily | bust maxDD | timeout | dias medianos |
|---|---|---|---|---|---|
| 0.0025 | 0.0225 | 0.0 | 0.0 | 0.9775 | 49 |
| 0.005 | 0.2587 | 0.0 | 0.0067 | 0.7345 | 40 |
| 0.01 | 0.5703 | 0.0 | 0.1934 | 0.2364 | 25 |

## 9. Stress de costos de ejecucion (NQ full)
| escenario | n | exp R | winrate | PF | sumR |
|---|---|---|---|---|---|
| base (1 tick/lado + 0.5pt) | 5191 | 0.396 | 0.724 | 2.84 | 2056.9 |
| slippage 2x (2 ticks/lado) | 5191 | 0.360 | 0.692 | 2.57 | 1867.1 |
| slippage 3x + comision 2pt (stress fuerte) | 5191 | 0.103 | 0.513 | 1.28 | 536.8 |
| stress + solo NY am | 2782 | 0.238 | 0.607 | 1.82 | 663.1 |

## 10. Conclusiones y advertencias (lectura anti-overfitting)

**Veredicto:** la estrategia tiene **edge real y robusto en NQ**, marginal en ES. Cuatro
pruebas independientes lo respaldan y hacen improbable que sea overfitting:
1. **Null de Monte Carlo:** real supera a entrada-aleatoria con z=13.2 (NQ) y z=10.3 (ES).
   El winrate alto NO es artefacto del breakeven: el null con la misma maquinaria de salida
   da 51% win; el setup real da 72%.
2. **Sensibilidad de parametros:** plateau ancho en los 7 parametros (exp 0.38-0.52R en todo
   el rango), sin picos aislados -> no esta calzada a valores finos.
3. **Walk-forward:** 8/8 anios out-of-sample positivos (0.26-1.18R); OOS (0.55R) >= IS (0.25R),
   sin degradacion.
4. **Simetria:** en NQ los shorts tambien ganan (+0.37R), no es solo beta del rally alcista.

**Componentes (que aporta cada regla de TJR):**
- TP a **liquidez opuesta** > TP a R fijo (0.40 vs 0.27R): targetear liquidez agrega valor.
- **Stop en la confluencia** (FVG/OB) > stop en el sweep (0.57 vs 0.40R) y es lo que eligio
  el walk-forward: el stop mas ajustado mejora el R sin romper la robustez.
- **Breakeven tras TP1**: NO sube expectancy (0.41 sin BE vs 0.40 con BE) pero sube winrate
  57%->72% y baja varianza. Es gestion de RIESGO/psicologia/regla-de-prop-firm, no de retorno.
- **Sesion NY am** > London. **15m** rinde mejor que 5m (menos ruido: 0.65R, PF 5.5).
- El **filtro de bias HTF** (proxy mecanico H1) RESTA aqui (0.32 vs 0.40R). No implica que el
  bias discrecional de TJR sea inutil; implica que mi proxy mecanico no lo captura.

**Advertencias de realismo (lo que el backtest NO captura y puede inflar el resultado):**
- **Sensibilidad a costos:** con 3x slippage + comision alta el exp cae de 0.40 a 0.10R. Es una
  scalper de winrate alto y edge chico por trade -> la rentabilidad depende fuerte de la
  CALIDAD DE EJECUCION real (fills, spread en apertura/noticias).
- **Fills intrabar:** en velas de 5m asumo que la orden limite llena al precio exacto y que el
  stop se toca antes que el TP (conservador), pero el camino intrabar real es desconocido; el
  TP1 cercano podria no llenarse siempre antes del stop en velas violentas.
- **Cola izquierda / gaps:** la peor perdida modelada es ~-1.4R, pero un gap nocturno o un
  spike de noticias (FOMC/CPI) puede saltar el stop. El riesgo de cola NO esta modelado.
- **Calidad de datos:** los CSV son de un contrato continuo de terceros; los rollovers/empalmes
  pueden generar barridos "fantasma". Conviene revalidar con data del broker real.
- **5m y bias son proxies** del proceso discrecional de TJR (1m/5m + lectura de bias).
- La curva de NQ es MUY suave (ret/DD=126). Es plausible por la mecanica (muchas BE chicas +
  parciales), pero exige **forward test en vivo/paper** antes de creerla al 100%.

**Recomendaciones accionables:**
- Vehiculo: **NQ**, sesion **NY am** preferente. ES no es buen vehiculo (marginal, DD alto).
- Usar **stop en confluencia** y evaluar **15m** ademas de 5m.
- Mantener **breakeven** por gestion de riesgo (clave para el daily-loss de prop firms).
- Prop firm (modelo 8%/5%/10%): a **0.5% riesgo/trade en NQ ~97% de pasar**; no forzar ES.
- Antes de capital real: (1) forward/paper 1-2 meses, (2) re-correr con data del broker propio,
  (3) stress de slippage 2-3x como piso, (4) plan para eventos de noticias (no operar o reducir).
