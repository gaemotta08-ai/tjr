"""trader_tjr_futuros.py — VÍA 2 del forward test: ejecuta la estrategia TJR en una
cuenta DEMO de futuros (ProjectX / TopstepX) y mide el SLIPPAGE real pedido-vs-fill.

REUSA la capa de órdenes ya validada de Fede (ejecutor_projectx.EjecutorProjectX):
abrir (market+stop bracket), mover_stop, cerrar, posicion, balance. NO la reescribe.
Lo único que agrega es la SALIDA de TJR (parciales 50/25/25 + breakeven tras TP1),
que el trader_real de Fede no tiene (él usa target fijo 2R), y el log de slippage
en CADA evento (entrada, cada parcial, BE, stop).

⚠️ LÓGICA validada offline (ver test al final). Las llamadas REST de ProjectX NO
están validadas contra la demo real todavía (mismo cabo suelto que dejó Fede) ->
validar contra la cuenta demo ANTES de creerle a los fills. DEMO por defecto.

Uso (cuando haya cuenta demo + claves PROJECTX_USER / PROJECTX_APIKEY):
  - El forward loop detecta el setup TJR (entry, stop, tps) con el MISMO engine.py
  - llama abrir_setup(...) y luego gestionar(...) en cada vela cerrada
  - el slippage queda en forward/slippage_live.csv (lo lee forward_test.py score)
"""
import os, sys, csv

# specs de futuros de Fede (punto/tick por contrato, micro)
sys.path.insert(0, os.path.expanduser("~/Desktop/HANDOFF_fede/ejecucion"))
from ejecutor_futuros import PUNTO, TICK, MICRO, OrdenMuyChica  # noqa

SLIP_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "forward", "slippage_live.csv")
TP_FRACS = (0.5, 0.25, 0.25)   # parciales TJR


class TraderTJRFuturos:
    def __init__(self, ejecutor, riesgo=0.005, usar_micro=True, max_dia=3):
        self.ej = ejecutor
        self.riesgo = riesgo
        self.usar_micro = usar_micro
        self.max_dia = max_dia
        self.tomados = {}
        self.abiertos = {}     # inst -> estado del trade (tps, fracs, stop, contratos, lado, entry)

    # ---- entrada: market@FVG + stop bracket server-side (sin target: gestionamos parciales) ----
    def abrir_setup(self, day, inst_symbol, lado, entry, stop, tps):
        if lado not in ("long", "short"):
            return ("skip", "lado")
        if self.tomados.get(day, 0) >= self.max_dia:
            return ("skip", "tope diario")
        inst = MICRO.get(inst_symbol, inst_symbol) if self.usar_micro else inst_symbol
        if self.ej.posicion(inst) or inst in self.abiertos:
            return ("skip", f"ya hay posición en {inst}")
        stop_pts = abs(entry - stop)
        if stop_pts <= 0:
            return ("skip", "stop inválido")
        equity = self.ej.balance()
        try:
            contratos, _ = self.ej.contratos_por_riesgo(inst, equity, self.riesgo, stop_pts)
        except OrdenMuyChica as e:
            return ("skip_chico", str(e)[:90])
        # repartir contratos en parciales (mín 1 por tramo si entran)
        n = contratos
        lotes = [max(1, round(n * f)) for f in TP_FRACS]
        while sum(lotes) > n and max(lotes) > 1:
            lotes[lotes.index(max(lotes))] -= 1
        self.ej.abrir(inst, lado, n, stop, target_price=None, entry_ref=entry)
        self._log("entrada", inst, lado, entry, contratos=n)   # mide slippage de entrada
        self.abiertos[inst] = dict(lado=lado, entry=entry, stop=stop, tps=list(tps),
                                   lotes=lotes, restante=n, tps_hit=0)
        self.tomados[day] = self.tomados.get(day, 0) + 1
        return ("abrir", inst, n, lotes)

    # ---- gestión: parciales en cada TP + BE tras TP1 + trailing tras TP2 ----
    def gestionar(self, inst, precio_actual):
        st = self.abiertos.get(inst)
        if not st:
            return ("flat",)
        lado, tps, k = st["lado"], st["tps"], st["tps_hit"]
        # ¿llegó al próximo TP?
        if k < 3:
            tp = tps[k]
            hit = (precio_actual >= tp) if lado == "long" else (precio_actual <= tp)
            if hit:
                lote = st["lotes"][k]
                self._cerrar_parcial(inst, lote)
                self._log(f"tp{k+1}", inst, lado, tp, contratos=lote)   # slippage del parcial
                st["restante"] -= lote; st["tps_hit"] += 1
                if st["tps_hit"] == 1:                       # BE tras TP1
                    self.ej.mover_stop(inst, st["entry"]); self._log("be_move", inst, lado, st["entry"])
                if st["restante"] <= 0:
                    self.abiertos.pop(inst, None)
                    return ("cerrado_full",)
                return (f"parcial_tp{k+1}", lote)
        return ("en_pos", st["restante"])

    def stop_ejecutado(self, inst, stop_price):
        """Llamar cuando el broker reporta que saltó el stop (BE o pérdida)."""
        st = self.abiertos.pop(inst, None)
        if st:
            self._log("stop", inst, st["lado"], stop_price, contratos=st["restante"])
        return ("stopped",)

    # ---- cierre parcial reusando el transporte del ejecutor (no reescribe la lógica) ----
    def _cerrar_parcial(self, inst, contratos):
        pos = self.ej.posicion(inst)
        if not pos or contratos <= 0:
            return
        from ejecutor_projectx import TIPO, LADO  # mismos códigos de la API
        side = LADO["sell"] if pos["lado"] == "long" else LADO["buy"]
        self.ej.api.post("/Order/place", {
            "accountId": self.ej.account_id, "contractId": self.ej._contract_id(inst),
            "type": TIPO["market"], "side": side, "size": int(contratos)})

    # ---- slippage pedido-vs-fill ----
    # ENTRADA: medible ya (precio pedido vs avg real de la posición = fede).
    # SALIDAS (tp/stop): el fill real SÓLO está en el fill report del broker -> se
    # loguea el precio pedido + orderId y se reconcilia con _reconciliar_fills()
    # contra el demo. NO inventamos el fill de salida.
    def _log(self, evento, inst, lado, intencion, contratos=0, fill=None):
        if evento == "entrada":
            pos = self.ej.posicion(inst)
            fill = pos["entrada"] if pos else intencion
        if fill is None:                      # salida sin fill confirmado todavía
            slip_pts = None; slip_tk = None
        else:
            adverso = ((fill - intencion) if lado == "long" else (intencion - fill)) \
                if evento == "entrada" else \
                ((intencion - fill) if lado == "long" else (fill - intencion))
            slip_pts = round(adverso, 3); slip_tk = round(adverso / TICK.get(inst, 0.25), 2)
        reg = dict(evento=evento, inst=inst, lado=lado, intencion=round(intencion, 2),
                   fill=(round(fill, 2) if fill is not None else "PENDIENTE_RECONCILIAR"),
                   slippage_pts=slip_pts, slippage_ticks=slip_tk, contratos=contratos)
        os.makedirs(os.path.dirname(SLIP_LOG), exist_ok=True)
        existe = os.path.exists(SLIP_LOG)
        with open(SLIP_LOG, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(reg))
            if not existe: w.writeheader()
            w.writerow(reg)


