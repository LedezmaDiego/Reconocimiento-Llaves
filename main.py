import os
import threading
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles

from config import (FRONTEND_DIST, DIRECTORIO_CARAS, DIRECTORIO_PENDIENTES, MODELO,
                    DETECTOR, UMBRAL, CLAVE_ADMIN)
from db import init_db
from estado import BASE_EMBEDDINGS
from fotos import worker_pendientes
from logs import log
from pocketbase import asegurar_coleccion
from reconocimiento import sincronizar_base
from routers.placa import router_reconocimiento, router_movimientos
from routers.usuarios import router as router_usuarios
from routers.paginas import router as router_paginas
from routers.admin import router as router_admin
from routers.captura import router as router_captura
from routers.aulas import router as router_aulas

app = FastAPI()
app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets"), check_dir=False),
          name="frontend-assets")

# Las docstrings de las funciones se usan como descripciones en OpenAPI; las quitamos
# aquí porque el contrato histórico las tenía vacías y no aportan información al cliente.
_openapi_original = app.openapi

def _openapi_sin_descripciones() -> dict:
    esquema = _openapi_original()
    for metodos in esquema.get("paths", {}).values():
        for operacion in metodos.values():
            operacion.pop("description", None)
    return esquema

app.openapi = _openapi_sin_descripciones


@app.on_event("startup")
async def startup_event() -> None:
    """Inicializa la base, PocketBase, carpetas, cámara y worker al arrancar."""
    init_db()
    try:
        await run_in_threadpool(asegurar_coleccion)
    except HTTPException:
        log("POCKETBASE", f"¡No pude conectar! Revisá PB_URL, PB_EMAIL y PB_PASSWORD.")
    os.makedirs(DIRECTORIO_CARAS, exist_ok=True)
    os.makedirs(DIRECTORIO_PENDIENTES, exist_ok=True)
    for f in os.listdir(DIRECTORIO_PENDIENTES):
        if f.endswith(".part"):
            os.remove(os.path.join(DIRECTORIO_PENDIENTES, f))

    print("\n" + "=" * 60)
    log("SISTEMA", f"Iniciando servidor | modelo={MODELO} detector={DETECTOR} umbral={UMBRAL}")
    if CLAVE_ADMIN == "cambiame-admin":
        log("SEGURIDAD", f"¡Estás usando la clave de admin por defecto! Definí ADMIN_CLAVE.")
    await run_in_threadpool(sincronizar_base)
    personas = sorted({d["persona"] for d in BASE_EMBEDDINGS.values()})
    log("SISTEMA", f"Listo: {len(BASE_EMBEDDINGS)} fotos válidas, personas: {personas}")
    log("SISTEMA", f"Usuarios:       http://IP_DE_ESTA_PC:8000/registro")
    log("SISTEMA", f"Administración: http://IP_DE_ESTA_PC:8000/admin")
    print("=" * 60 + "\n")
    threading.Thread(target=worker_pendientes, daemon=True).start()


# FastAPI 0.138 conserva estas rutas como entradas individuales de app.routes
# al registrar los APIRouter sin prefijo en su posición original.
app.router.routes.extend(router_reconocimiento.routes)
app.router.routes.extend(router_usuarios.routes)
app.router.routes.extend(router_paginas.routes)
app.router.routes.extend(router_admin.routes)
app.router.routes.extend(router_captura.routes)
app.router.routes.extend(router_movimientos.routes)
app.router.routes.extend(router_aulas.routes)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

