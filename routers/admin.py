import hmac
import os
import secrets
import time
from fastapi import APIRouter, Request, HTTPException

from config import (ADMIN_SOLO_LOCAL, CLAVE_ADMIN, ADMIN_SESION_S, COLECCION,
                    DIRECTORIO_CARAS, DIRECTORIO_PENDIENTES)
from estado import INTENTOS, SESIONES_ADMIN, SESIONES, _CACHE_ESTADO, LOCK_BASE, BASE_EMBEDDINGS
from fotos import archivos_de, pendientes_de
from logs import log
from pocketbase import pb, pb_usuario
from schemas import AdminLogin, Decision
from seguridad import autenticar_admin, es_local, controlar_bloqueo, registrar_fallo, normalizar_usuario

router = APIRouter()

@router.post("/admin/login")
async def admin_login(datos: AdminLogin, request: Request):
    """Autentica al administrador y emite un token de sesión."""
    if ADMIN_SOLO_LOCAL and not es_local(request):
        raise HTTPException(status_code=404, detail="No encontrado")
    clave_int = f"admin:{request.client.host if request.client else '?'}"
    controlar_bloqueo(clave_int)
    if not hmac.compare_digest(datos.clave.encode(), CLAVE_ADMIN.encode()):
        registrar_fallo(clave_int)
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    INTENTOS.pop(clave_int, None)
    ahora = time.time()
    for t in [t for t, exp in SESIONES_ADMIN.items() if exp < ahora]:
        SESIONES_ADMIN.pop(t, None)
    token = secrets.token_hex(24)
    SESIONES_ADMIN[token] = ahora + ADMIN_SESION_S
    log("ADMIN", f"Sesión de administrador iniciada")
    return {"token": token}

@router.get("/admin/usuarios")
async def admin_usuarios(request: Request):
    """Lista usuarios y cantidad de fotos registradas para el panel."""
    autenticar_admin(request)
    r = pb("GET", f"/api/collections/{COLECCION}/records", params={"perPage": 200, "sort": "creado"})
    if r.status_code != 200:
        raise HTTPException(status_code=503, detail="La base de datos de usuarios no está disponible.")
    return {"usuarios": [{"usuario": f["usuario"], "estado": f["estado"], "creado": f.get("creado", ""),
                          "fotos": len(archivos_de(f["usuario"]))} for f in r.json()["items"]]}

@router.post("/admin/decidir")
async def admin_decidir(datos: Decision, request: Request):
    """Aprueba o rechaza una solicitud de usuario."""
    autenticar_admin(request)
    usuario = normalizar_usuario(datos.usuario)
    if datos.accion not in ("aprobar", "rechazar"):
        raise HTTPException(status_code=400, detail="Acción inválida")
    nuevo = "aprobado" if datos.accion == "aprobar" else "rechazado"
    rec = pb_usuario(usuario)
    if not rec:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    r = pb("PATCH", f"/api/collections/{COLECCION}/records/{rec['id']}", json={"estado": nuevo})
    if r.status_code != 200:
        raise HTTPException(status_code=503, detail="No se pudo actualizar el usuario.")
    _CACHE_ESTADO.pop(usuario, None)
    log("ADMIN", f"{usuario} -> {nuevo}")
    return {"ok": True, "usuario": usuario, "estado": nuevo}

@router.delete("/admin/usuario/{usuario}")
async def admin_eliminar(usuario: str, request: Request):
    """Elimina un usuario, sus fotos, sesiones y embeddings asociados."""
    autenticar_admin(request)
    usuario = normalizar_usuario(usuario)
    rec = pb_usuario(usuario)
    if rec:
        r = pb("DELETE", f"/api/collections/{COLECCION}/records/{rec['id']}")
        if r.status_code not in (200, 204):
            raise HTTPException(status_code=503, detail="No se pudo eliminar el usuario.")
    _CACHE_ESTADO.pop(usuario, None)
    for t in [t for t, (u, _) in SESIONES.items() if u == usuario]:
        SESIONES.pop(t, None)
    for carpeta, lista in ((DIRECTORIO_CARAS, archivos_de(usuario)), (DIRECTORIO_PENDIENTES, pendientes_de(usuario))):
        for f in lista:
            try:
                os.remove(os.path.join(carpeta, f))
            except OSError:
                pass
    with LOCK_BASE:
        for f in [f for f, d in BASE_EMBEDDINGS.items() if d["persona"] == usuario.capitalize()]:
            BASE_EMBEDDINGS.pop(f, None)
    log("ADMIN", f"Usuario eliminado: {usuario}")
    return {"ok": True}


