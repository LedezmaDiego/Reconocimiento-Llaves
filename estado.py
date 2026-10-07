import threading
import time

from logs import log

MODO = {"valor": "reconocimiento", "hasta": 0.0}

ULTIMA_FOTO = {"bytes": None, "ts": 0.0}

ULTIMO_RESULTADO = {"texto": "Sin datos todavia"}

ULTIMA_AUTORIZACION: dict[str, tuple[str, float]] = {}

ACCESO_CODIGO: dict[str, tuple[str, float]] = {}

SESIONES: dict[str, tuple[str, float]] = {}

SESIONES_ADMIN: dict[str, float] = {}

INTENTOS: dict[str, list] = {}          # usuarios y "admin:<ip>"

AVISOS: dict[str, list] = {}

BASE_EMBEDDINGS: dict[str, dict] = {}

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


