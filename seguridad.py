import hashlib
import hmac
import re
import secrets
import time
from fastapi import Request, HTTPException

from config import (RESERVADOS, MAX_INTENTOS, BLOQUEO_S, SESION_S, ADMIN_SOLO_LOCAL, ADMIN_SESION_S,
                    PBKDF2_ITERACIONES)
from estado import INTENTOS, SESIONES, SESIONES_ADMIN
from logs import log
from pocketbase import pb_usuario, estado_de

def normalizar_usuario(u: str) -> str:
    """Normaliza el nombre de usuario eliminando espacios y dejando minúsculas."""
    return (u or "").strip().lower()

def usuario_valido(u: str) -> bool:
    """Valida formato de usuario y descarta nombres reservados."""
    return re.fullmatch(r"[a-z]{3,20}", u) is not None and u not in RESERVADOS

def hash_pin(pin: str, salt: bytes) -> bytes:
    """Deriva un hash PBKDF2-HMAC-SHA256 del PIN con la sal indicada."""
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, PBKDF2_ITERACIONES)

def controlar_bloqueo(clave: str):
    """Rechaza peticiones recientes de claves bloqueadas por intentos fallidos."""
    est = INTENTOS.get(clave)
    if est and est[1] > time.time():
        raise HTTPException(status_code=429, detail="Demasiados intentos. Espera un minuto.")

def registrar_fallo(clave: str):
    """Cuenta un intento fallido y bloquea la clave al superar el límite."""
    est = INTENTOS.get(clave)
    fallos = (est[0] if est else 0) + 1
    if fallos >= MAX_INTENTOS:
        INTENTOS[clave] = [0, time.time() + BLOQUEO_S]
        log("SEGURIDAD", f"'{clave}' bloqueado {BLOQUEO_S}s por intentos fallidos")
    else:
        INTENTOS[clave] = [fallos, 0]

def verificar_pin(usuario: str, pin: str) -> bool:
    """Verifica usuario y PIN contra PocketBase aplicando el control de bloqueo."""
    usuario = normalizar_usuario(usuario)
    controlar_bloqueo(usuario)
    fila = pb_usuario(usuario)
    ok = bool(fila) and hmac.compare_digest(hash_pin(pin or "", bytes.fromhex(fila["salt"])),
                                            bytes.fromhex(fila["pin_hash"]))
    if ok:
        INTENTOS.pop(usuario, None)
        return True
    registrar_fallo(usuario)
    return False

def crear_sesion(usuario: str) -> str:
    """Crea un token de sesión, purgando antes las sesiones vencidas."""
    ahora = time.time()
    for t in [t for t, (_, exp) in SESIONES.items() if exp < ahora]:
        SESIONES.pop(t, None)
    token = secrets.token_hex(16)
    SESIONES[token] = (usuario, ahora + SESION_S)
    return token

def usuario_de_sesion(request: Request) -> str | None:
    """Recupera el usuario desde el token x-token y renueva la sesión."""
    token = request.headers.get("x-token", "")
    s = SESIONES.get(token)
    if not s or s[1] < time.time():
        SESIONES.pop(token, None)
        return None
    SESIONES[token] = (s[0], time.time() + SESION_S)
    return s[0]

def autenticar(request: Request, aprobado: bool = True) -> str:
    """Devuelve el usuario de la sesión. Con aprobado=True exige que el admin ya lo haya aceptado."""
    usuario = usuario_de_sesion(request)
    if not usuario:
        raise HTTPException(status_code=401, detail="Sesión no válida. Vuelve a entrar.")
    if aprobado and estado_de(usuario) != "aprobado":
        raise HTTPException(status_code=403, detail="Tu cuenta todavía no fue aprobada por el administrador.")
    return usuario

def es_local(request: Request) -> bool:
    """Indica si la petición viene del propio equipo."""
    return (request.client.host if request.client else "") in ("127.0.0.1", "::1", "localhost")

def autenticar_admin(request: Request):
    """Exige una cabecera x-admin válida para acceder a administración."""
    if ADMIN_SOLO_LOCAL and not es_local(request):
        raise HTTPException(status_code=404, detail="No encontrado")
    token = request.headers.get("x-admin", "")
    exp = SESIONES_ADMIN.get(token)
    if not exp or exp < time.time():
        SESIONES_ADMIN.pop(token, None)
        raise HTTPException(status_code=401, detail="Sesión de administrador no válida.")
    SESIONES_ADMIN[token] = time.time() + ADMIN_SESION_S


