from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from deepface import DeepFace
from contextlib import closing
import os
import re
import sqlite3
import time
import uuid
import uvicorn
from datetime import datetime

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIRECTORIO_CARAS = os.path.join(BASE_DIR, "personas_autorizadas")
DB_PATH = os.path.join(BASE_DIR, "llaves.db")

DETECTOR = "yunet"          # si no detecta caras, probar: "retinaface", "mediapipe", "opencv"
EXIGIR_ROSTRO = True        # False = no verificar que haya una cara antes de comparar
VENTANA_RETIRO_S = 60       # segundos que vale una autorización facial para asociar un retiro

# {casillero_id: (persona, timestamp)}
ULTIMA_AUTORIZACION: dict[str, tuple[str, float]] = {}


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


# ============================ STARTUP ============================
@app.on_event("startup")
async def startup_event():
    init_db()
    print("\n" + "=" * 60)
    print(f"[{obtener_hora()}] [SISTEMA] Iniciando Servidor sin caché (Modo Seguro)")

    if os.path.exists(DIRECTORIO_CARAS):
        fotos = [f for f in os.listdir(DIRECTORIO_CARAS) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        if fotos:
            print(f"[{obtener_hora()}] [SISTEMA] ¡Éxito! {len(fotos)} fotos válidas encontradas: {fotos}")
        else:
            print(f"[{obtener_hora()}] [ALERTA] La carpeta existe pero no tiene imágenes válidas.")
    else:
        os.makedirs(DIRECTORIO_CARAS)
    print(f"[{obtener_hora()}] [SISTEMA] Detector de rostros: {DETECTOR}")
    print("=" * 60 + "\n")


# ============================ RECONOCIMIENTO ============================
def comparar_rostro(ruta_temp: str, fotos_db: list[str]) -> dict:
    """Bloqueante (DeepFace). Se ejecuta en un hilo aparte."""
    if EXIGIR_ROSTRO:
        try:
            DeepFace.extract_faces(img_path=ruta_temp,
                                   detector_backend=DETECTOR,
                                   enforce_detection=True)
        except ValueError:
            return {"rostro": False, "autorizado": False, "persona": "Desconocido", "distancia": None}

    persona = "Desconocido"
    mejor = 999.0
    autorizado = False

    for foto in fotos_db:
        ruta_db = os.path.join(DIRECTORIO_CARAS, foto)
        try:
            r = DeepFace.verify(img1_path=ruta_temp,
                                img2_path=ruta_db,
                                detector_backend=DETECTOR,
                                enforce_detection=False,
                                silent=True)
            if r["verified"] and r["distance"] < mejor:
                mejor = r["distance"]
                autorizado = True
                persona = re.sub(r'\d+', '', foto.split('.')[0]).capitalize()
        except Exception as e:
            print(f"[{obtener_hora()}] [ADVERTENCIA] No se pudo analizar {foto}: {e}")

    return {"rostro": True, "autorizado": autorizado, "persona": persona,
            "distancia": mejor if autorizado else None}


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

        fotos_db = [f for f in os.listdir(DIRECTORIO_CARAS) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        if not fotos_db:
            return {"status": "error", "mensaje": "Carpeta de rostros vacía en el sistema."}

        res = await run_in_threadpool(comparar_rostro, ruta_temp, fotos_db)

        if res["autorizado"]:
            ULTIMA_AUTORIZACION[casillero_id] = (res["persona"], time.time())
            print(f"[{obtener_hora()}] [ACCESO PERMITIDO] {res['persona']} (dist: {res['distancia']:.2f})")
            print("-" * 60)
            return {"status": "success", "autorizado": True, "persona": res["persona"],
                    "mensaje": f"Bienvenido/a, {res['persona']}.", "distancia": res["distancia"]}

        motivo = "Persona no registrada." if res["rostro"] else "No se detectó ningún rostro."
        print(f"[{obtener_hora()}] [ACCESO DENEGADO] {motivo}")
        print("-" * 60)
        return {"status": "success", "autorizado": False, "persona": "Desconocido", "mensaje": motivo}

    except Exception as e:
        print(f"[{obtener_hora()}] [ERROR GENERAL] {e}")
        print("-" * 60)
        return {"status": "error", "mensaje": str(e)}
    finally:
        if os.path.exists(ruta_temp):
            os.remove(ruta_temp)


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