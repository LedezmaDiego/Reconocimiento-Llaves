import threading
import time

from config import RECONOCIDO_REPETIR_S
from logs import log

MODO = {"valor": "reconocimiento", "hasta": 0.0}

ULTIMA_FOTO = {"bytes": None, "ts": 0.0}

ULTIMO_RESULTADO = {"texto": "Sin datos todavia"}

ULTIMA_AUTORIZACION: dict[str, tuple[str, float]] = {}

ACCESO_CODIGO: dict[str, tuple[str, float]] = {}

# Último rostro autorizado que vio la cámara. El dispensador lo consulta para
# mostrar "Bienvenido <persona>" y habilitar el pedido por teclado.
RECONOCIDO: dict = {"persona": "", "ts": 0.0, "seq": 0, "ultimo_aviso": 0.0}


def registrar_reconocido(persona: str) -> None:
    """Anota el rostro autorizado; avisa de nuevo solo si cambia o pasa el tiempo."""
    if not persona:
        return
    ahora = time.time()
    mismo = persona.lower() == RECONOCIDO["persona"].lower()
    if mismo and ahora - RECONOCIDO["ultimo_aviso"] < RECONOCIDO_REPETIR_S:
        # Sigue la misma persona delante: solo se refresca la vigencia.
        RECONOCIDO["ts"] = ahora
        return
    RECONOCIDO.update({"persona": persona, "ts": ahora,
                       "seq": RECONOCIDO["seq"] + 1, "ultimo_aviso": ahora})


INTENTOS: dict[str, list] = {}          # usuarios y "admin:<ip>"

AVISOS: dict[str, list] = {}

LOGIN_ROSTRO: dict[str, dict] = {}   # solicitudes de inicio de sesión por rostro (las atiende /reconocimiento)

BASE_EMBEDDINGS: dict[str, dict] = {}

# ---------------- Dispensador de llaves ----------------
# Solicitud de llave activa: el ESP32-CAM / frontend la crea y el ESP32 la consume.
SOLICITUD_LLAVE: dict = {
    "activa": False,
    "aula_id": None,
    "aula_nombre": "",
    "persona": "",
    "rfid": "",
    "requiere_pin": False,
    "intentos_rostro": 0,
    "creada": 0.0,
}

LOCK_SOLICITUD = threading.Lock()

# Último evento reportado por el dispensador (para el panel y logs).
ULTIMO_EVENTO_DISPENSADOR: dict = {"evento": "ninguno", "detalle": "", "ts": 0.0}

LOCK_BASE = threading.Lock()

LOCK_DEEPFACE = threading.Lock()

LOCK_NOMBRES = threading.Lock()

_PB = {"token": None}

LOCK_PB = threading.Lock()

_CACHE_ESTADO: dict[str, tuple[str | None, float]] = {}   # evita consultar PocketBase en cada request

def modo_actual() -> str:
    """Devuelve el modo vigente; si expiró el registro vuelve a reconocimiento."""
    if MODO["valor"] == "registro" and time.time() > MODO["hasta"]:
        MODO["valor"] = "reconocimiento"
        log("MODO", f"Reconocimiento (el modo registro venció)")
    return MODO["valor"]


