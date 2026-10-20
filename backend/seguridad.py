import hashlib
import hmac
import re
import secrets
import time
from fastapi import Request, HTTPException

from config import (RESERVADOS, MAX_INTENTOS, BLOQUEO_S, SESION_S, ADMIN_SOLO_LOCAL, ADMIN_SESION_S,
                    PBKDF2_ITERACIONES, COLECCION_SESIONES)
from estado import INTENTOS
from logs import log
from pocketbase import pb, pb_usuario, estado_de, pb_login

# Sesiones en memoria como caché ultra-rápida (se sincronizan con PocketBase)
_SESIONES_CACHE: dict[str, tuple[str, float]] = {}
_SESIONES_ADMIN_CACHE: dict[str, float] = {}

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

def _cache_sesion(token: str, usuario: str, expira: float) -> None:
    """Guarda en caché local para acceso ultra-rápido."""
    _SESIONES_CACHE[token] = (usuario, expira)

def _cache_sesion_admin(token: str, expira: float) -> None:
    _SESIONES_ADMIN_CACHE[token] = expira

def _leer_sesion_cache(token: str) -> tuple[str, float] | None:
    s = _SESIONES_CACHE.get(token)
    if s and s[1] > time.time():
        return s
    _SESIONES_CACHE.pop(token, None)
    return None

def _leer_sesion_admin_cache(token: str) -> float | None:
    exp = _SESIONES_ADMIN_CACHE.get(token)
    if exp and exp > time.time():
        return exp
    _SESIONES_ADMIN_CACHE.pop(token, None)
    return None

def _guardar_sesion_pb(token: str, usuario: str, tipo: str, expira: float) -> None:
    """Guarda/actualiza sesión en PocketBase."""
    try:
        # Verificar si existe
        r = pb("GET", f"/api/collections/{COLECCION_SESIONES}/records",
               params={"filter": f'token="{token}"', "perPage": 1})
        if r.status_code == 200 and r.json().get("items"):
            item_id = r.json()["items"][0]["id"]
            pb("PATCH", f"/api/collections/{COLECCION_SESIONES}/records/{item_id}",
               json={"expira": int(expira)})
        else:
            ahora = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            pb("POST", f"/api/collections/{COLECCION_SESIONES}/records", json={
                "token": token, "usuario": usuario, "tipo": tipo,
                "expira": int(expira), "creado": ahora
            })
    except Exception as e:
        log("SEGURIDAD", f"Error guardando sesión en PB: {e}")

def _borrar_sesion_pb(token: str) -> None:
    """Borra sesión de PocketBase."""
    try:
        r = pb("GET", f"/api/collections/{COLECCION_SESIONES}/records",
               params={"filter": f'token="{token}"', "perPage": 1})
        if r.status_code == 200 and r.json().get("items"):
            item_id = r.json()["items"][0]["id"]
            pb("DELETE", f"/api/collections/{COLECCION_SESIONES}/records/{item_id}")
    except Exception:
        pass


def crear_sesion(usuario: str, tipo: str = "usuario") -> str:
    """Crea un token de sesión persistente en PocketBase (duración SESION_S)."""
    ahora = time.time()
    expira = ahora + SESION_S
    token = secrets.token_hex(16)
    _guardar_sesion_pb(token, usuario, tipo, expira)
    if tipo == "usuario":
        _cache_sesion(token, usuario, expira)
    else:
        _cache_sesion_admin(token, expira)
    return token


def usuario_de_sesion(request: Request) -> str | None:
    """Recupera el usuario desde el token x-token (caché + PocketBase)."""
    token = request.headers.get("x-token", "")
    if not token:
        return None
    # 1. Caché local
    s = _leer_sesion_cache(token)
    if s:
        usuario, expira = s
        # Renovar en caché y PB
        nueva_expira = time.time() + SESION_S
        _cache_sesion(token, usuario, nueva_expira)
        _guardar_sesion_pb(token, usuario, "usuario", nueva_expira)
        return usuario
    # 2. PocketBase
    try:
        r = pb("GET", f"/api/collections/{COLECCION_SESIONES}/records",
               params={"filter": f'token="{token}"', "perPage": 1})
        if r.status_code == 200:
            items = r.json().get("items", [])
            if items:
                item = items[0]
                if item["expira"] > time.time():
                    usuario = item["usuario"]
                    nueva_expira = time.time() + SESION_S
                    _cache_sesion(token, usuario, nueva_expira)
                    _guardar_sesion_pb(token, usuario, "usuario", nueva_expira)
                    return usuario
                else:
                    _borrar_sesion_pb(token)
    except Exception:
        pass
    return None


def autenticar(request: Request, aprobado: bool = True) -> str:
    """Devuelve el usuario de la sesión. Con aprobado=True exige que el admin ya lo haya aceptado."""
    usuario = usuario_de_sesion(request)
    if not usuario:
        raise HTTPException(status_code=401, detail="Sesión no válida. Vuelve a entrar.")
    if aprobado and estado_de(usuario) != "aprobado":
        raise HTTPException(status_code=403, detail="Tu cuenta todavía no fue aprobada por el administrador.")
    return usuario


def autenticar_admin(request: Request):
    """Exige una cabecera x-admin válida para acceder a administración (caché + PocketBase)."""
    if ADMIN_SOLO_LOCAL and not es_local(request):
        raise HTTPException(status_code=404, detail="No encontrado")
    token = request.headers.get("x-admin", "")
    if not token:
        raise HTTPException(status_code=401, detail="Sesión de administrador no válida.")
    # 1. Caché local
    exp = _leer_sesion_admin_cache(token)
    if exp:
        nueva_expira = time.time() + ADMIN_SESION_S
        _cache_sesion_admin(token, nueva_expira)
        _guardar_sesion_pb(token, "admin", "admin", nueva_expira)
        return
    # 2. PocketBase
    try:
        r = pb("GET", f"/api/collections/{COLECCION_SESIONES}/records",
               params={"filter": f'token="{token}" AND tipo="admin"', "perPage": 1})
        if r.status_code == 200:
            items = r.json().get("items", [])
            if items:
                item = items[0]
                if item["expira"] > time.time():
                    nueva_expira = time.time() + ADMIN_SESION_S
                    _cache_sesion_admin(token, nueva_expira)
                    _guardar_sesion_pb(token, "admin", "admin", nueva_expira)
                    return
                else:
                    _borrar_sesion_pb(token)
    except Exception:
        pass
    raise HTTPException(status_code=401, detail="Sesión de administrador no válida.")


def cerrar_sesion(request: Request) -> None:
    """Cierra la sesión del usuario (borra de caché y PB)."""
    token = request.headers.get("x-token", "")
    if token:
        _SESIONES_CACHE.pop(token, None)
        _borrar_sesion_pb(token)


def cerrar_sesion_admin(request: Request) -> None:
    """Cierra la sesión de admin (borra de caché y PB)."""
    token = request.headers.get("x-admin", "")
    if token:
        _SESIONES_ADMIN_CACHE.pop(token, None)
        _borrar_sesion_pb(token)


def es_local(request: Request) -> bool:
    """Indica si la petición viene del propio equipo."""
    return (request.client.host if request.client else "") in ("127.0.0.1", "::1", "localhost")


