import time
from fastapi import APIRouter, HTTPException

from config import MAX_INTENTOS
from db import (aula_por_id, registrar_prestamo, prestamo_activo)
from estado import SOLICITUD_LLAVE, LOCK_SOLICITUD, ULTIMA_AUTORIZACION, ULTIMO_EVENTO_DISPENSADOR
from logs import log, obtener_hora
from schemas import PedidoDispensador, PinDispensador, EventoDispensador
from seguridad import verificar_pin

router = APIRouter()

# Bloqueo por aula_id tras superar MAX_INTENTOS fallos de rostro: aula -> [intentos, bloqueado_hasta]
_INTENTOS_ROSTRO: dict[int, list] = {}


def _limpiar_solicitud() -> None:
    """Reinicia la solicitud activa."""
    with LOCK_SOLICITUD:
        SOLICITUD_LLAVE.update({"activa": False, "aula_id": None, "aula_nombre": "",
                                "persona": "", "rfid": "", "requiere_pin": False,
                                "intentos_rostro": 0, "creada": 0.0})


def _snapshot_solicitud() -> dict:
    """Copia segura de la solicitud para responder al ESP32."""
    with LOCK_SOLICITUD:
        return dict(SOLICITUD_LLAVE)


def _crear_solicitud(aula: dict, persona: str, requiere_pin: bool) -> None:
    """Marca la solicitud activa para que el ESP32 vaya a buscar la llave.

    No valida préstamos: el llamador decide si corresponde (el pedido web ya
    registra el préstamo antes de llamar a esto).
    """
    with LOCK_SOLICITUD:
        SOLICITUD_LLAVE.update({"activa": True, "aula_id": aula["id"],
                                "aula_nombre": aula["nombre"], "persona": persona,
                                "rfid": aula["rfid"], "requiere_pin": requiere_pin,
                                "intentos_rostro": 0, "creada": time.time()})
    _INTENTOS_ROSTRO.pop(aula["id"], None)
    log("DISPENSADOR", f"Solicitud activa para '{aula['nombre']}' (rfid {aula['rfid']})")


def _registrar_fallo_rostro(aula_id: int) -> int:
    """Cuenta un fallo de reconocimiento para el aula y devuelve los intentos restantes."""
    with LOCK_SOLICITUD:
        est = _INTENTOS_ROSTRO.get(aula_id, [0, 0.0])
        # Si el bloqueo venció, se reinicia la cuenta.
        if est[1] and est[1] < time.time():
            est = [0, 0.0]
        est[0] += 1
        restantes = MAX_INTENTOS - est[0]
        if restantes <= 0:
            est[1] = time.time() + 300      # 5 minutos de bloqueo, luego pide PIN
            SOLICITUD_LLAVE["requiere_pin"] = SOLICITUD_LLAVE.get("aula_id") == aula_id
            log("SEGURIDAD", f"Aula {aula_id}: {MAX_INTENTOS} fallos de rostro, se requiere PIN")
        _INTENTOS_ROSTRO[aula_id] = est
        return max(restantes, 0)


def _registrar_acierto_rostro(aula_id: int, persona: str) -> None:
    """El rostro fue aprobado: reinicia la cuenta de fallos de esa aula."""
    _INTENTOS_ROSTRO.pop(aula_id, None)
    log("DISPENSADOR", f"Rostro aprobado para aula {aula_id}: {persona or '?'}")


@router.get("/dispensador/solicitud")
async def obtener_solicitud() -> dict:
    """El ESP32 consulta qué llave debe buscar. Devuelve la solicitud vigente."""
    sol = _snapshot_solicitud()
    if not sol["activa"] or not sol.get("aula_id"):
        return {"activa": False}

    aula = aula_por_id(sol["aula_id"]) or {}
    return {
        "activa": True,
        "aula_id": sol["aula_id"],
        "aula_nombre": aula.get("nombre", sol["aula_nombre"]),
        "persona": sol["persona"],
        "rfid": aula.get("rfid", ""),
        "requiere_pin": sol["requiere_pin"],
        "intentos_rostro": sol["intentos_rostro"],
    }


@router.post("/dispensador/solicitar")
async def solicitar_llave(datos: PedidoDispensador) -> dict:
    """Crea (o reemplaza) la solicitud de entrega de una llave."""
    aula = aula_por_id(datos.aula_id)
    if not aula:
        return {"ok": False, "error": "Ese aula no existe."}
    if not aula["activa"]:
        return {"ok": False, "error": "Ese aula está deshabilitada."}
    if not aula["rfid"]:
        return {"ok": False, "error": f"El aula '{aula['nombre']}' no tiene tag RFID asignado."}
    if prestamo_activo(datos.aula_id):
        return {"ok": False, "error": "Esa llave todavía no fue devuelta."}

    _crear_solicitud(aula, datos.persona, datos.requiere_pin)
    return {"ok": True, "aula_nombre": aula["nombre"], "rfid": aula["rfid"]}


