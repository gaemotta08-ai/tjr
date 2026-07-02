"""
pseudocodigo.py — Estrategia mecanica de TJR (SMC/ICT day trading)
Consolidada de 225 videos del canal @TJRTrades que contienen estrategia.
Reglas incluidas SOLO si aparecen en >=3 videos (ver estrategia.json).

NO es codigo de produccion: es pseudocodigo estructurado y testeable que
define el flujo y, sobre todo, la GESTION DE SALIDAS (stop / take profit /
breakeven), que es el foco. Las funciones de deteccion (sweep, BOS, fvg...)
son contratos a implementar con tu feed de velas.

Convencion: trabajamos un solo instrumento, direccion del dia = bias.
'long'  -> esperamos barrido de un LOW  y giro al alza
'short' -> esperamos barrido de un HIGH y giro a la baja
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ----------------------------------------------------------------------------
# CONFIG (los numeros surgen de la consolidacion; ajustables / a backtestear)
# ----------------------------------------------------------------------------
class Cfg:
    # Sesion / horario (killzones) -- regla 1
    KILLZONES = [("02:00", "05:00"),   # London open (ET aprox)
                 ("09:30", "11:00")]   # New York open / sesion AM
    # Timeframes -- regla 7
    TF_BIAS = ["1D", "4H", "1H"]       # contexto / draws on liquidity
    TF_MARK = "15m"                    # marcado intermedio
    TF_EXEC = ["5m", "1m"]            # ejecucion: 5m -> 1m

    # Entrada -- regla 6
    FVG_ENTRY_FRACTION = 0.50          # entra al 50% del fair value gap ('the 50')
    USE_ORDER_BLOCK_FALLBACK = True    # si no hay FVG usable, usar order block

    # Estructura -- regla 5
    BOS_REQUIRE_CLOSE = True           # confirma con CIERRE de vela, no mecha

    # SALIDAS ------------------------------------------------------------------
    # Stop estructural (no por ticks fijos). Eleccion de ubicacion:
    #   'sweep'      -> del otro lado del barrido completo (mas seguro, preferido)
    #   'confluence' -> del otro lado del FVG/OB de entrada (intermedio)
    #   'micro'      -> del otro lado del high/low previo al BOS (mas tight/arriesgado)
    STOP_ANCHOR = "sweep"
    SPREAD_BUFFER_PIPS = 4             # Forex/oro: +2..4 pips por el spread
    IS_FOREX = False

    # Take profit escalonado hacia liquidez OPUESTA (regla TP)
    #   lista de (fraccion_a_cerrar, cual_draw). El resto = runner.
    TP_LADDER = [
        (0.50, "nearest_opposite_liquidity"),   # TP1 (~1:1 tipico)
        (0.25, "intermediate_opposite_liquidity"),  # TP2
        # runner 0.25 corre a 'htf_opposite_liquidity'
    ]
    TP_RUNNER_TARGET = "htf_opposite_liquidity"
    FOREX_FULL_TP1 = True             # en Forex a veces cierra TODO en TP1

    # Breakeven (regla BE)
    MOVE_TO_BE_AFTER_TP = 1           # tras TP1 -> stop a break even
    TRAIL_TO_PROFIT_AFTER_TP = 2     # tras TP2 -> stop a profit detras de estructura
    BE_TOO_EARLY_GUARD = True        # NO mover a BE antes de TP1 (Seek & Destroy)


# ----------------------------------------------------------------------------
# Tipos
# ----------------------------------------------------------------------------
class Side(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class Level:
    price: float
    kind: str          # 'session_high','prev_day_low','1h_high','equal_lows',...
    timeframe: str


@dataclass
class Trade:
    side: Side
    entry: float
    stop: float
    tps: list           # [(price, fraction)]
    size: float
    filled: bool = False
    tps_hit: int = 0
    stop_at_be: bool = False
    runner_target: Optional[float] = None
    open_size: float = 0.0


# ----------------------------------------------------------------------------
# CONTRATOS DE DETECCION (implementar con tu data) -- reglas 2,3,4,5,6
# ----------------------------------------------------------------------------
def in_killzone(now) -> bool: ...
def daily_bias(candles_htf) -> Side:
    """Regla 2: top-down en 1D/4H/1H. Direccion = hacia que draw on liquidity
    deberia ir el precio DESPUES de manipular (barrer) el lado opuesto."""
    ...
def mark_liquidity_levels(candles_htf) -> list:  # -> [Level]
    """Regla 3: session highs/lows (Asia/London/NY), previous day H/L,
    1H y 4H highs/lows, relative equal highs/lows, data H/L, opening gaps."""
    ...
def detect_liquidity_sweep(candles_ltf, level: Level, side: Side) -> Optional[dict]:
    """Regla 4: el precio EXCEDE el nivel con mecha y NO continua (falla/revierte).
    Invalida si el precio se mantiene mas alla -> no fue sweep.
    Devuelve {'extreme': precio_del_wick} o None."""
    ...
def detect_bos(candles_ltf, side: Side, require_close=True) -> Optional[dict]:
    """Regla 5: break of structure en direccion del bias tras el sweep.
    Confirmado por CIERRE (displacement), no por mecha.
    Devuelve {'broken_level':..., 'pre_bos_extreme':...} o None."""
    ...
def find_entry_fvg_or_ob(candles_ltf, side: Side) -> Optional[dict]:
    """Regla 6: el displacement del BOS deja un FVG (imbalance). Entrada al 50%.
    Fallback: order block (ultima vela opuesta antes del impulso).
    Devuelve {'entry': precio_50, 'fvg_far_edge':..., 'ob_far_edge':...}."""
    ...
def opposite_liquidity_targets(levels: list, side: Side, entry: float) -> list:
    """Regla TP: draws on liquidity del lado OPUESTO a la entrada, ordenados
    de mas cercano a mas lejano. Long->highs ; Short->lows."""
    ...
def pip_buffer(price: float, side: Side) -> float:
    d = Cfg.SPREAD_BUFFER_PIPS * 0.0001 if Cfg.IS_FOREX else 0.0
    return d


# ----------------------------------------------------------------------------
# CONSTRUCCION DEL STOP (foco salidas)
# ----------------------------------------------------------------------------
def compute_stop(side: Side, sweep: dict, fvg: dict, bos: dict) -> float:
    """Stop ESTRUCTURAL, del lado que INVALIDA la idea. Nunca por ticks fijos.
    Preferencia: sweep (mas seguro) > confluence (FVG/OB) > micro (pre-BOS)."""
    if Cfg.STOP_ANCHOR == "sweep":
        anchor = sweep["extreme"]                 # arriba/abajo del barrido completo
    elif Cfg.STOP_ANCHOR == "confluence":
        anchor = fvg.get("fvg_far_edge") or fvg.get("ob_far_edge")
    else:  # 'micro'
        anchor = bos["pre_bos_extreme"]

    buf = pip_buffer(anchor, side)
    if side == Side.SHORT:
        return anchor + buf      # stop POR ENCIMA de los highs barridos
    else:
        return anchor - buf      # stop POR DEBAJO de los lows/wick barridos


# ----------------------------------------------------------------------------
# CONSTRUCCION DE TAKE PROFITS (foco salidas)
# ----------------------------------------------------------------------------
def build_take_profits(side: Side, entry: float, levels: list) -> list:
    """Devuelve [(price, fraction)] hacia liquidez opuesta, escalonado.
    El runner (resto) apunta al draw on liquidity de HTF."""
    targets = opposite_liquidity_targets(levels, side, entry)
    if not targets:
        return []

    if Cfg.IS_FOREX and Cfg.FOREX_FULL_TP1:
        return [(targets[0].price, 1.0)]          # Forex: full TP en el primer nivel

    tps = []
    # TP1 = nivel mas cercano ; TP2 = intermedio ; runner = HTF mas lejano
    if len(targets) >= 1:
        tps.append((targets[0].price, Cfg.TP_LADDER[0][0]))           # 50%
    if len(targets) >= 2:
        tps.append((targets[1].price, Cfg.TP_LADDER[1][0]))           # 25%
    # runner: el draw on liquidity de mayor timeframe disponible
    runner_price = targets[-1].price
    tps.append((runner_price, 1.0 - sum(f for _, f in tps)))          # ~25%
    return tps


# ----------------------------------------------------------------------------
# GESTION EN VIVO DE LA SALIDA (stop / parciales / breakeven) -- foco
# ----------------------------------------------------------------------------
def manage_open_trade(trade: Trade, candle) -> Trade:
    """Se llama en cada vela mientras el trade esta abierto.
    Implementa: parciales en cada TP, breakeven tras TP1, trailing a profit tras TP2."""
    if not trade.filled:
        return trade

    # 1) stop hit?
    if _stop_hit(trade, candle):
        _close_all(trade, reason="stop" if not trade.stop_at_be else "breakeven")
        return trade

    # 2) TP hit? (de a uno, en orden)
    if trade.tps_hit < len(trade.tps):
        tp_price, frac = trade.tps[trade.tps_hit]
        if _tp_hit(trade.side, tp_price, candle):
            _take_partial(trade, frac)            # cerrar parcial (50%, 25%, ...)
            trade.tps_hit += 1

            # --- BREAKEVEN: tras TP1 mover stop a entry (regla BE por defecto) ---
            if trade.tps_hit == Cfg.MOVE_TO_BE_AFTER_TP:
                trade.stop = trade.entry
                trade.stop_at_be = True

            # --- TRAILING A PROFIT: tras TP2 mover stop detras de la estructura ---
            elif trade.tps_hit == Cfg.TRAIL_TO_PROFIT_AFTER_TP:
                trade.stop = _last_structure_beyond_entry(trade, candle)

    return trade


# Guard del caveat: NUNCA mover a BE antes de TP1 (Seek & Destroy te wickea).
def _enforce_be_guard(trade: Trade):
    if Cfg.BE_TOO_EARLY_GUARD and trade.tps_hit < 1:
        assert not trade.stop_at_be, "No mover a breakeven antes de TP1"


# ----------------------------------------------------------------------------
# LOOP PRINCIPAL
# ----------------------------------------------------------------------------
def run_session(feed):
    candles_htf = feed.htf(Cfg.TF_BIAS)
    bias = daily_bias(candles_htf)                 # regla 2
    levels = mark_liquidity_levels(candles_htf)    # regla 3

    while True:
        now = feed.next()
        if now is None:
            break
        if not in_killzone(now):                   # regla 1
            continue
        ltf = feed.ltf(Cfg.TF_EXEC)

        # contexto: barrido de liquidez contrario al bias (regla 4)
        contrarian_level = _nearest_level_against(levels, bias, ltf.price)
        sweep = detect_liquidity_sweep(ltf, contrarian_level, bias)
        if not sweep:
            continue

        # confirmacion: break of structure en direccion del bias (regla 5)
        bos = detect_bos(ltf, bias, require_close=Cfg.BOS_REQUIRE_CLOSE)
        if not bos:
            continue

        # gatillo: FVG/order block del displacement (regla 6)
        fvg = find_entry_fvg_or_ob(ltf, bias)
        if not fvg:
            continue

        entry = fvg["entry"]                        # limite al 50% del FVG
        stop = compute_stop(bias, sweep, fvg, bos)  # SALIDA: stop estructural
        tps = build_take_profits(bias, entry, levels)  # SALIDA: TP a liquidez opuesta
        if not tps or not _valid_risk(entry, stop, tps):
            continue

        size = _position_size(entry, stop)          # riesgo fijo % por trade
        trade = Trade(side=bias, entry=entry, stop=stop, tps=tps,
                      size=size, runner_target=tps[-1][0], open_size=size)

        # esperar fill del limite, luego gestionar salida vela por vela
        _place_limit_and_manage(trade, feed)


# ----------------------------------------------------------------------------
# Helpers de ejecucion (contratos)
# ----------------------------------------------------------------------------
def _stop_hit(t, c): ...
def _tp_hit(side, price, c): ...
def _take_partial(t, frac): ...      # cierra frac*size_original; reduce t.open_size
def _close_all(t, reason): ...
def _last_structure_beyond_entry(t, c): ...   # low/high de 5m detras del precio (solo con cierre)
def _nearest_level_against(levels, bias, price): ...
def _valid_risk(entry, stop, tps): ...        # exige TP1 >= ~1:1 vs el stop
def _position_size(entry, stop): ...          # riesgo = % fijo de cuenta / distancia al stop
def _place_limit_and_manage(trade, feed): ... # fill + loop de manage_open_trade


# ============================================================================
# RESUMEN MECANICO (de estrategia.json)
# ----------------------------------------------------------------------------
# ENTRADA:
#   killzone -> bias HTF -> barrido de liquidez contrario -> BOS confirmado por
#   cierre -> entrada limite al 50% del FVG (o order block).
#
# SALIDA (foco):
#   STOP  = estructural, del otro lado del barrido que invalida la idea
#           (shorts: arriba de los highs barridos; longs: debajo del low/wick).
#           Forex: +2..4 pips por spread. NUNCA ticks fijos.
#   TP    = liquidez OPUESTA (session/prev-day/1H/4H highs-lows, equal H/L),
#           escalonado: 50% TP1 (~1:1) / 25% TP2 / runner 25% a draw HTF.
#           R es consecuencia del nivel, no objetivo fijo (tipico 1:2-1:3).
#   BE    = tras TP1 (primer parcial) -> stop a BREAK EVEN.
#           tras TP2 -> stop a PROFIT detras de la ultima estructura.
#           Caveat: no mover a BE demasiado temprano (Seek & Destroy).
# ============================================================================
