import os
import io
from fastapi import FastAPI, File, UploadFile
from PIL import Image
import numpy as np
from deepface import DeepFace

app = FastAPI()

CARPETA_AUTORIZADOS = "personas_autorizadas"
MODELO = "Facenet"
UMBRAL_DISTANCIA = 10


@app.on_event("startup")
def startup():
    """Crea la carpeta de personas autorizadas si no existe."""
    if not os.path.exists(CARPETA_AUTORIZADOS):
        os.makedirs(CARPETA_AUTORIZADOS)
    print("Servidor listo. Personas autorizadas:", os.listdir(CARPETA_AUTORIZADOS))


@app.post("/reconocimiento")
async def reconocimiento(file: UploadFile = File(...)):
    """Recibe una foto del ESP32-CAM y la compara contra personas autorizadas."""
    contenido = await file.read()
    imagen_pil = Image.open(io.BytesIO(contenido)).convert("RGB")
    imagen_np = np.array(imagen_pil)

    try:
        resultados = DeepFace.find(
            img_path=imagen_np,
            db_path=CARPETA_AUTORIZADOS,
            model_name=MODELO,
            enforce_detection=True,
            silent=True,
        )
    except ValueError:
        return {"autorizado": False, "motivo": "no_se_detecto_cara"}

    if len(resultados) == 0 or resultados[0].empty:
        return {"autorizado": False, "motivo": "no_coincide"}

    mejor_match = resultados[0].iloc[0]
    ruta_archivo = mejor_match["identity"]
    nombre = os.path.splitext(os.path.basename(ruta_archivo))[0]

    print(f"Autorizado: {nombre}")
    return {"autorizado": True, "persona": nombre}


@app.get("/")
def home():
    """Endpoint simple para verificar que el servidor esta activo."""
    personas = [
        os.path.splitext(f)[0] for f in os.listdir(CARPETA_AUTORIZADOS)
    ]
    return {"mensaje": "Servidor activo", "personas_cargadas": personas}