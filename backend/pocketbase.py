import re
import time
import requests
from fastapi import HTTPException

from config import (PB_URL, PB_EMAIL, PB_PASSWORD, COLECCION, PB_TIMEOUT_S,
                    CACHE_ESTADO_S, LONGITUD_ERROR_PB, LONGITUD_TEXTO_COLECCION, COLECCION_SESIONES)
from estado import _PB, LOCK_PB, _CACHE_ESTADO
from logs import log

UID_RE = r"[A-F0-9]{4,20}"
_ULTIMA_FOTO_RECHAZO = {"ts": 0.0}


def normalizar_uid(uid: str) -> str:
    """Deja el UID en mayúsculas y sin separadores: '04:a3:2b:1f' -> '04A32B1F'."""
    return re.sub(r"[^A-Fa-f0-9]", "", uid or "").upper()


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
        log("POCKETBASE", f"Error consultando usuario: {r.status_code} {r.text[:LONGITUD_TEXTO_COLECCION]}")
        raise HTTPException(status_code=503, detail="La base de datos de usuarios no está disponible.")
    items = r.json().get("items", [])
    return items[0] if items else None


# ============================================================
#  Colecciones
# ============================================================
def _crear_coleccion(nombre: str, campos: list, indices: list) -> None:
    """Crea una colección sin índices y luego los agrega (los campos ya existen)."""
    r = pb("GET", f"/api/collections/{nombre}")
    if r.status_code == 200:
        return
    esquema = {
        "name": nombre, "type": "base",
        "fields": campos,
        # Sin reglas (null) = solo superusuarios: nadie puede acceder desde fuera del servidor
        "listRule": None, "viewRule": None, "createRule": None, "updateRule": None, "deleteRule": None,
    }
    r = pb("POST", "/api/collections", json=esquema)
    if r.status_code not in (200, 201):
        log("POCKETBASE", f"No pude crear la colección '{nombre}': {r.status_code} {r.text[:LONGITUD_TEXTO_COLECCION]}")
        return
    log("POCKETBASE", f"Colección '{nombre}' creada")
    r = pb("PATCH", f"/api/collections/{nombre}", json={"indexes": indices})
    if r.status_code != 200:
        log("POCKETBASE", f"No pude crear los índices de '{nombre}': {r.status_code} {r.text[:LONGITUD_TEXTO_COLECCION]}")


def asegurar_coleccion() -> None:
    """Colección 'personal' (usuarios)."""
    _crear_coleccion(
        COLECCION,
        [
            {"name": "usuario", "type": "text", "required": True},
            {"name": "salt", "type": "text", "required": True},
            {"name": "pin_hash", "type": "text", "required": True},
            {"name": "estado", "type": "select", "required": True,
             "maxSelect": 1, "values": ["pendiente", "aprobado", "rechazado"]},
            {"name": "creado", "type": "text", "required": False},
        ],
        [f"CREATE UNIQUE INDEX idx_{COLECCION}_usuario ON {COLECCION} (usuario)"],
    )


def asegurar_coleccion_sesiones() -> None:
    """Colección 'sesiones'."""
    _crear_coleccion(
        COLECCION_SESIONES,
        [
            {"name": "token", "type": "text", "required": True},
            {"name": "usuario", "type": "text", "required": True},
            {"name": "tipo", "type": "select", "required": True,
             "maxSelect": 1, "values": ["usuario", "admin"]},
            {"name": "expira", "type": "number", "required": True},
            {"name": "creado", "type": "text", "required": False},
        ],
        [
            f"CREATE UNIQUE INDEX idx_{COLECCION_SESIONES}_token ON {COLECCION_SESIONES} (token)",
            f"CREATE INDEX idx_{COLECCION_SESIONES}_usuario ON {COLECCION_SESIONES} (usuario)",
        ],
    )


def asegurar_coleccion_fotos() -> None:
    """Fotos tomadas en el reconocimiento o la captura."""
    _crear_coleccion(
        "fotos",
        [
            {"name": "usuario", "type": "text", "required": False},
            {"name": "origen", "type": "select", "required": True,
             "maxSelect": 1, "values": ["reconocimiento", "captura"]},
            {"name": "reconocido", "type": "bool"},
            {"name": "confianza", "type": "number"},   # en realidad es la distancia de DeepFace
            {"name": "imagen", "type": "file", "required": True, "maxSelect": 1,
             "maxSize": 5242880, "mimeTypes": ["image/jpeg", "image/png"]},
            {"name": "creado", "type": "autodate", "onCreate": True, "onUpdate": False},
        ],
        ["CREATE INDEX idx_fotos_usuario ON fotos (usuario)"],
    )


def asegurar_coleccion_tags() -> None:
    """Tags NFC/RFID de llaves o tarjetas (llave_id = aulas.id, puede quedar vacío)."""
    _crear_coleccion(
        "tags",
        [
            {"name": "uid", "type": "text", "required": True},
            {"name": "nombre", "type": "text", "required": True},
            {"name": "numero_aula", "type": "text", "required": False},
            {"name": "llave_id", "type": "text", "required": False},
            {"name": "tipo", "type": "select", "required": True,
             "maxSelect": 1, "values": ["llave", "tarjeta"]},
            {"name": "notas", "type": "text", "required": False},
            {"name": "activo", "type": "bool"},
            {"name": "creado", "type": "autodate", "onCreate": True, "onUpdate": False},
        ],
        [
            "CREATE UNIQUE INDEX idx_tags_uid ON tags (uid)",
            "CREATE INDEX idx_tags_llave ON tags (llave_id)",
            "CREATE INDEX idx_tags_numero ON tags (numero_aula)",
        ],
    )
    # Bases creadas con la versión anterior: agregar el número de aula sin perder datos.
    _agregar_campo("tags", {"name": "numero_aula", "type": "text", "required": False})


