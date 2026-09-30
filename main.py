from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from deepface import DeepFace
from contextlib import closing
import numpy as np
import os
import re
import sqlite3
import threading
import time
import uuid
import uvicorn
from datetime import datetime

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIRECTORIO_CARAS = os.path.join(BASE_DIR, "personas_autorizadas")
DB_PATH = os.path.join(BASE_DIR, "llaves.db")
EXTENSIONES = (".jpg", ".jpeg", ".png")

MODELO = "VGG-Face"
DETECTOR = "yunet"          # si no detecta caras, probar "retinaface"
UMBRAL = 0.40               # distancia coseno máxima para aceptar (menor = más estricto)
EXIGIR_ROSTRO = True        # False = no exigir que se detecte una cara en la foto entrante
VENTANA_RETIRO_S = 60       # segundos que vale una autorización facial para asociar un retiro

# {casillero_id: (persona, timestamp)}
ULTIMA_AUTORIZACION: dict[str, tuple[str, float]] = {}

# {archivo: {"mtime": float, "emb": np.ndarray, "persona": str}}
BASE_EMBEDDINGS: dict[str, dict] = {}
LOCK_BASE = threading.Lock()


def obtener_hora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================ BASE DE DATOS ============================
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with closing(db()) as con, con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS llaves (
                casillero_id TEXT PRIMARY KEY,
                estado       TEXT NOT NULL DEFAULT 'Disponible',
                persona      TEXT,
                actualizado  TEXT NOT NULL
            )""")
        con.execute("""
            CREATE TABLE IF NOT EXISTS historial (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                casillero_id TEXT NOT NULL,
                evento       TEXT NOT NULL,
                persona      TEXT,
                fecha        TEXT NOT NULL
            )""")


def registrar_estado(casillero_id: str, estado: str, evento: str, persona: str | None = None):
    ahora = obtener_hora()
    with closing(db()) as con, con:
        con.execute("""
            INSERT INTO llaves (casillero_id, estado, persona, actualizado)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(casillero_id) DO UPDATE SET
                estado = excluded.estado,
                persona = excluded.persona,
                actualizado = excluded.actualizado
            """, (casillero_id, estado, persona, ahora))
        con.execute(
            "INSERT INTO historial (casillero_id, evento, persona, fecha) VALUES (?, ?, ?, ?)",
            (casillero_id, evento, persona, ahora))


# ============================ RECONOCIMIENTO ============================
def nombre_persona(archivo: str) -> str:
    return re.sub(r"\d+", "", archivo.split(".")[0]).capitalize()


def calcular_embedding(ruta: str, exigir_rostro: bool) -> np.ndarray:
    """Devuelve el embedding de la cara más grande de la imagen.
    Lanza ValueError si exigir_rostro=True y no hay ninguna cara."""
    res = DeepFace.represent(
        img_path=ruta,
        model_name=MODELO,
        detector_backend=DETECTOR,
        enforce_detection=exigir_rostro,
    )

    def area(r):
        fa = r.get("facial_area", {})
        return fa.get("w", 0) * fa.get("h", 0)

    mejor = max(res, key=area)
    return np.array(mejor["embedding"], dtype=np.float32)


def distancia_coseno(a: np.ndarray, b: np.ndarray) -> float:
    return float(1.0 - np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def sincronizar_base():
    """Calcula (una sola vez) el embedding de cada foto de referencia.
    Detecta fotos nuevas, modificadas o borradas sin reiniciar el servidor."""
    with LOCK_BASE:
        if not os.path.exists(DIRECTORIO_CARAS):
            os.makedirs(DIRECTORIO_CARAS)

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
                print(f"[{obtener_hora()}] [ADVERTENCIA] {f} ignorada (sin cara detectable o corrupta): {str(e)[:80]}")


def comparar_rostro(ruta_temp: str) -> dict:
    """Bloqueante (DeepFace). Se ejecuta en un hilo aparte."""
    sincronizar_base()

    if not BASE_EMBEDDINGS:
        return {"vacia": True}

    try:
        emb = calcular_embedding(ruta_temp, exigir_rostro=EXIGIR_ROSTRO)
    except ValueError:
        return {"rostro": False, "autorizado": False, "persona": "Desconocido", "distancia": None}

    mejor_dist = 999.0
    mejor_persona = "Desconocido"
    with LOCK_BASE:
        for f, datos in BASE_EMBEDDINGS.items():
            d = distancia_coseno(emb, datos["emb"])
            if d < mejor_dist:
                mejor_dist = d
                mejor_persona = datos["persona"]

    autorizado = mejor_dist <= UMBRAL
    return {
        "rostro": True,
        "autorizado": autorizado,
        "persona": mejor_persona if autorizado else "Desconocido",
        "distancia": mejor_dist,
        "mas_parecido": mejor_persona,
    }


# ============================ STARTUP ============================
@app.on_event("startup")
async def startup_event():
    init_db()
    print("\n" + "=" * 60)
    print(f"[{obtener_hora()}] [SISTEMA] Iniciando servidor | modelo={MODELO} detector={DETECTOR} umbral={UMBRAL}")
    print(f"[{obtener_hora()}] [SISTEMA] Cargando fotos de referencia (la primera vez descarga modelos)...")
    await run_in_threadpool(sincronizar_base)
    personas = sorted({d["persona"] for d in BASE_EMBEDDINGS.values()})
    print(f"[{obtener_hora()}] [SISTEMA] Listo: {len(BASE_EMBEDDINGS)} fotos válidas, personas: {personas}")
    print("=" * 60 + "\n")


# ============================ ENDPOINTS ============================
@app.post("/reconocimiento")
async def reconocer_rostro(request: Request):
    casillero_id = request.headers.get("x-casillero-id", "C01")
    ruta_temp = os.path.join(BASE_DIR, f"temp_{uuid.uuid4().hex}.jpg")

    try:
        cuerpo = await request.body()
        print(f"[{obtener_hora()}] [PETICIÓN] {casillero_id}: imagen de {len(cuerpo)} bytes")

        if len(cuerpo) < 1000:
            return {"status": "error", "mensaje": "Imagen muy pequeña o corrupta"}

        with open(ruta_temp, "wb") as f:
            f.write(cuerpo)

        res = await run_in_threadpool(comparar_rostro, ruta_temp)

        if res.get("vacia"):
            return {"status": "error", "mensaje": "No hay fotos de referencia válidas en el sistema."}

        if res["autorizado"]:
            ULTIMA_AUTORIZACION[casillero_id] = (res["persona"], time.time())
            print(f"[{obtener_hora()}] [ACCESO PERMITIDO] {res['persona']} (dist: {res['distancia']:.3f})")
            print("-" * 60)
            return {"status": "success", "autorizado": True, "persona": res["persona"],
                    "mensaje": f"Bienvenido/a, {res['persona']}.", "distancia": res["distancia"]}

        if res["rostro"]:
            print(f"[{obtener_hora()}] [ACCESO DENEGADO] Persona no registrada "
                  f"(más parecido: {res['mas_parecido']}, dist: {res['distancia']:.3f}, umbral: {UMBRAL})")
            motivo = "Persona no registrada."
        else:
            print(f"[{obtener_hora()}] [SIN ROSTRO] No se detectó ninguna cara en la imagen")
            motivo = "No se detectó ningún rostro."
        print("-" * 60)
        return {"status": "success", "autorizado": False, "persona": "Desconocido", "mensaje": motivo}

    except Exception as e:
        print(f"[{obtener_hora()}] [ERROR GENERAL] {e}")
        print("-" * 60)
        return {"status": "error", "mensaje": str(e)}
    finally:
        if os.path.exists(ruta_temp):
            os.remove(ruta_temp)


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