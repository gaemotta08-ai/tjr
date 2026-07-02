#!/usr/bin/env bash
# setup_vps.sh — prepara una VM Ubuntu (Oracle Always Free) para correr las
# senales TJR 24/7. Es idempotente: se puede correr varias veces sin romper nada.
#
# Uso (una vez logueado por SSH a la VM):
#   bash setup_vps.sh
set -euo pipefail

BASE="${TJR_BASE:-$HOME/tjr}"
VENV="$BASE/venv"

echo "[setup] base=$BASE"

# 1) Paquetes del sistema
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip

# 2) Estructura de carpetas que espera live_runner
mkdir -p "$BASE/ENTREGA/2_backtest" "$BASE/ejecucion"

# 3) Entorno virtual + dependencias (mismas que en la Mac)
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install pandas numpy scipy yfinance

echo
echo "[setup] LISTO."
echo "[setup] venv:            $VENV"
echo "[setup] copia ahora los .py a:"
echo "         $BASE/ENTREGA/           (live_runner.py, feed_yfinance.py)"
echo "         $BASE/ENTREGA/2_backtest/ (data.py engine.py metrics.py analyze.py plan.py plan2.py)"
echo "         $BASE/ejecucion/         (ejecutor_futuros.py trader_real_futuros.py)"
echo "[setup] despues: sudo cp deploy/*.service /etc/systemd/system/ && sudo systemctl daemon-reload"
