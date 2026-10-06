from fastapi import FastAPI, Request, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse, RedirectResponse
from pydantic import BaseModel
from deepface import DeepFace
from contextlib import closing
import hashlib
import hmac
import numpy as np
import os
import re
import requests
import secrets
import sqlite3
import threading
import time
import uuid
import uvicorn
from datetime import datetime

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIRECTORIO_CARAS = os.path.join(BASE_DIR, "personas_autorizadas")
DIRECTORIO_PENDIENTES = os.path.join(BASE_DIR, "fotos_pendientes")
DB_PATH = os.path.join(BASE_DIR, "llaves.db")
EXTENSIONES = (".jpg", ".jpeg", ".png")

# ---------------- Reconocimiento facial ----------------
MODELO = "VGG-Face"
DETECTOR = "yunet"
UMBRAL = 0.40
EXIGIR_ROSTRO = True
VENTANA_RETIRO_S = 60

# ---------------- Administración ----------------
# Contraseña del panel de administración. Definila antes de arrancar:
#   PowerShell:  $env:ADMIN_CLAVE="tu-clave-larga"
CLAVE_ADMIN = os.environ.get("ADMIN_CLAVE", "cambiame-admin")
ADMIN_SOLO_LOCAL = False    # True = el panel /admin solo se abre desde esta misma PC
ADMIN_SESION_S = 1800
MAX_PENDIENTES = 20         # tope de solicitudes sin resolver (evita spam)

# ---------------- PocketBase (guarda los usuarios) ----------------
# El servidor entra como superusuario de PocketBase. Definí estas variables:
#   PB_EMAIL y PB_PASSWORD = el superusuario que creaste en PocketBase
PB_URL = os.environ.get("PB_URL", "http://127.0.0.1:8090")
PB_EMAIL = os.environ.get("PB_EMAIL", "")
PB_PASSWORD = os.environ.get("PB_PASSWORD", "")
COLECCION = "personal"

# ---------------- Usuarios ----------------
MAX_FOTOS_POR_USUARIO = 15
REGISTRO_TIMEOUT_S = 120
SESION_S = 1800
CODIGO_VALIDO_S = 30
MAX_INTENTOS = 5
BLOQUEO_S = 60
CASILLERO_DEFECTO = "C01"
RESERVADOS = {"admin", "administrador", "root"}

# ---------------- Estado en memoria ----------------
MODO = {"valor": "reconocimiento", "hasta": 0.0}
ULTIMA_FOTO = {"bytes": None, "ts": 0.0}
ULTIMO_RESULTADO = {"texto": "Sin datos todavia"}
ULTIMA_AUTORIZACION: dict[str, tuple[str, float]] = {}
ACCESO_CODIGO: dict[str, tuple[str, float]] = {}
SESIONES: dict[str, tuple[str, float]] = {}
SESIONES_ADMIN: dict[str, float] = {}
INTENTOS: dict[str, list] = {}          # usuarios y "admin:<ip>"
AVISOS: dict[str, list] = {}

BASE_EMBEDDINGS: dict[str, dict] = {}
LOCK_BASE = threading.Lock()
LOCK_DEEPFACE = threading.Lock()
LOCK_NOMBRES = threading.Lock()


def obtener_hora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================ BASE DE DATOS ============================
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with closing(db()) as con, con:
        con.execute("""CREATE TABLE IF NOT EXISTS llaves (
            casillero_id TEXT PRIMARY KEY, estado TEXT NOT NULL DEFAULT 'Disponible',
            persona TEXT, actualizado TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS historial (
            id INTEGER PRIMARY KEY AUTOINCREMENT, casillero_id TEXT NOT NULL,
            evento TEXT NOT NULL, persona TEXT, fecha TEXT NOT NULL)""")
        # Los usuarios ya no se guardan acá: viven en PocketBase (ver más abajo)


def registrar_estado(casillero_id: str, estado: str, evento: str, persona: str | None = None):
    ahora = obtener_hora()
    with closing(db()) as con, con:
        con.execute("""INSERT INTO llaves (casillero_id, estado, persona, actualizado)
            VALUES (?, ?, ?, ?) ON CONFLICT(casillero_id) DO UPDATE SET
            estado = excluded.estado, persona = excluded.persona, actualizado = excluded.actualizado""",
                    (casillero_id, estado, persona, ahora))
        con.execute("INSERT INTO historial (casillero_id, evento, persona, fecha) VALUES (?, ?, ?, ?)",
                    (casillero_id, evento, persona, ahora))


# ============================ USUARIOS Y SESIONES ============================
def normalizar_usuario(u: str) -> str:
    return (u or "").strip().lower()


def usuario_valido(u: str) -> bool:
    return re.fullmatch(r"[a-z]{3,20}", u) is not None and u not in RESERVADOS


def hash_pin(pin: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 100_000)


# ---- Cliente de PocketBase ----
_PB = {"token": None}
LOCK_PB = threading.Lock()
_CACHE_ESTADO: dict[str, tuple[str | None, float]] = {}   # evita consultar PocketBase en cada request


def pb_login():
    r = requests.post(f"{PB_URL}/api/collections/_superusers/auth-with-password",
                      json={"identity": PB_EMAIL, "password": PB_PASSWORD}, timeout=5)
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
                                 timeout=5, **kw)
            if r.status_code in (401, 403) and intento == 1:
                _PB["token"] = None
                continue
            return r
    except requests.RequestException as e:
        print(f"[{obtener_hora()}] [POCKETBASE] No disponible o credenciales inválidas: {str(e)[:100]}")
        raise HTTPException(status_code=503, detail="La base de datos de usuarios no está disponible.")


def pb_usuario(usuario: str) -> dict | None:
    if not re.fullmatch(r"[a-z]{3,20}", usuario or ""):   # también evita inyección en el filtro
        return None
    r = pb("GET", f"/api/collections/{COLECCION}/records",
           params={"filter": f'usuario="{usuario}"', "perPage": 1})
    if r.status_code != 200:
        raise HTTPException(status_code=503, detail="La base de datos de usuarios no está disponible.")
    items = r.json().get("items", [])
    return items[0] if items else None


