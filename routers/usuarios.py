import os
import re
import secrets
import time
from fastapi import APIRouter, HTTPException

from config import COLECCION, MAX_PENDIENTES, LOGIN_ROSTRO_TIMEOUT_S, CODIGO_VALIDO_S
from estado import _CACHE_ESTADO, ACCESO_CODIGO, LOGIN_ROSTRO
from logs import obtener_hora, log
from fotos import archivos_de
from pocketbase import pb, pb_usuario, estado_de
from schemas import SolicitudAcceso, LoginDatos, AccesoCodigo, UsuarioSimple
from seguridad import (normalizar_usuario, usuario_valido, hash_pin, verificar_pin,
                        crear_sesion)

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
    return {"token": crear_sesion(usuario), "usuario": usuario, "estado": estado_de(usuario)}

@router.post("/preparar_login")
async def preparar_login(datos: UsuarioSimple):
    """Paso 1 del inicio de sesión: indica si el usuario existe y qué métodos puede usar."""
    usuario = normalizar_usuario(datos.usuario)
    if not usuario_valido(usuario):
        raise HTTPException(status_code=400, detail="Usuario inválido: solo letras, de 3 a 20 caracteres")
    rec = pb_usuario(usuario)
    if not rec:
        raise HTTPException(status_code=404, detail="Ese usuario no existe. Solicitá acceso primero.")
    return {"usuario": usuario, "estado": rec["estado"], "puede_rostro": bool(archivos_de(usuario))}

@router.post("/login_rostro")
async def login_rostro(datos: UsuarioSimple):
    """Paso 2 alternativo: abre una espera de inicio de sesión por reconocimiento facial."""
    usuario = normalizar_usuario(datos.usuario)
    if not usuario_valido(usuario):
        raise HTTPException(status_code=400, detail="Usuario inválido: solo letras, de 3 a 20 caracteres")
    if not pb_usuario(usuario):
        raise HTTPException(status_code=404, detail="Ese usuario no existe. Solicitá acceso primero.")
    if not archivos_de(usuario):
        raise HTTPException(status_code=409, detail="No tenés fotos registradas. Entrá con tu PIN.")

    ahora = time.time()
    for clave, pendiente in [ (k, v) for k, v in LOGIN_ROSTRO.items() if v["expira"] < ahora ]:
        LOGIN_ROSTRO.pop(clave, None)
    if sum(1 for v in LOGIN_ROSTRO.values() if v["usuario"] == usuario and v["estado"] == "esperando") >= 2:
        raise HTTPException(status_code=429, detail="Ya hay una espera de reconocimiento en curso.")

    solicitud_id = secrets.token_hex(8)
    LOGIN_ROSTRO[solicitud_id] = {"usuario": usuario, "expira": ahora + LOGIN_ROSTRO_TIMEOUT_S,
                                  "estado": "esperando", "token": None, "aviso": None}
    log("ACCESO", f"{usuario}: esperando reconocimiento facial")
    return {"ok": True, "solicitud_id": solicitud_id, "espera_s": LOGIN_ROSTRO_TIMEOUT_S}

@router.get("/login_rostro/{solicitud_id}")
async def estado_login_rostro(solicitud_id: str):
    """Consulta el estado de una espera de reconocimiento facial."""
    pendiente = LOGIN_ROSTRO.get(solicitud_id)
    if not pendiente:
        raise HTTPException(status_code=404, detail="La espera no existe o venció.")
    if pendiente["expira"] < time.time() and pendiente["estado"] == "esperando":
        pendiente["estado"] = "expirado"
    if pendiente["estado"] == "autorizado":
        LOGIN_ROSTRO.pop(solicitud_id, None)   # El token se entrega una única vez.
        return {"estado": "autorizado", "token": pendiente["token"], "usuario": pendiente["usuario"]}
    return {"estado": pendiente["estado"], "usuario": pendiente["usuario"], "aviso": pendiente["aviso"]}

@router.delete("/login_rostro/{solicitud_id}")
async def cancelar_login_rostro(solicitud_id: str):
    """Cancela una espera de reconocimiento facial."""
    LOGIN_ROSTRO.pop(solicitud_id, None)
    return {"ok": True}

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