@router.post("/dispensador/cancelar")
async def cancelar_solicitud() -> dict:
    """Cancela la solicitud activa (por ejemplo, desde el panel)."""
    _limpiar_solicitud()
    log("DISPENSADOR", "Solicitud cancelada")
    return {"ok": True}


@router.post("/dispensador/pin")
async def validar_pin(datos: PinDispensador) -> dict:
    """Valida el PIN escrito en el teclado del dispensador contra el usuario aprobado."""
    sol = _snapshot_solicitud()
    persona = (datos.persona or sol.get("persona") or "").strip().lower()

    # La persona llega en la solicitud activa; si no hay, se intenta por el aula.
    if not persona:
        return {"ok": False, "error": "Sin sesión activa. Volvé a empezar."}

    try:
        if not verificar_pin(persona, datos.pin):
            return {"ok": False, "error": "PIN incorrecto."}
    except HTTPException as e:
        # Bloqueo temporal por intentos fallidos (429) o PocketBase caído (503).
        return {"ok": False, "error": e.detail}
    return {"ok": True, "persona": persona}


@router.post("/dispensador/confirmar")
async def confirmar_evento(datos: EventoDispensador) -> dict:
    """Recibe los eventos del dispensador: encontrada, entregada, error o bloqueado."""
    ULTIMO_EVENTO_DISPENSADOR.update({"evento": datos.evento, "detalle": datos.detalle,
                                      "ts": time.time()})
    aula = aula_por_id(datos.aula_id) if datos.aula_id else None
    nombre = aula["nombre"] if aula else (datos.persona or "?")

    if datos.evento == "encontrada":
        log("DISPENSADOR", f"Llave de '{nombre}' posicionada ({datos.detalle})")
    elif datos.evento == "entregada":
        log("DISPENSADOR", f"Llave de '{nombre}' retirada")
        if aula and not prestamo_activo(aula["id"]):
            # Flujo en que el pedido entró directo desde la placa: el préstamo
            # se registra recién ahora. Si vino de la web, ya existe uno activo.
            persona = datos.persona or _snapshot_solicitud().get("persona") or None
            ULTIMA_AUTORIZACION[str(aula["id"])] = (persona or "Desconocido", time.time())
            registrar_prestamo(aula["id"], persona or "Desconocido",
                               "Retiro en dispensador", obtener_hora(), persona or "dispensador")
        _limpiar_solicitud()
    elif datos.evento == "error":
        log("DISPENSADOR", f"Error en '{nombre}': {datos.detalle}")
        _limpiar_solicitud()
    elif datos.evento == "bloqueado":
        log("SEGURIDAD", f"Aula {datos.aula_id} bloqueada por intentos fallidos")
        _limpiar_solicitud()
    else:
        log("DISPENSADOR", f"Evento desconocido '{datos.evento}': {datos.detalle}")

    return {"ok": True}


@router.post("/dispensador/rostro/fallo")
async def fallo_rostro(aula_id: int) -> dict:
    """El reconocimiento facial falló: cuenta el intento y avisa si se pasa a PIN."""
    if not aula_por_id(aula_id):
        return {"ok": False, "error": "Ese aula no existe."}
    restantes = _registrar_fallo_rostro(aula_id)
    with LOCK_SOLICITUD:
        if SOLICITUD_LLAVE.get("aula_id") == aula_id:
            SOLICITUD_LLAVE["intentos_rostro"] = SOLICITUD_LLAVE.get("intentos_rostro", 0) + 1
    return {"ok": True, "restantes": restantes, "requiere_pin": restantes <= 0}


@router.post("/dispensador/rostro/ok")
async def acierto_rostro(aula_id: int, persona: str = "") -> dict:
    """El reconocimiento facial acertó: limpia los intentos fallidos del aula."""
    _INTENTOS_ROSTRO.pop(aula_id, None)
    log("DISPENSADOR", f"Rostro aprobado para aula {aula_id}: {persona or '?'}")
    return {"ok": True}


@router.get("/dispensador/estado")
async def estado_dispensador() -> dict:
    """Estado actual del dispensador para el panel de administración."""
    from db import aulas
    sol = _snapshot_solicitud()
    return {
        "solicitud": sol,
        "ultimo_evento": dict(ULTIMO_EVENTO_DISPENSADOR),
        "aulas": [{**a, "tiene_rfid": bool(a["rfid"])} for a in aulas()],
    }