def asegurar_coleccion():
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
        print(f"[{obtener_hora()}] [POCKETBASE] Colección '{COLECCION}' creada")
    else:
        print(f"[{obtener_hora()}] [POCKETBASE] No pude crear la colección: {r.status_code} {r.text[:200]}")


def estado_de(usuario: str) -> str | None:
    c = _CACHE_ESTADO.get(usuario)
    if c and c[1] > time.time():
        return c[0]
    rec = pb_usuario(usuario)
    est = rec["estado"] if rec else None
    _CACHE_ESTADO[usuario] = (est, time.time() + 2)
    return est


def controlar_bloqueo(clave: str):
    est = INTENTOS.get(clave)
    if est and est[1] > time.time():
        raise HTTPException(status_code=429, detail="Demasiados intentos. Espera un minuto.")


def registrar_fallo(clave: str):
    est = INTENTOS.get(clave)
    fallos = (est[0] if est else 0) + 1
    if fallos >= MAX_INTENTOS:
        INTENTOS[clave] = [0, time.time() + BLOQUEO_S]
        print(f"[{obtener_hora()}] [SEGURIDAD] '{clave}' bloqueado {BLOQUEO_S}s por intentos fallidos")
    else:
        INTENTOS[clave] = [fallos, 0]


def verificar_pin(usuario: str, pin: str) -> bool:
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


def usuario_de_sesion(request: Request) -> str | None:
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


# ---- Administrador ----
def es_local(request: Request) -> bool:
    return (request.client.host if request.client else "") in ("127.0.0.1", "::1", "localhost")


def autenticar_admin(request: Request):
    if ADMIN_SOLO_LOCAL and not es_local(request):
        raise HTTPException(status_code=404, detail="No encontrado")
    token = request.headers.get("x-admin", "")
    exp = SESIONES_ADMIN.get(token)
    if not exp or exp < time.time():
        SESIONES_ADMIN.pop(token, None)
        raise HTTPException(status_code=401, detail="Sesión de administrador no válida.")
    SESIONES_ADMIN[token] = time.time() + ADMIN_SESION_S


def modo_actual() -> str:
    if MODO["valor"] == "registro" and time.time() > MODO["hasta"]:
        MODO["valor"] = "reconocimiento"
        print(f"[{obtener_hora()}] [MODO] Reconocimiento (el modo registro venció)")
    return MODO["valor"]


# ============================ RECONOCIMIENTO ============================
def nombre_persona(archivo: str) -> str:
    return re.sub(r"\d+", "", archivo.split(".")[0]).capitalize()


def calcular_embedding(ruta: str, exigir_rostro: bool) -> np.ndarray:
    with LOCK_DEEPFACE:
        res = DeepFace.represent(img_path=ruta, model_name=MODELO, detector_backend=DETECTOR,
                                 enforce_detection=exigir_rostro)

    def area(r):
        fa = r.get("facial_area", {})
        return fa.get("w", 0) * fa.get("h", 0)

    return np.array(max(res, key=area)["embedding"], dtype=np.float32)