def _agregar_campo(coleccion: str, campo: dict) -> None:
    """Agrega un campo a una colección existente si todavía no lo tiene."""
    r = pb("GET", f"/api/collections/{coleccion}")
    if r.status_code != 200:
        return
    campos = r.json().get("fields", [])
    if any(f.get("name") == campo["name"] for f in campos):
        return
    campos.append(campo)
    r = pb("PATCH", f"/api/collections/{coleccion}", json={"fields": campos})
    if r.status_code == 200:
        log("POCKETBASE", f"Campo '{campo['name']}' agregado a '{coleccion}'")
    else:
        log("POCKETBASE", f"No pude agregar '{campo['name']}' a '{coleccion}': "
                          f"{r.status_code} {r.text[:LONGITUD_TEXTO_COLECCION]}")


def limpiar_sesiones_expiradas() -> None:
    """Elimina sesiones expiradas de PocketBase (se ejecuta al arrancar)."""
    ahora = int(time.time())
    r = pb("GET", f"/api/collections/{COLECCION_SESIONES}/records",
           params={"filter": f"expira < {ahora}", "perPage": 500})
    if r.status_code != 200:
        return
    items = r.json().get("items", [])
    for item in items:
        pb("DELETE", f"/api/collections/{COLECCION_SESIONES}/records/{item['id']}")
    if items:
        log("POCKETBASE", f"Limpiadas {len(items)} sesiones expiradas")


def estado_de(usuario: str) -> str | None:
    """Devuelve el estado aprobado, pendiente o rechazado usando una caché corta."""
    c = _CACHE_ESTADO.get(usuario)
    if c and c[1] > time.time():
        return c[0]
    rec = pb_usuario(usuario)
    est = rec["estado"] if rec else None
    _CACHE_ESTADO[usuario] = (est, time.time() + CACHE_ESTADO_S)
    return est


# ============================================================
#  Fotos
# ============================================================
def guardar_foto(jpeg: bytes, origen: str, usuario: str | None = None,
                 reconocido: bool = False, confianza: float | None = None) -> None:
    """Sube una foto a PocketBase. Nunca lanza error: no debe frenar el reconocimiento."""
    # Los rechazos se limitan a 1 cada 5 s para no llenar la base (el ESP32 manda ~1 foto/s).
    if not reconocido:
        if time.time() - _ULTIMA_FOTO_RECHAZO["ts"] < 5:
            return
        _ULTIMA_FOTO_RECHAZO["ts"] = time.time()
    try:
        r = pb("POST", "/api/collections/fotos/records",
               data={"usuario": usuario or "", "origen": origen,
                     "reconocido": "true" if reconocido else "false",
                     "confianza": confianza if confianza is not None else 0},
               files={"imagen": (f"{int(time.time())}.jpg", jpeg, "image/jpeg")})
        if r.status_code not in (200, 201):
            log("POCKETBASE", f"No pude guardar foto: {r.status_code} {r.text[:LONGITUD_TEXTO_COLECCION]}")
    except HTTPException:
        pass


# ============================================================
#  Tags
# ============================================================
def listar_tags() -> list:
    r = pb("GET", "/api/collections/tags/records", params={"perPage": 500, "sort": "llave_id,nombre"})
    return r.json().get("items", []) if r.status_code == 200 else []


def tags_de_llave(llave_id: str) -> list:
    if not re.fullmatch(r"\d{1,9}", llave_id or ""):
        return []
    r = pb("GET", "/api/collections/tags/records",
           params={"filter": f'llave_id="{llave_id}"', "perPage": 100})
    return r.json().get("items", []) if r.status_code == 200 else []


def tag_por_uid(uid: str, solo_activos: bool = True) -> dict | None:
    uid = normalizar_uid(uid)
    if not re.fullmatch(UID_RE, uid):
        return None
    filtro = f'uid="{uid}" && activo=true' if solo_activos else f'uid="{uid}"'
    r = pb("GET", "/api/collections/tags/records", params={"filter": filtro, "perPage": 1})
    items = r.json().get("items", []) if r.status_code == 200 else []
    return items[0] if items else None


def crear_tag(uid: str, nombre: str, llave_id: str = "", tipo: str = "llave",
              notas: str = "") -> requests.Response:
    return pb("POST", "/api/collections/tags/records",
              json={"uid": normalizar_uid(uid), "nombre": nombre, "llave_id": llave_id,
                    "tipo": tipo, "notas": notas, "activo": True})


def editar_tag(tag_id: str, **campos) -> requests.Response:
    permitidos = {k: v for k, v in campos.items()
                  if k in ("uid", "nombre", "llave_id", "tipo", "notas", "activo")}
    if "uid" in permitidos:
        permitidos["uid"] = normalizar_uid(permitidos["uid"])
    return pb("PATCH", f"/api/collections/tags/records/{tag_id}", json=permitidos)


def borrar_tag(tag_id: str) -> requests.Response:
    return pb("DELETE", f"/api/collections/tags/records/{tag_id}")


def uids_activos(aula_id: int, legacy: str = "") -> list[str]:
    """UIDs válidos de un aula: tags activos de PocketBase + el rfid viejo si existe."""
    try:
        uids = [normalizar_uid(t["uid"]) for t in tags_de_llave(str(aula_id)) if t.get("activo")]
    except Exception:
        uids = []
    legacy = normalizar_uid(legacy)
    if legacy and legacy not in uids:
        uids.append(legacy)
    return uids