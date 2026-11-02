import re

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from logs import log
from pocketbase import pb, normalizar_uid, UID_RE

router = APIRouter()

# Colección de PocketBase con los campos "uid" y "numero_aula".
COLECCION_LLAVEROS = "tags"


class EventoLlave(BaseModel):
    numero_aula: str = ""
    evento: str
    uid: str = ""
    detalle: str = ""


def _registros(params: dict) -> list | None:
    """Lee la colección de llaveros. Devuelve None si PocketBase falla."""
    try:
        r = pb("GET", f"/api/collections/{COLECCION_LLAVEROS}/records", params=params)
    except Exception as e:
        log("LLAVES", f"PocketBase no disponible: {str(e)[:120]}")
        return None
    if r.status_code != 200:
        log("LLAVES", f"No pude leer '{COLECCION_LLAVEROS}': {r.status_code} {r.text[:120]}")
        return None
    return r.json().get("items", [])


def _uids_de_aula(numero_aula: str) -> list | None:
    items = _registros({"filter": f'numero_aula="{numero_aula}"', "perPage": 100})
    if items is None:
        return None
    uids = []
    for it in items:
        uid = normalizar_uid(it.get("uid", ""))
        if re.fullmatch(UID_RE, uid) and uid not in uids:
            uids.append(uid)
    return uids


def _aula_de_uid(uid: str) -> str | None:
    items = _registros({"perPage": 500})
    if items is None:
        return None
    for it in items:
        if normalizar_uid(it.get("uid", "")) == uid:
            return str(it.get("numero_aula", ""))
    return ""


@router.get("/dispensador/llave/{numero_aula}")
async def pedir_llave(numero_aula: str):
    """El dispensador pregunta qué UID(s) corresponden a un aula."""
    if not re.fullmatch(r"\d{1,6}", numero_aula):
        return {"ok": False, "error": "Aula inválida."}
    uids = await run_in_threadpool(_uids_de_aula, numero_aula)
    if uids is None:
        return {"ok": False, "error": "Base de datos no disponible."}
    if not uids:
        log("LLAVES", f"Pedido de aula {numero_aula}: no tiene llavero cargado")
        return {"ok": False, "error": "Esa aula no tiene llavero."}
    log("LLAVES", f"Pedido de aula {numero_aula}: uids {uids}")
    return {"ok": True, "aula": numero_aula, "uids": uids}


@router.get("/dispensador/llave-por-uid/{uid}")
async def aula_por_uid(uid: str):
    """El dispensador pregunta a qué aula pertenece un llavero (devoluciones)."""
    uid = normalizar_uid(uid)
    if not re.fullmatch(UID_RE, uid):
        return {"ok": False, "error": "UID inválido."}
    aula = await run_in_threadpool(_aula_de_uid, uid)
    if aula is None:
        return {"ok": False, "error": "Base de datos no disponible."}
    if not aula:
        return {"ok": False, "error": "Llavero desconocido."}
    return {"ok": True, "uid": uid, "aula": aula}


@router.post("/dispensador/llave/evento")
async def evento_llave(datos: EventoLlave):
    """Eventos de pedidos hechos por teclado: encontrada, entregada, error."""
    log("LLAVES", f"Aula {datos.numero_aula or '?'}: {datos.evento} "
                  f"{datos.uid} {datos.detalle}".strip())
    return {"ok": True}