#!/usr/bin/env bash
# ============================================================
#  LLAVERO INTELIGENTE - Script de inicio
# ============================================================
#  Levanta PocketBase + FastAPI y deja la web lista para usar.
#
#  Uso:
#    ./iniciar.sh              → arranca todo (PocketBase + FastAPI)
#    ./iniciar.sh --build      → recompila el frontend antes de arrancar
#    ./iniciar.sh --parar      → detiene los procesos
#    ./iniciar.sh --reiniciar  → para y vuelve a arrancar
# ============================================================

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$RAIZ"

PUERTO_API=8000
PUERTO_PB=8090
VENV="$RAIZ/venv"

# ---- Configuración: .env si existe, si no valores por defecto ----
if [ -f "$RAIZ/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$RAIZ/.env"
  set +a
fi

ADMIN_CLAVE="${ADMIN_CLAVE:-admin123}"
PB_EMAIL="${PB_EMAIL:-admin@llavero.local}"
PB_PASSWORD="${PB_PASSWORD:-LlaveroAdmin2026!}"
PB_URL="${PB_URL:-http://127.0.0.1:${PUERTO_PB}}"

# ---- Colores ----
VERDE='\033[0;32m'; AMARILLO='\033[1;33m'; ROJO='\033[0;31m'; CIERRE='\033[0m'

info()  { echo -e "${AMARILLO}[INFO]${CIERRE} $*"; }
ok()    { echo -e "${VERDE}[ OK ]${CIERRE} $*"; }
error() { echo -e "${ROJO}[ERR ]${CIERRE} $*" >&2; }

# ============================================================
#  Utilidades
# ============================================================
puerto_ocupado() {
  # Nota: con `set -o pipefail`, "ss | grep -q" falla por SIGPIPE.
  # Por eso se captura la salida antes de filtrar.
  local lineas
  lineas=$(ss -ltnH 2>/dev/null | grep -E "[:.]${1}[[:space:]]" || true)
  [ -n "$lineas" ]
}

esperar_puerto() {
  # $1 = puerto, $2 = segundos máximos, $3 = descripción
  local puerto="$1" max="$2" nombre="$3" i
  for ((i = 0; i < max; i++)); do
    if puerto_ocupado "$puerto"; then
      return 0
    fi
    sleep 1
  done
  error "$nombre no respondió en ${max}s. Revisá el log."
  return 1
}

# ============================================================
#  Detener procesos
# ============================================================
parar() {
  info "Deteniendo procesos..."
  # Uvicorn con --reload deja un proceso hijo (multiprocessing) que sigue
  # con el puerto: se matan por puerto y además por nombre.
  for puerto in "$PUERTO_API" "$PUERTO_PB"; do
    pids=$(ss -ltnpH 2>/dev/null | grep -E "[:.]${puerto}[[:space:]]" | grep -oP 'pid=\K[0-9]+' | sort -u || true)
    for pid in $pids; do
      kill -9 "$pid" 2>/dev/null && ok "Puerto $puerto liberado (pid $pid)"
    done
  done
  pkill -9 -f "main:app" 2>/dev/null || true
  pkill -9 -f "multiprocessing.spawn" 2>/dev/null || true
  pkill -9 -f "pocketbase serve" 2>/dev/null || true
  sleep 1
  for puerto in "$PUERTO_API" "$PUERTO_PB"; do
    if puerto_ocupado "$puerto"; then
      error "El puerto $puerto sigue ocupado"
    fi
  done
}

# ============================================================
#  Verificaciones previas
# ============================================================
verificar() {
  if [ ! -d "$VENV" ]; then
    error "No existe el entorno virtual '$VENV'."
    echo "     Creálo con:  python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
  fi
  if [ ! -f "$RAIZ/pocketbase" ]; then
    error "Falta el ejecutable 'pocketbase'."
    echo "     Descargalo de https://github.com/pocketbase/pocketbase/releases y ponelo en la raíz."
    exit 1
  fi
}

# ============================================================
#  Frontend
# ============================================================
construir_frontend() {
  if [ ! -d "$RAIZ/frontend/node_modules" ]; then
    info "Instalando dependencias del frontend..."
    (cd frontend && npm install)
  fi
  info "Compilando frontend..."
  (cd frontend && npm run build)
  ok "Frontend compilado en frontend/dist/"
}

# ============================================================
#  Arranque
# ============================================================
arrancar() {
  verificar

  if [ "${1:-}" = "--build" ]; then
    construir_frontend
  fi

  # Si el frontend no está compilado, se compila ahora.
  if [ ! -f "$RAIZ/frontend/dist/index.html" ]; then
    info "Falta frontend/dist, compilando..."
    construir_frontend
  fi

  # --- PocketBase ---
  info "Arrancando PocketBase en puerto $PUERTO_PB..."
  # setsid+nohup: sobreviven al cierre de esta terminal.
  setsid nohup ./pocketbase serve --http=0.0.0.0:$PUERTO_PB > pocketbase.log 2>&1 < /dev/null &
  if esperar_puerto "$PUERTO_PB" 20 "PocketBase"; then
    ok "PocketBase corriendo → http://localhost:$PUERTO_PB/_/"
  else
    exit 1
  fi

  # --- FastAPI ---
  info "Arrancando FastAPI en puerto $PUERTO_API..."
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  ADMIN_CLAVE="$ADMIN_CLAVE" PB_EMAIL="$PB_EMAIL" PB_PASSWORD="$PB_PASSWORD" PB_URL="$PB_URL" \
    setsid nohup python backend/main.py > server.log 2>&1 < /dev/null &
  # DeepFace/TensorFlow tardan en importar: se espera hasta 180s.
  if esperar_puerto "$PUERTO_API" 180 "FastAPI"; then
    ok "FastAPI corriendo → http://localhost:$PUERTO_API"
  else
    exit 1
  fi

  IP_ESP32=$(ip -4 addr show wlp2s0 2>/dev/null | grep -oP 'inet \K[\d.]+' | head -1)
  IP_LOCAL=$(ip -4 addr show eno1 2>/dev/null | grep -oP 'inet \K[\d.]+' | head -1)
  IP_ESP32="${IP_ESP32:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
  IP_LOCAL="${IP_LOCAL:-${IP_ESP32}}"

  echo
  echo "============================================================"
  echo -e " ${VERDE}Proyecto iniciado${CIERRE}"
  echo "============================================================"
  echo "  En esta PC:"
  echo "    Usuarios:       http://localhost:$PUERTO_API/registro"
  echo "    Administración:  http://localhost:$PUERTO_API/admin  (clave: $ADMIN_CLAVE)"
  echo "    PocketBase:     http://localhost:$PUERTO_PB/_/"
  echo
  echo "  Desde la red (ESP32-CAM / dispenser):"
  echo "    WiFi:           http://$IP_ESP32:$PUERTO_API"
  echo "    Cable:          http://$IP_LOCAL:$PUERTO_API"
  echo "============================================================"
  echo "  Logs:  tail -f server.log"
  echo "  Parar: ./iniciar.sh --parar"
  echo
}

# ============================================================
#  Menú
# ============================================================
case "${1:-}" in
  --parar|--stop)
    parar
    ok "Todo detenido"
    ;;
  --reiniciar|--restart)
    parar
    arrancar
    ;;
  --build)
    parar
    arrancar --build
    ;;
  "")
    parar
    arrancar
    ;;
  --help|-h)
    echo "Uso: ./iniciar.sh [--build|--parar|--reiniciar|--help]"
    ;;
  *)
    error "Opción desconocida: $1"
    echo "Uso: ./iniciar.sh [--build|--parar|--reiniciar|--help]"
    exit 1
    ;;
esac