def distancia_coseno(a: np.ndarray, b: np.ndarray) -> float:
    return float(1.0 - np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def sincronizar_base():
    with LOCK_BASE:
        os.makedirs(DIRECTORIO_CARAS, exist_ok=True)
        archivos = {f for f in os.listdir(DIRECTORIO_CARAS) if f.lower().endswith(EXTENSIONES)}
        for f in list(BASE_EMBEDDINGS):
            if f not in archivos:
                del BASE_EMBEDDINGS[f]
                print(f"[{obtener_hora()}] [BASE] Foto eliminada: {f}")
        for f in sorted(archivos):
            ruta = os.path.join(DIRECTORIO_CARAS, f)
            mtime = os.path.getmtime(ruta)
            if f in BASE_EMBEDDINGS and BASE_EMBEDDINGS[f]["mtime"] == mtime:
                continue
            try:
                emb = calcular_embedding(ruta, exigir_rostro=True)
                BASE_EMBEDDINGS[f] = {"mtime": mtime, "emb": emb, "persona": nombre_persona(f)}
                print(f"[{obtener_hora()}] [BASE] Cargada: {f} -> {nombre_persona(f)}")
            except Exception as e:
                BASE_EMBEDDINGS.pop(f, None)
                print(f"[{obtener_hora()}] [ADVERTENCIA] {f} ignorada: {str(e)[:80]}")


def comparar_rostro(ruta_temp: str) -> dict:
    sincronizar_base()
    if not BASE_EMBEDDINGS:
        return {"vacia": True}
    try:
        emb = calcular_embedding(ruta_temp, exigir_rostro=EXIGIR_ROSTRO)
    except ValueError:
        return {"rostro": False, "autorizado": False, "persona": "Desconocido", "distancia": None}

    mejor_dist, mejor_persona = 999.0, "Desconocido"
    with LOCK_BASE:
        for datos in BASE_EMBEDDINGS.values():
            d = distancia_coseno(emb, datos["emb"])
            if d < mejor_dist:
                mejor_dist, mejor_persona = d, datos["persona"]

    autorizado = mejor_dist <= UMBRAL
    return {"rostro": True, "autorizado": autorizado,
            "persona": mejor_persona if autorizado else "Desconocido",
            "distancia": mejor_dist, "mas_parecido": mejor_persona}


# ============================ FOTOS DE REFERENCIA POR USUARIO ============================
def _archivos_en(carpeta: str, usuario: str) -> list[str]:
    if not os.path.exists(carpeta):
        return []
    patron = re.compile(rf"{usuario}\d+\.(jpg|jpeg|png)", re.IGNORECASE)
    return sorted(f for f in os.listdir(carpeta) if patron.fullmatch(f))


def archivos_de(usuario: str) -> list[str]:
    return _archivos_en(DIRECTORIO_CARAS, usuario)


def pendientes_de(usuario: str) -> list[str]:
    return _archivos_en(DIRECTORIO_PENDIENTES, usuario)


def ruta_foto_de(usuario: str, archivo: str) -> str:
    archivo = os.path.basename(archivo)
    if archivo in archivos_de(usuario):
        return os.path.join(DIRECTORIO_CARAS, archivo)
    if archivo in pendientes_de(usuario):
        return os.path.join(DIRECTORIO_PENDIENTES, archivo)
    raise HTTPException(status_code=404, detail="Foto no encontrada")


def guardar_pendiente(usuario: str, datos: bytes) -> dict:
    with LOCK_NOMBRES:
        os.makedirs(DIRECTORIO_PENDIENTES, exist_ok=True)
        aprobadas, pendientes = archivos_de(usuario), pendientes_de(usuario)
        if len(aprobadas) + len(pendientes) >= MAX_FOTOS_POR_USUARIO:
            return {"ok": False, "mensaje": f"Ya tienes {MAX_FOTOS_POR_USUARIO} fotos. Borra alguna para agregar otra."}
        usados = []
        for f in aprobadas + pendientes:
            m = re.fullmatch(rf"{usuario}(\d+)\.\w+", f, re.IGNORECASE)
            if m:
                usados.append(int(m.group(1)))
        archivo = f"{usuario}{max(usados, default=0) + 1}.jpg"
        ruta = os.path.join(DIRECTORIO_PENDIENTES, archivo)
        with open(ruta + ".part", "wb") as f:
            f.write(datos)
        os.replace(ruta + ".part", ruta)
    print(f"[{obtener_hora()}] [REGISTRO] {usuario}: foto {archivo} guardada en fotos_pendientes")
    return {"ok": True, "archivo": archivo, "estado": "pendiente"}


def rechazar_pendiente(usuario: str, archivo: str, ruta: str, motivo: str):
    try:
        os.remove(ruta)
    except OSError:
        pass
    AVISOS.setdefault(usuario, []).append(f"{archivo}: {motivo}")
    print(f"[{obtener_hora()}] [REGISTRO] {archivo} rechazada: {motivo}")


def procesar_pendiente(archivo: str):
    m = re.fullmatch(r"([a-z]+)\d+\.jpg", archivo)
    ruta = os.path.join(DIRECTORIO_PENDIENTES, archivo)
    if not m or not os.path.isfile(ruta):
        return
    usuario = m.group(1)
    persona = usuario.capitalize()
    destino = os.path.join(DIRECTORIO_CARAS, archivo)

    try:
        emb = calcular_embedding(ruta, exigir_rostro=True)
    except Exception:
        rechazar_pendiente(usuario, archivo, ruta,
                           "no se detectó un rostro. Acércate, mira a la cámara y vuelve a intentar.")
        return

    otro = None
    with LOCK_BASE:
        for d in BASE_EMBEDDINGS.values():
            if d["persona"] != persona and distancia_coseno(emb, d["emb"]) <= UMBRAL:
                otro = d["persona"]
                break
        if otro is None:
            os.makedirs(DIRECTORIO_CARAS, exist_ok=True)
            try:
                os.replace(ruta, destino)
            except FileNotFoundError:
                return
            BASE_EMBEDDINGS[archivo] = {"mtime": os.path.getmtime(destino), "emb": emb, "persona": persona}

    if otro:
        rechazar_pendiente(usuario, archivo, ruta, f"esa cara ya está registrada como {otro}.")
    else:
        print(f"[{obtener_hora()}] [REGISTRO] {archivo} aprobada y movida a personas_autorizadas")


def worker_pendientes():
    while True:
        try:
            pendientes = sorted(f for f in os.listdir(DIRECTORIO_PENDIENTES) if f.lower().endswith(".jpg"))
        except Exception:
            pendientes = []
        if not pendientes:
            time.sleep(1)
            continue
        for f in pendientes:
            try:
                procesar_pendiente(f)
            except Exception as e:
                print(f"[{obtener_hora()}] [ERROR] Verificando {f}: {e}")
                try:
                    os.remove(os.path.join(DIRECTORIO_PENDIENTES, f))
                except OSError:
                    pass


# ============================ STARTUP ============================
@app.on_event("startup")
async def startup_event():
    init_db()
    try:
        await run_in_threadpool(asegurar_coleccion)
    except HTTPException:
        print(f"[{obtener_hora()}] [POCKETBASE] ¡No pude conectar! Revisá PB_URL, PB_EMAIL y PB_PASSWORD.")
    os.makedirs(DIRECTORIO_CARAS, exist_ok=True)
    os.makedirs(DIRECTORIO_PENDIENTES, exist_ok=True)
    for f in os.listdir(DIRECTORIO_PENDIENTES):
        if f.endswith(".part"):
            os.remove(os.path.join(DIRECTORIO_PENDIENTES, f))

    print("\n" + "=" * 60)
    print(f"[{obtener_hora()}] [SISTEMA] Iniciando servidor | modelo={MODELO} detector={DETECTOR} umbral={UMBRAL}")
    if CLAVE_ADMIN == "cambiame-admin":
        print(f"[{obtener_hora()}] [SEGURIDAD] ¡Estás usando la clave de admin por defecto! Definí ADMIN_CLAVE.")
    await run_in_threadpool(sincronizar_base)
    personas = sorted({d["persona"] for d in BASE_EMBEDDINGS.values()})
    print(f"[{obtener_hora()}] [SISTEMA] Listo: {len(BASE_EMBEDDINGS)} fotos válidas, personas: {personas}")
    print(f"[{obtener_hora()}] [SISTEMA] Usuarios:       http://IP_DE_ESTA_PC:8000/registro")
    print(f"[{obtener_hora()}] [SISTEMA] Administración: http://IP_DE_ESTA_PC:8000/admin")
    print("=" * 60 + "\n")
    threading.Thread(target=worker_pendientes, daemon=True).start()


# ============================ ENDPOINT DE LA PLACA ============================
@app.post("/reconocimiento")
async def reconocer_rostro(request: Request):
    casillero_id = request.headers.get("x-casillero-id", CASILLERO_DEFECTO)
    cuerpo = await request.body()
    if len(cuerpo) < 1000:
        print(f"[{obtener_hora()}] [PETICIÓN] {casillero_id}: imagen de {len(cuerpo)} bytes (descartada)")
        return {"status": "error", "mensaje": "Imagen muy pequeña o corrupta"}

    ULTIMA_FOTO["bytes"] = cuerpo
    ULTIMA_FOTO["ts"] = time.time()

    if modo_actual() == "registro":
        return {"status": "success", "modo": "registro", "autorizado": False, "mensaje": "Modo registro"}

    acc = ACCESO_CODIGO.get(casillero_id)
    if acc and time.time() - acc[1] <= CODIGO_VALIDO_S:
        ACCESO_CODIGO.pop(casillero_id, None)
        persona = acc[0].capitalize()
        ULTIMA_AUTORIZACION[casillero_id] = (persona, time.time())
        ULTIMO_RESULTADO["texto"] = f"ACCESO PERMITIDO (código): {persona} ({datetime.now().strftime('%H:%M:%S')})"
        print(f"[{obtener_hora()}] [ACCESO PERMITIDO] {persona} (por código personal)")
        print("-" * 60)
        return {"status": "success", "modo": "reconocimiento", "autorizado": True,
                "persona": persona, "metodo": "codigo", "mensaje": f"Bienvenido/a, {persona}."}

    ruta_temp = os.path.join(BASE_DIR, f"temp_{uuid.uuid4().hex}.jpg")
    try:
        print(f"[{obtener_hora()}] [PETICIÓN] {casillero_id}: imagen de {len(cuerpo)} bytes")
        with open(ruta_temp, "wb") as f:
            f.write(cuerpo)

        res = await run_in_threadpool(comparar_rostro, ruta_temp)

        if res.get("vacia"):
            ULTIMO_RESULTADO["texto"] = "No hay fotos de referencia"
            return {"status": "error", "modo": "reconocimiento",
                    "mensaje": "No hay fotos de referencia válidas en el sistema."}

        if res["autorizado"]:
            ULTIMA_AUTORIZACION[casillero_id] = (res["persona"], time.time())
            ULTIMO_RESULTADO["texto"] = f"ACCESO PERMITIDO: {res['persona']} ({datetime.now().strftime('%H:%M:%S')})"
            print(f"[{obtener_hora()}] [ACCESO PERMITIDO] {res['persona']} (dist: {res['distancia']:.3f})")
            print("-" * 60)
            return {"status": "success", "modo": "reconocimiento", "autorizado": True,
                    "persona": res["persona"], "metodo": "rostro",
                    "mensaje": f"Bienvenido/a, {res['persona']}.", "distancia": res["distancia"]}

        if res["rostro"]:
            print(f"[{obtener_hora()}] [ACCESO DENEGADO] Persona no registrada "
                  f"(más parecido: {res['mas_parecido']}, dist: {res['distancia']:.3f}, umbral: {UMBRAL})")
            motivo = "Persona no registrada."
        else:
            print(f"[{obtener_hora()}] [SIN ROSTRO] No se detectó ninguna cara en la imagen")
            motivo = "No se detectó ningún rostro."
        ULTIMO_RESULTADO["texto"] = f"Denegado: {motivo} ({datetime.now().strftime('%H:%M:%S')})"
        print("-" * 60)
        return {"status": "success", "modo": "reconocimiento", "autorizado": False,
                "persona": "Desconocido", "mensaje": motivo}
    except Exception as e:
        print(f"[{obtener_hora()}] [ERROR GENERAL] {e}")
        print("-" * 60)
        return {"status": "error", "mensaje": str(e)}
    finally:
        if os.path.exists(ruta_temp):
            os.remove(ruta_temp)


# ============================ USUARIOS: SOLICITUD, LOGIN, CÓDIGO ============================
class SolicitudAcceso(BaseModel):
    usuario: str
    pin: str


class LoginDatos(BaseModel):
    usuario: str
    pin: str


class AccesoCodigo(BaseModel):
    usuario: str
    pin: str
    casillero_id: str = CASILLERO_DEFECTO


@app.post("/solicitar_acceso")
async def solicitar_acceso(datos: SolicitudAcceso):
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

    print(f"[{obtener_hora()}] [SOLICITUD] Nueva solicitud de acceso: {usuario}")
    return {"ok": True, "usuario": usuario}


@app.post("/login")
async def login(datos: LoginDatos):
    usuario = normalizar_usuario(datos.usuario)
    if not verificar_pin(usuario, datos.pin):
        raise HTTPException(status_code=401, detail="Usuario o código incorrecto")
    ahora = time.time()
    for t in [t for t, (_, exp) in SESIONES.items() if exp < ahora]:
        SESIONES.pop(t, None)
    token = secrets.token_hex(16)
    SESIONES[token] = (usuario, ahora + SESION_S)
    return {"token": token, "usuario": usuario, "estado": estado_de(usuario)}


@app.post("/acceso_codigo")
async def acceso_codigo(datos: AccesoCodigo):
    usuario = normalizar_usuario(datos.usuario)
    if not verificar_pin(usuario, datos.pin):
        raise HTTPException(status_code=401, detail="Usuario o código incorrecto")
    if estado_de(usuario) != "aprobado":
        raise HTTPException(status_code=403, detail="Tu cuenta todavía no fue aprobada por el administrador.")
    ACCESO_CODIGO[datos.casillero_id] = (usuario, time.time())
    print(f"[{obtener_hora()}] [CÓDIGO] {usuario} autorizó el casillero {datos.casillero_id} con su código")
    return {"ok": True,
            "mensaje": f"Código correcto. Párate frente a la cámara: se abrirá en unos segundos ({CODIGO_VALIDO_S} s de validez)."}


# ============================ ESTILO COMPARTIDO ============================
CSS = r"""
:root{--bg:#0f1115;--card:#171a21;--line:#262b36;--txt:#e8eaf0;--mut:#8b93a5;--acc:#4f8cff;--ok:#2fb36b;--bad:#e5484d;--warn:#f5a524}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:720px;margin:0 auto;padding:28px 16px 48px}
h1{font-size:1.6rem;margin:0 0 4px;letter-spacing:-.02em}
h2{font-size:1.05rem;margin:0 0 12px}
.sub{color:var(--mut);margin:0 0 24px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;margin-bottom:16px}
input{width:100%;padding:11px 12px;margin:0 0 10px;background:var(--bg);border:1px solid var(--line);border-radius:10px;color:var(--txt);font:inherit}
input:focus{outline:2px solid var(--acc);border-color:transparent}
button{padding:10px 16px;border:0;border-radius:10px;background:var(--acc);color:#fff;font:inherit;font-weight:600;cursor:pointer}
button:hover{filter:brightness(1.1)}
button.ok{background:var(--ok)} button.rojo{background:var(--bad)}
button.ghost{background:transparent;border:1px solid var(--line);color:var(--txt)}
button.chico{padding:6px 12px;font-size:.9rem}
.aviso{display:none;padding:12px 14px;border-radius:10px;margin-bottom:16px;border:1px solid}
.aviso.ok{background:#12301f;border-color:#1f6b43}
.aviso.err{background:#3a1618;border-color:#7a2a2e}
.aviso.info{background:#14243d;border-color:#26467a}
.badge{display:inline-block;padding:2px 10px;border-radius:99px;font-size:.78rem;font-weight:600}
.b-pendiente{background:#3d2e0e;color:var(--warn)} .b-aprobado{background:#12301f;color:var(--ok)} .b-rechazado{background:#3a1618;color:var(--bad)}
.fila{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap;padding:12px 0;border-top:1px solid var(--line)}
.fila:first-of-type{border-top:0}
.acciones{display:flex;gap:8px}
.mut{color:var(--mut);font-size:.9rem}
.live{width:100%;min-height:180px;border-radius:10px;background:#000;display:block;margin:12px 0}
.grid{display:flex;flex-wrap:wrap;gap:10px}
.item{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:8px;width:136px;font-size:.82rem}
.item img{width:100%;height:90px;object-fit:cover;border-radius:6px;display:block;margin-bottom:6px}
.pend{color:var(--warn)}
.barra{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}
"""

# ============================ PÁGINA DE USUARIOS ============================
PAGINA_USUARIO = r"""<!DOCTYPE html><html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Llavero ETEC</title><style>__CSS__</style></head><body><main>
<h1>Llavero Inteligente</h1>
<p class="sub">Acceso al casillero de llaves con reconocimiento facial.</p>
<div id="msg" class="aviso"></div>

<div id="c_acceso">
  <div class="card">
    <h2>Solicitar acceso</h2>
    <p class="mut">Tu solicitud le llega al administrador. Cuando la apruebe vas a poder registrar tu cara.</p>
    <input id="r_user" placeholder="Usuario (solo letras)" autocapitalize="none">
    <input id="r_pin" type="password" inputmode="numeric" placeholder="Código personal (4 a 8 números)">
    <input id="r_pin2" type="password" inputmode="numeric" placeholder="Repetir código personal">
    <button onclick="solicitar()">Enviar solicitud</button>
  </div>
  <div class="card">
    <h2>Ya tengo usuario</h2>
    <input id="l_user" placeholder="Usuario" autocapitalize="none">
    <input id="l_pin" type="password" inputmode="numeric" placeholder="Código personal">
    <button onclick="entrar()">Entrar</button>
  </div>
  <div class="card">
    <h2>Si falla el reconocimiento facial</h2>
    <input id="a_user" placeholder="Usuario" autocapitalize="none">
    <input id="a_pin" type="password" inputmode="numeric" placeholder="Código personal">
    <button class="ghost" onclick="abrirConCodigo()">Abrir con código</button>
  </div>
</div>

<div id="c_panel" style="display:none">
  <div class="barra"><div>Hola, <b id="u"></b></div><button class="ghost chico" onclick="salir()">Salir</button></div>

  <div id="b_pend" class="card" style="display:none">
    <h2>Solicitud en revisión <span class="badge b-pendiente">Pendiente</span></h2>
    <p class="mut">Esperando que el administrador la apruebe. Esta pantalla se actualiza sola y te va a avisar.</p>
  </div>
  <div id="b_rech" class="card" style="display:none">
    <h2>Solicitud rechazada <span class="badge b-rechazado">Rechazada</span></h2>
    <p class="mut">El administrador no aprobó tu acceso. Hablá con él si creés que es un error.</p>
  </div>

  <div id="c_fotos" style="display:none">
    <div id="b_ok" class="aviso ok" style="display:none"><b>¡Solicitud aprobada!</b> Iniciá la captura y guardá varias fotos de tu cara.</div>
    <div class="card">
      <h2>Registrar mi cara</h2>
      <div class="mut">Modo: <b id="modo">...</b> · <span id="edad"></span></div>
      <div class="mut">Último resultado: <b id="res">...</b></div>
      <button id="btnCap" onclick="toggleCaptura()" style="margin-top:12px">Iniciar captura</button>
      <img id="v" class="live" alt="Vista de la cámara">
      <p class="mut">Mirá de frente, con buena luz, y guardá varias fotos cambiando un poco el ángulo.</p>
      <button class="ok" onclick="guardar()">Guardar foto</button>
      <p id="m" class="mut"></p>
    </div>
    <div class="card"><h2>Mis fotos</h2><div id="lista" class="grid"></div></div>
  </div>
</div>

<script>
const q = id => document.getElementById(id);
let token = null, estadoU = null, capturando = false, urlActual = null, listaTimer = null;
const miniaturas = {};

function aviso(t, tipo){
  const m = q('msg');
  m.textContent = t || '';
  m.className = 'aviso ' + (tipo || 'ok');
  m.style.display = t ? 'block' : 'none';
}

async function api(url, metodo, cuerpo){
  const h = {};
  if (token) h['x-token'] = token;
  const o = {method: metodo || 'GET', headers: h};
  if (cuerpo){ h['Content-Type'] = 'application/json'; o.body = JSON.stringify(cuerpo); }
  const r = await fetch(url, o);
  let d = {};
  try { d = await r.json(); } catch (e) {}
  if (r.status === 401 && token) limpiarSesion(true);
  if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : (d.mensaje || 'Error HTTP ' + r.status));
  return d;
}

function notificar(titulo, texto){
  aviso(titulo + ' ' + texto, 'ok');
  document.title = '🔔 ' + titulo;
  try { if ('Notification' in window && Notification.permission === 'granted') new Notification(titulo, {body: texto}); } catch (e) {}
}

async function solicitar(){
  const pin = q('r_pin').value;
  if (pin !== q('r_pin2').value){ aviso('Los códigos personales no coinciden', 'err'); return; }
  try {
    const d = await api('/solicitar_acceso', 'POST', {usuario: q('r_user').value, pin: pin});
    aviso('Solicitud enviada. Entrá con "' + d.usuario + '" para ver cuándo la aprueban.', 'ok');
    q('l_user').value = d.usuario;
    q('r_pin').value = ''; q('r_pin2').value = '';
  } catch (e) { aviso(e.message, 'err'); }
}

async function entrar(){
  try {
    const d = await api('/login', 'POST', {usuario: q('l_user').value, pin: q('l_pin').value});
    token = d.token;
    q('u').textContent = d.usuario;
    q('c_acceso').style.display = 'none';
    q('c_panel').style.display = 'block';
    q('l_pin').value = '';
    aviso('');
    try { if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission(); } catch (e) {}
    aplicarEstado(d.estado);
    estado();
  } catch (e) { aviso(e.message, 'err'); }
}

function aplicarEstado(e){
  const previo = estadoU;
  estadoU = e;
  q('b_pend').style.display = e === 'pendiente' ? 'block' : 'none';
  q('b_rech').style.display = e === 'rechazado' ? 'block' : 'none';
  q('c_fotos').style.display = e === 'aprobado' ? 'block' : 'none';
  if (e === 'aprobado' && previo !== 'aprobado'){
    if (previo === 'pendiente') notificar('¡Solicitud aprobada!', 'Ya podés registrar tu cara.');
    cargarLista();
  }
}

function limpiarSesion(expirada){
  capturando = false; token = null; estadoU = null;
  clearTimeout(listaTimer);
  for (const k in miniaturas) delete miniaturas[k];
  q('btnCap').textContent = 'Iniciar captura';
  q('c_panel').style.display = 'none';
  q('c_acceso').style.display = 'block';
  document.title = 'Llavero ETEC';
  if (expirada) aviso('Tu sesión venció. Volvé a entrar.', 'err');
}

async function salir(){
  if (capturando){ try { await api('/modo?m=reconocimiento', 'POST'); } catch (e) {} }
  limpiarSesion(false);
  aviso('');
}

async function estado(){
  if (!token) return;
  try {
    const e = await (await fetch('/estado', {headers: {'x-token': token}})).json();
    if (!e.estado_usuario){ limpiarSesion(true); return; }
    aplicarEstado(e.estado_usuario);
    q('modo').textContent = e.modo === 'registro' ? 'REGISTRO' : 'RECONOCIMIENTO';
    q('res').textContent = e.ultimo || '-';
    q('edad').textContent = e.edad_foto === null ? 'la placa todavía no envió fotos' : 'última foto hace ' + e.edad_foto + ' s';
  } catch (err) {}
  setTimeout(estado, 2000);
}

async function toggleCaptura(){
  try {
    await api('/modo?m=' + (capturando ? 'reconocimiento' : 'registro'), 'POST');
    capturando = !capturando;
    q('btnCap').textContent = capturando ? 'Terminar captura' : 'Iniciar captura';
    if (capturando) bucleFoto();
  } catch (e) { aviso(e.message, 'err'); }
}

setInterval(() => { if (capturando && token) api('/modo?m=registro', 'POST').catch(() => {}); }, 30000);

async function bucleFoto(){
  while (capturando && token){
    try {
      const r = await fetch('/ultima_foto?t=' + Date.now(), {headers: {'x-token': token}});
      if (r.status === 401){ limpiarSesion(true); return; }
      if (r.ok){
        const u = URL.createObjectURL(await r.blob());
        q('v').src = u;
        if (urlActual) URL.revokeObjectURL(urlActual);
        urlActual = u;
      }
    } catch (e) {}
    await new Promise(res => setTimeout(res, 400));
  }
}

async function guardar(){
  q('m').textContent = 'Guardando...';
  try {
    const d = await api('/guardar_foto', 'POST');
    q('m').textContent = 'Guardada: ' + d.archivo + ' (verificando la cara en segundo plano...)';
    cargarLista();
  } catch (e) { q('m').textContent = 'Error: ' + e.message; }
}

async function cargarLista(){
  if (!token) return;
  clearTimeout(listaTimer);
  try {
    const d = await api('/mis_fotos');
    if (d.avisos && d.avisos.length) q('m').textContent = 'Foto rechazada - ' + d.avisos.join(' | ');
    q('b_ok').style.display = d.fotos.length ? 'none' : 'block';
    const cont = q('lista');
    cont.innerHTML = '';
    if (!d.fotos.length){ cont.textContent = 'Todavía no tenés fotos.'; return; }
    let hayPend = false;
    for (const f of d.fotos){
      const div = document.createElement('div'); div.className = 'item';
      const img = document.createElement('img');
      const nm = document.createElement('div'); nm.textContent = f.archivo;
      if (f.estado === 'pendiente'){ hayPend = true; nm.textContent += ' (verificando...)'; nm.className = 'pend'; }
      const bt = document.createElement('button'); bt.className = 'rojo chico'; bt.textContent = 'Borrar';
      bt.onclick = () => borrar(f.archivo);
      div.append(img, nm, bt); cont.append(div);
      if (miniaturas[f.archivo]) img.src = miniaturas[f.archivo];
      else fetch('/foto/' + encodeURIComponent(f.archivo), {headers: {'x-token': token}})
        .then(r => r.blob()).then(b => { miniaturas[f.archivo] = URL.createObjectURL(b); img.src = miniaturas[f.archivo]; });
    }
    if (hayPend) listaTimer = setTimeout(cargarLista, 2000);
  } catch (e) {}
}

async function borrar(archivo){
  if (!confirm('¿Borrar ' + archivo + '?')) return;
  try {
    await api('/foto/' + encodeURIComponent(archivo), 'DELETE');
    delete miniaturas[archivo];
    cargarLista();
  } catch (e) { q('m').textContent = 'Error: ' + e.message; }
}

async function abrirConCodigo(){
  try {
    const d = await api('/acceso_codigo', 'POST', {usuario: q('a_user').value, pin: q('a_pin').value, casillero_id: 'C01'});
    aviso(d.mensaje, 'ok');
    q('a_pin').value = '';
  } catch (e) { aviso(e.message, 'err'); }
}
</script></main></body></html>
""".replace("__CSS__", CSS)


# ============================ PÁGINA DE ADMINISTRACIÓN ============================
PAGINA_ADMIN = r"""<!DOCTYPE html><html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Administración · Llavero ETEC</title><style>__CSS__</style></head><body><main>
<h1>Administración</h1>
<p class="sub">Control de personal autorizado del casillero.</p>
<div id="msg" class="aviso"></div>

<div id="c_login" class="card">
  <h2>Acceso restringido</h2>
  <input id="clave" type="password" placeholder="Contraseña de administrador" onkeydown="if(event.key==='Enter')entrar()">
  <button onclick="entrar()">Entrar</button>
</div>

<div id="c_panel" style="display:none">
  <div class="barra"><div class="mut">Sesión de administrador</div><button class="ghost chico" onclick="salir()">Salir</button></div>
  <div class="card"><h2>Solicitudes pendientes <span id="n_pend" class="badge b-pendiente">0</span></h2><div id="pendientes"></div></div>
  <div class="card"><h2>Personal registrado</h2><div id="usuarios"></div></div>
</div>

<script>
const q = id => document.getElementById(id);
let tokenA = null, vistos = null, timer = null;

function aviso(t, tipo){
  const m = q('msg');
  m.textContent = t || '';
  m.className = 'aviso ' + (tipo || 'ok');
  m.style.display = t ? 'block' : 'none';
}

async function api(url, metodo, cuerpo){
  const h = {};
  if (tokenA) h['x-admin'] = tokenA;
  const o = {method: metodo || 'GET', headers: h};
  if (cuerpo){ h['Content-Type'] = 'application/json'; o.body = JSON.stringify(cuerpo); }
  const r = await fetch(url, o);
  let d = {};
  try { d = await r.json(); } catch (e) {}
  if (r.status === 401 && tokenA) cerrar(true);
  if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Error HTTP ' + r.status);
  return d;
}

async function entrar(){
  try {
    const d = await api('/admin/login', 'POST', {clave: q('clave').value});
    tokenA = d.token; q('clave').value = ''; aviso('');
    q('c_login').style.display = 'none'; q('c_panel').style.display = 'block';
    try { if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission(); } catch (e) {}
    refrescar();
  } catch (e) { aviso(e.message, 'err'); }
}

function cerrar(expirada){
  tokenA = null; vistos = null; clearTimeout(timer);
  q('c_panel').style.display = 'none'; q('c_login').style.display = 'block';
  document.title = 'Administración · Llavero ETEC';
  if (expirada) aviso('La sesión venció. Volvé a entrar.', 'err');
}
function salir(){ cerrar(false); aviso(''); }

function boton(texto, clase, fn){
  const b = document.createElement('button');
  b.className = 'chico ' + clase; b.textContent = texto; b.onclick = fn;
  return b;
}

function fila(u, conAcciones){
  const f = document.createElement('div'); f.className = 'fila';
  const izq = document.createElement('div');
  const nom = document.createElement('b'); nom.textContent = u.usuario;
  const bd = document.createElement('span'); bd.className = 'badge b-' + u.estado; bd.textContent = u.estado; bd.style.marginLeft = '8px';
  const info = document.createElement('div'); info.className = 'mut';
  info.textContent = 'Solicitó: ' + u.creado + (u.estado === 'aprobado' ? ' · ' + u.fotos + ' foto(s)' : '');
  const t = document.createElement('div'); t.append(nom, bd);
  izq.append(t, info);
  const ac = document.createElement('div'); ac.className = 'acciones';
  if (conAcciones){
    ac.append(boton('Aprobar', 'ok', () => decidir(u.usuario, 'aprobar')),
              boton('Rechazar', 'rojo', () => decidir(u.usuario, 'rechazar')));
  } else {
    if (u.estado === 'rechazado') ac.append(boton('Aprobar', 'ok', () => decidir(u.usuario, 'aprobar')));
    ac.append(boton('Eliminar', 'ghost', () => eliminar(u.usuario)));
  }
  f.append(izq, ac);
  return f;
}

async function refrescar(){
  if (!tokenA) return;
  try {
    const d = await api('/admin/usuarios');
    const pend = d.usuarios.filter(u => u.estado === 'pendiente');
    const resto = d.usuarios.filter(u => u.estado !== 'pendiente');
    q('n_pend').textContent = pend.length;
    const cp = q('pendientes'); cp.innerHTML = '';
    if (!pend.length){ cp.innerHTML = '<p class="mut">No hay solicitudes pendientes.</p>'; }
    pend.forEach(u => cp.append(fila(u, true)));
    const cu = q('usuarios'); cu.innerHTML = '';
    if (!resto.length){ cu.innerHTML = '<p class="mut">Todavía no hay personal registrado.</p>'; }
    resto.forEach(u => cu.append(fila(u, false)));
    document.title = pend.length ? '(' + pend.length + ') Solicitudes · Llavero ETEC' : 'Administración · Llavero ETEC';
    if (vistos !== null && pend.length > vistos){
      const nuevo = pend[pend.length - 1].usuario;
      aviso('Nueva solicitud de acceso: ' + nuevo, 'info');
      try { if ('Notification' in window && Notification.permission === 'granted') new Notification('Nueva solicitud', {body: nuevo + ' pide acceso'}); } catch (e) {}
    }
    vistos = pend.length;
  } catch (e) {}
  timer = setTimeout(refrescar, 3000);
}

async function decidir(usuario, accion){
  try { await api('/admin/decidir', 'POST', {usuario: usuario, accion: accion}); aviso(''); refrescar(); }
  catch (e) { aviso(e.message, 'err'); }
}

async function eliminar(usuario){
  if (!confirm('¿Eliminar a ' + usuario + ' y borrar sus fotos? No se puede deshacer.')) return;
  try { await api('/admin/usuario/' + encodeURIComponent(usuario), 'DELETE'); refrescar(); }
  catch (e) { aviso(e.message, 'err'); }
}
</script></main></body></html>
""".replace("__CSS__", CSS)


@app.get("/")
async def raiz():
    return RedirectResponse("/registro")


@app.get("/registro", response_class=HTMLResponse)
async def pagina_usuario():
    return PAGINA_USUARIO


@app.get("/admin", response_class=HTMLResponse)
async def pagina_admin(request: Request):
    if ADMIN_SOLO_LOCAL and not es_local(request):
        raise HTTPException(status_code=404, detail="No encontrado")
    return HTMLResponse(PAGINA_ADMIN, headers={"Cache-Control": "no-store"})


# ============================ API DE ADMINISTRACIÓN ============================
class AdminLogin(BaseModel):
    clave: str


class Decision(BaseModel):
    usuario: str
    accion: str


@app.post("/admin/login")
async def admin_login(datos: AdminLogin, request: Request):
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
    print(f"[{obtener_hora()}] [ADMIN] Sesión de administrador iniciada")
    return {"token": token}


@app.get("/admin/usuarios")
async def admin_usuarios(request: Request):
    autenticar_admin(request)
    r = pb("GET", f"/api/collections/{COLECCION}/records", params={"perPage": 200, "sort": "creado"})
    if r.status_code != 200:
        raise HTTPException(status_code=503, detail="La base de datos de usuarios no está disponible.")
    return {"usuarios": [{"usuario": f["usuario"], "estado": f["estado"], "creado": f.get("creado", ""),
                          "fotos": len(archivos_de(f["usuario"]))} for f in r.json()["items"]]}


@app.post("/admin/decidir")
async def admin_decidir(datos: Decision, request: Request):
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
    print(f"[{obtener_hora()}] [ADMIN] {usuario} -> {nuevo}")
    return {"ok": True, "usuario": usuario, "estado": nuevo}


@app.delete("/admin/usuario/{usuario}")
async def admin_eliminar(usuario: str, request: Request):
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
    print(f"[{obtener_hora()}] [ADMIN] Usuario eliminado: {usuario}")
    return {"ok": True}


# ============================ CAPTURA DE FOTOS (usuarios aprobados) ============================
@app.get("/ultima_foto")
async def ultima_foto(request: Request):
    autenticar(request)
    if ULTIMA_FOTO["bytes"] is None:
        return Response(status_code=404)
    return Response(content=ULTIMA_FOTO["bytes"], media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/estado")
async def estado(request: Request):
    edad = None if ULTIMA_FOTO["bytes"] is None else int(time.time() - ULTIMA_FOTO["ts"])
    datos = {"modo": modo_actual(), "edad_foto": edad}
    usuario = usuario_de_sesion(request)
    if usuario:
        est = estado_de(usuario)
        if est:
            datos["estado_usuario"] = est
            if est == "aprobado":
                datos["ultimo"] = ULTIMO_RESULTADO["texto"]
    return datos


@app.post("/modo")
async def cambiar_modo(request: Request, m: str):
    autenticar(request)
    if m not in ("registro", "reconocimiento"):
        raise HTTPException(status_code=400, detail="Modo inválido")
    if MODO["valor"] != m:
        print(f"[{obtener_hora()}] [MODO] {m}")
    MODO["valor"] = m
    MODO["hasta"] = time.time() + REGISTRO_TIMEOUT_S
    return {"modo": m}


@app.post("/guardar_foto")
async def guardar_foto(request: Request):
    usuario = autenticar(request)
    if ULTIMA_FOTO["bytes"] is None or time.time() - ULTIMA_FOTO["ts"] > 10:
        return JSONResponse(status_code=400, content={
            "ok": False, "mensaje": "No hay una foto reciente. ¿La placa está enviando? Inicia la captura."})
    res = guardar_pendiente(usuario, ULTIMA_FOTO["bytes"])
    return JSONResponse(status_code=200 if res["ok"] else 422, content=res)


@app.get("/mis_fotos")
async def mis_fotos(request: Request):
    usuario = autenticar(request)
    fotos = [{"archivo": f, "estado": "ok"} for f in archivos_de(usuario)]
    fotos += [{"archivo": f, "estado": "pendiente"} for f in pendientes_de(usuario)]
    return {"fotos": fotos, "avisos": AVISOS.pop(usuario, [])}


@app.get("/foto/{archivo}")
async def ver_foto(archivo: str, request: Request):
    usuario = autenticar(request)
    return FileResponse(ruta_foto_de(usuario, archivo))


@app.delete("/foto/{archivo}")
async def borrar_foto(archivo: str, request: Request):
    usuario = autenticar(request)
    ruta = ruta_foto_de(usuario, archivo)
    try:
        os.remove(ruta)
    except FileNotFoundError:
        pass
    with LOCK_BASE:
        BASE_EMBEDDINGS.pop(os.path.basename(ruta), None)
    print(f"[{obtener_hora()}] [REGISTRO] {usuario}: borrada {os.path.basename(ruta)}")
    return {"ok": True}


# ============================ US03: DEVOLUCIÓN / RETIRO ============================
class EventoCasillero(BaseModel):
    casillero_id: str


@app.post("/devolucion")
async def devolucion(datos: EventoCasillero):
    registrar_estado(datos.casillero_id, "Disponible", "devolucion", None)
    print(f"[{obtener_hora()}] [DEVOLUCIÓN] {datos.casillero_id} -> Disponible")
    return {"status": "success", "casillero_id": datos.casillero_id, "estado": "Disponible"}


@app.post("/retiro")
async def retiro(datos: EventoCasillero):
    persona = None
    ult = ULTIMA_AUTORIZACION.get(datos.casillero_id)
    if ult and time.time() - ult[1] <= VENTANA_RETIRO_S:
        persona = ult[0]
    registrar_estado(datos.casillero_id, "En uso", "retiro", persona)
    print(f"[{obtener_hora()}] [RETIRO] {datos.casillero_id} -> En uso ({persona or 'sin identificar'})")
    return {"status": "success", "casillero_id": datos.casillero_id, "estado": "En uso", "persona": persona}


@app.get("/llaves")
async def listar_llaves():
    with closing(db()) as con:
        return [dict(r) for r in con.execute("SELECT * FROM llaves ORDER BY casillero_id")]


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)