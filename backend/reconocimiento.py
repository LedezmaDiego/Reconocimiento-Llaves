import os
import re
import numpy as np
from deepface import DeepFace

from config import (DIRECTORIO_CARAS, EXTENSIONES, MODELO, DETECTOR, UMBRAL,
                    EXIGIR_ROSTRO, LONGITUD_ERROR_BREVE, DISTANCIA_DESCONOCIDA)
from estado import BASE_EMBEDDINGS, LOCK_BASE, LOCK_DEEPFACE
from logs import log

def nombre_persona(archivo: str) -> str:
    """Extrae un nombre visible a partir del nombre de archivo."""
    return re.sub(r"\d+", "", archivo.split(".")[0]).capitalize()

def calcular_embedding(ruta: str, exigir_rostro: bool) -> np.ndarray:
    """Obtiene un embedding representativo de la foto con DeepFace."""
    with LOCK_DEEPFACE:
        res = DeepFace.represent(img_path=ruta, model_name=MODELO, detector_backend=DETECTOR,
                                 enforce_detection=exigir_rostro)

    def area(r):
        fa = r.get("facial_area", {})
        return fa.get("w", 0) * fa.get("h", 0)

    return np.array(max(res, key=area)["embedding"], dtype=np.float32)

def distancia_coseno(a: np.ndarray, b: np.ndarray) -> float:
    """Calcula la distancia coseno entre dos embeddings."""
    return float(1.0 - np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

def sincronizar_base() -> None:
    """Carga, recarga y elimina embeddings según las fotos autorizadas."""
    with LOCK_BASE:
        os.makedirs(DIRECTORIO_CARAS, exist_ok=True)
        archivos = {f for f in os.listdir(DIRECTORIO_CARAS) if f.lower().endswith(EXTENSIONES)}
        for f in list(BASE_EMBEDDINGS):
            if f not in archivos:
                del BASE_EMBEDDINGS[f]
                log("BASE", f"Foto eliminada: {f}")
        for f in sorted(archivos):
            ruta = os.path.join(DIRECTORIO_CARAS, f)
            mtime = os.path.getmtime(ruta)
            if f in BASE_EMBEDDINGS and BASE_EMBEDDINGS[f]["mtime"] == mtime:
                continue
            try:
                emb = calcular_embedding(ruta, exigir_rostro=True)
                BASE_EMBEDDINGS[f] = {"mtime": mtime, "emb": emb, "persona": nombre_persona(f)}
                log("BASE", f"Cargada: {f} -> {nombre_persona(f)}")
            except Exception as e:
                BASE_EMBEDDINGS.pop(f, None)
                log("ADVERTENCIA", f"{f} ignorada: {str(e)[:LONGITUD_ERROR_BREVE]}")

def comparar_rostro(ruta_temp: str) -> dict:
    """Compara un rostro contra la base de fotos autorizadas."""
    sincronizar_base()
    if not BASE_EMBEDDINGS:
        return {"vacia": True}
    try:
        emb = calcular_embedding(ruta_temp, exigir_rostro=EXIGIR_ROSTRO)
    except ValueError:
        return {"rostro": False, "autorizado": False, "persona": "Desconocido", "distancia": None}

    mejor_dist, mejor_persona = DISTANCIA_DESCONOCIDA, "Desconocido"
    with LOCK_BASE:
        for datos in BASE_EMBEDDINGS.values():
            d = distancia_coseno(emb, datos["emb"])
            if d < mejor_dist:
                mejor_dist, mejor_persona = d, datos["persona"]

    autorizado = mejor_dist <= UMBRAL
    return {"rostro": True, "autorizado": autorizado,
            "persona": mejor_persona if autorizado else "Desconocido",
            "distancia": mejor_dist, "mas_parecido": mejor_persona}