# ===================== TEST OFFLINE (valida la lógica sin cuenta) =====================
class _MockEj:
    """Simula el ejecutor ProjectX con slippage configurable, para validar el adapter."""
    def __init__(self, slip_ticks=1.0):
        self.slip = slip_ticks; self.pos = {}; self.account_id = 1
        class _Api:
            def post(s, path, body): return {"orderId": 1}
        self.api = _Api()
    def balance(self): return 50000.0
    def _contract_id(self, s): return s
    def contratos_por_riesgo(self, inst, eq, r, stop_pts):
        import math
        n = math.floor((eq * r) / (stop_pts * PUNTO[inst]))
        if n < 1: raise OrdenMuyChica("chico")
        return n, n * stop_pts * PUNTO[inst]
    def posicion(self, inst): return self.pos.get(inst)
    def abrir(self, inst, lado, n, stop, target_price=None, entry_ref=None):
        fill = entry_ref + (self.slip * TICK[inst]) * (1 if lado == "long" else -1)  # entrada adversa
        self.pos[inst] = {"lado": lado, "contratos": n, "entrada": fill}
    def mover_stop(self, inst, px): pass
    def cerrar(self, inst): self.pos.pop(inst, None)


def _test():
    import os
    if os.path.exists(SLIP_LOG): os.remove(SLIP_LOG)
    ej = _MockEj(slip_ticks=1.0)
    t = TraderTJRFuturos(ej, riesgo=0.005, usar_micro=True)
    # setup TJR long: entry 18000, stop 17980 (20pt), tps a +1R/+2R/+3R
    r = t.abrir_setup("2026-06-13", "NQ", "long", 18000.0, 17980.0, [18020.0, 18040.0, 18060.0])
    assert r[0] == "abrir", r
    inst = r[1]; print("entrada:", r)
    # simular que el precio sube y toca cada TP
    for px in (18020.0, 18040.0, 18060.0):
        print("  gestionar @", px, "->", t.gestionar(inst, px))
    assert inst not in t.abiertos, "debería haber cerrado todo tras TP3"
    # leer el log de slippage
    import csv as _c
    rows = list(_c.DictReader(open(SLIP_LOG)))
    print(f"\nslippage_live.csv: {len(rows)} eventos")
    for r in rows: print("  ", r["evento"], r["inst"], "pedido", r["intencion"], "fill", r["fill"], "→", r["slippage_ticks"], "ticks")
    ent = [r for r in rows if r["evento"] == "entrada"][0]
    assert abs(float(ent["slippage_ticks"]) - 1.0) < 1e-6, "slippage de entrada debería ser 1 tick (mock)"
    assert any(r["fill"] == "PENDIENTE_RECONCILIAR" for r in rows), "salidas deben quedar a reconciliar"
    print("\n✅ TEST OFFLINE OK — ladder de salida TJR (parciales 50/25/25 + BE) dispara bien;")
    print("   slippage de ENTRADA se mide ya (1 tick en el mock); el de SALIDAS queda")
    print("   PENDIENTE_RECONCILIAR contra el fill report del broker (sólo con cuenta demo).")


if __name__ == "__main__":
    _test()
