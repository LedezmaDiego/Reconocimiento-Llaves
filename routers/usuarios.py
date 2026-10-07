import os
import re
import secrets
import time
from fastapi import APIRouter, HTTPException

from config import COLECCION, MAX_PENDIENTES, SESION_S, CODIGO_VALIDO_S
from estado import _CACHE_ESTADO, SESIONES, ACCESO_CODIGO
from logs import obtener_hora, log
from pocketbase import pb, pb_usuario, estado_de
from schemas import SolicitudAcceso, LoginDatos, AccesoCodigo
from seguridad import normalizar_usuario, usuario_valido, hash_pin, verificar_pin

router = APIRouter()

@router.post("/solicitar_acceso")
async def solicitar_acceso(datos: SolicitudAcceso):
    """Registra una solicitud nueva de acceso pendiente de aprobación."""
    usuario = normalizar_usuario(datos.usuario)
    if not usuario_valido(usuario):
        raise HTTPException(status_code=400, detail="Usuario inválido: solo letras, de 3 a 20 caracteres")
    if not re.fullmatch(r"\d{4,8}", datos.pin):
        raise HTTPException(status_code=400, detail="El código personal debe tener de 4 a 8 números")

    r = pb("GET", f"/api/collections/{COLECCION}/records",
           params={"filter": 'estado="pendiente"', "perPage": 1})
    if r.status_code == 200 and r.json().get("totalItems", 0) >= MAX_PENDIENTES:
        raise HTTPException(status_code=429, detail="Hay demasiadas solicitudes pendientes. Avisá al administrador.")
    if pb_usuario(usuario):
        raise HTTPException(status_code=409, detail="Ese usuario ya existe")

    salt = os.urandom(16)
    r = pb("POST", f"/api/collections/{COLECCION}/records", json={
        "usuario": usuario, "salt": salt.hex(), "pin_hash": hash_pin(datos.pin, salt).hex(),
        "estado": "pendiente", "creado": obtener_hora()})
    if r.status_code == 400:
        raise HTTPException(status_code=409, detail="Ese usuario ya existe")
    if r.status_code not in (200, 201):
        raise HTTPException(status_code=503, detail="No se pudo guardar la solicitud. Intentá de nuevo.")
    _CACHE_ESTADO.pop(usuario, None)

    log("SOLICITUD", f"Nueva solicitud de acceso: {usuario}")
    return {"ok": True, "usuario": usuario}

@router.post("/login")
async def login(datos: LoginDatos):
    """Autentica un usuario y devuelve su token de sesión temporal."""
    usuario = normalizar_usuario(datos.usuario)
    if not verificar_pin(usuario, datos.pin):
        raise HTTPException(status_code=401, detail="Usuario o código incorrecto")
    ahora = time.time()
    for t in [t for t, (_, exp) in SESIONES.items() if exp < ahora]:
        SESIONES.pop(t, None)
    token = secrets.token_hex(16)
    SESIONES[token] = (usuario, ahora + SESION_S)
    return {"token": token, "usuario": usuario, "estado": estado_de(usuario)}

@router.post("/acceso_codigo")
async def acceso_codigo(datos: AccesoCodigo):
    """Autoriza un casillero usando usuario y código personal."""
    usuario = normalizar_usuario(datos.usuario)
    if not verificar_pin(usuario, datos.pin):
        raise HTTPException(status_code=401, detail="Usuario o código incorrecto")
    if estado_de(usuario) != "aprobado":
        raise HTTPException(status_code=403, detail="Tu cuenta todavía no fue aprobada por el administrador.")
    ACCESO_CODIGO[datos.casillero_id] = (usuario, time.time())
    log("CÓDIGO", f"{usuario} autorizó el casillero {datos.casillero_id} con su código")
    return {"ok": True,
            "mensaje": f"Código correcto. Párate frente a la cámara: se abrirá en unos segundos ({CODIGO_VALIDO_S} s de validez)."}


