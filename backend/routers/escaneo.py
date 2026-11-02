import re
import time
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from seguridad import autenticar_admin
from pocketbase import tag_por_uid, normalizar_uid, UID_RE

router = APIRouter()

VENCE_S = 30
_ESCANEO = {"activo": False, "hasta": 0.0, "uid": "", "ts": 0.0, "ya_registrado": False}


class UidLeido(BaseModel):
    uid: str


def _vencer() -> None:
    if _ESCANEO["activo"] and time.time() > _ESCANEO["hasta"]:
        _ESCANEO["activo"] = False


@router.post("/admin/escaneo/iniciar")
async def iniciar_escaneo(request: Request):
    """El admin pide escanear una tarjeta nueva."""
    autenticar_admin(request)
    _ESCANEO.update({"activo": True, "hasta": time.time() + VENCE_S,
                     "uid": "", "ts": 0.0, "ya_registrado": False})
    return {"ok": True, "vence_en": VENCE_S}


@router.post("/admin/escaneo/cancelar")
async def cancelar_escaneo(request: Request):
    autenticar_admin(request)
    _ESCANEO.update({"activo": False, "uid": "", "ya_registrado": False})
    return {"ok": True}


@router.get("/admin/escaneo")
async def estado_escaneo(request: Request):
    """La web consulta esto cada segundo mientras espera la tarjeta."""
    autenticar_admin(request)
    _vencer()
    return {"activo": _ESCANEO["activo"], "uid": _ESCANEO["uid"],
            "ya_registrado": _ESCANEO["ya_registrado"]}


@router.get("/dispensador/modo-escaneo")
async def modo_escaneo():
    """El ESP32 pregunta si debe mandar el próximo UID como alta."""
    _vencer()
    return {"activo": _ESCANEO["activo"]}


@router.post("/dispensador/escaneo")
async def recibir_uid(datos: UidLeido):
    """El ESP32 manda el UID leído. Solo se acepta si el admin pidió escanear."""
    _vencer()
    if not _ESCANEO["activo"]:
        return {"ok": False, "error": "No hay un escaneo pedido."}
    uid = normalizar_uid(datos.uid)
    if not re.fullmatch(UID_RE, uid):
        return {"ok": False, "error": "UID inválido."}
    ya = await run_in_threadpool(tag_por_uid, uid, False)
    _ESCANEO.update({"uid": uid, "ts": time.time(), "activo": False, "ya_registrado": bool(ya)})
    return {"ok": True, "uid": uid, "ya_registrado": bool(ya)}