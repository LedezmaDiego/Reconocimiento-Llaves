import re
import time
import requests
from fastapi import HTTPException

from config import (PB_URL, PB_EMAIL, PB_PASSWORD, COLECCION, PB_TIMEOUT_S,
                    CACHE_ESTADO_S, LONGITUD_ERROR_PB, LONGITUD_TEXTO_COLECCION)
from estado import _PB, LOCK_PB, _CACHE_ESTADO
from logs import log

def pb_login() -> None:
    """Autentica con PocketBase y renueva el token de superusuario."""
    r = requests.post(f"{PB_URL}/api/collections/_superusers/auth-with-password",
                      json={"identity": PB_EMAIL, "password": PB_PASSWORD}, timeout=PB_TIMEOUT_S)
    r.raise_for_status()
    _PB["token"] = r.json()["token"]

def pb(metodo: str, ruta: str, **kw) -> requests.Response:
    """Llamada a PocketBase con el token de superusuario (se renueva solo)."""
    try:
        for intento in (1, 2):
            if not _PB["token"]:
                with LOCK_PB:
                    if not _PB["token"]:
                        pb_login()
            r = requests.request(metodo, f"{PB_URL}{ruta}", headers={"Authorization": _PB["token"]},
                                 timeout=PB_TIMEOUT_S, **kw)
            if r.status_code in (401, 403) and intento == 1:
                _PB["token"] = None
                continue
            return r
    except requests.RequestException as e:
        log("POCKETBASE", f"No disponible o credenciales inválidas: {str(e)[:LONGITUD_ERROR_PB]}")
        raise HTTPException(status_code=503, detail="La base de datos de usuarios no está disponible.")

def pb_usuario(usuario: str) -> dict | None:
    """Busca un usuario en PocketBase y evita el filtro si tiene formato inválido."""
    if not re.fullmatch(r"[a-z]{3,20}", usuario or ""):   # también evita inyección en el filtro
        return None
    r = pb("GET", f"/api/collections/{COLECCION}/records",
           params={"filter": f'usuario="{usuario}"', "perPage": 1})
    if r.status_code != 200:
        raise HTTPException(status_code=503, detail="La base de datos de usuarios no está disponible.")
    items = r.json().get("items", [])
    return items[0] if items else None

def asegurar_coleccion() -> None:
    """Crea la colección 'personal' en PocketBase si todavía no existe."""
    r = pb("GET", f"/api/collections/{COLECCION}")
    if r.status_code == 200:
        return
    esquema = {
        "name": COLECCION, "type": "base",
        "fields": [
            {"name": "usuario", "type": "text", "required": True},
            {"name": "salt", "type": "text", "required": True},
            {"name": "pin_hash", "type": "text", "required": True},
            {"name": "estado", "type": "select", "required": True, "maxSelect": 1,
             "values": ["pendiente", "aprobado", "rechazado"]},
            {"name": "creado", "type": "text"},
        ],
        "indexes": [f"CREATE UNIQUE INDEX idx_{COLECCION}_usuario ON {COLECCION} (usuario)"],
        # Sin reglas (null) = solo superusuarios: nadie puede leerla desde fuera del servidor
        "listRule": None, "viewRule": None, "createRule": None, "updateRule": None, "deleteRule": None,
    }
    r = pb("POST", "/api/collections", json=esquema)
    if r.status_code in (200, 201):
        log("POCKETBASE", f"Colección '{COLECCION}' creada")
    else:
        log("POCKETBASE", f"No pude crear la colección: {r.status_code} {r.text[:LONGITUD_TEXTO_COLECCION]}")

def estado_de(usuario: str) -> str | None:
    """Devuelve el estado aprobado, pendiente o rechazado usando una caché corta."""
    c = _CACHE_ESTADO.get(usuario)
    if c and c[1] > time.time():
        return c[0]
    rec = pb_usuario(usuario)
    est = rec["estado"] if rec else None
    _CACHE_ESTADO[usuario] = (est, time.time() + CACHE_ESTADO_S)
    return est


