import os
import time
import uuid
from contextlib import closing
from datetime import datetime
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from config import (BASE_DIR, CASILLERO_DEFECTO, CODIGO_VALIDO_S, UMBRAL,
                    VENTANA_RETIRO_S, MIN_BYTES_IMAGEN)
from db import db, registrar_estado
from estado import (ACCESO_CODIGO, ULTIMA_AUTORIZACION, ULTIMA_FOTO, ULTIMO_RESULTADO, modo_actual)
from logs import log
from reconocimiento import comparar_rostro
from schemas import EventoCasillero

router_reconocimiento = APIRouter()
router_movimientos = APIRouter()

@router_reconocimiento.post("/reconocimiento")
async def reconocer_rostro(request: Request):
    """Recibe JPEG de la placa y devuelve autorización en formato compatible."""
    casillero_id = request.headers.get("x-casillero-id", CASILLERO_DEFECTO)
    cuerpo = await request.body()
    if len(cuerpo) < MIN_BYTES_IMAGEN:
        log("PETICIÓN", f"{casillero_id}: imagen de {len(cuerpo)} bytes (descartada)")
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
        log("ACCESO PERMITIDO", f"{persona} (por código personal)")
        print("-" * 60)
        return {"status": "success", "modo": "reconocimiento", "autorizado": True,
                "persona": persona, "metodo": "codigo", "mensaje": f"Bienvenido/a, {persona}."}

    ruta_temp = os.path.join(BASE_DIR, f"temp_{uuid.uuid4().hex}.jpg")
    try:
        log("PETICIÓN", f"{casillero_id}: imagen de {len(cuerpo)} bytes")
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
            log("ACCESO PERMITIDO", f"{res['persona']} (dist: {res['distancia']:.3f})")
            print("-" * 60)
            return {"status": "success", "modo": "reconocimiento", "autorizado": True,
                    "persona": res["persona"], "metodo": "rostro",
                    "mensaje": f"Bienvenido/a, {res['persona']}.", "distancia": res["distancia"]}

        if res["rostro"]:
            log("ACCESO DENEGADO", f"Persona no registrada "
                  f"(más parecido: {res['mas_parecido']}, dist: {res['distancia']:.3f}, umbral: {UMBRAL})")
            motivo = "Persona no registrada."
        else:
            log("SIN ROSTRO", f"No se detectó ninguna cara en la imagen")
            motivo = "No se detectó ningún rostro."
        ULTIMO_RESULTADO["texto"] = f"Denegado: {motivo} ({datetime.now().strftime('%H:%M:%S')})"
        print("-" * 60)
        return {"status": "success", "modo": "reconocimiento", "autorizado": False,
                "persona": "Desconocido", "mensaje": motivo}
    except Exception as e:
        log("ERROR GENERAL", f"{e}")
        print("-" * 60)
        return {"status": "error", "mensaje": str(e)}
    finally:
        if os.path.exists(ruta_temp):
            os.remove(ruta_temp)

@router_movimientos.post("/devolucion")
async def devolucion(datos: EventoCasillero):
    """Marca el casillero como disponible para la siguiente devolución."""
    registrar_estado(datos.casillero_id, "Disponible", "devolucion", None)
    log("DEVOLUCIÓN", f"{datos.casillero_id} -> Disponible")
    return {"status": "success", "casillero_id": datos.casillero_id, "estado": "Disponible"}

@router_movimientos.post("/retiro")
async def retiro(datos: EventoCasillero):
    """Marca el casillero como en uso y conserva al último usuario autorizado."""
    persona = None
    ult = ULTIMA_AUTORIZACION.get(datos.casillero_id)
    if ult and time.time() - ult[1] <= VENTANA_RETIRO_S:
        persona = ult[0]
    registrar_estado(datos.casillero_id, "En uso", "retiro", persona)
    log("RETIRO", f"{datos.casillero_id} -> En uso ({persona or 'sin identificar'})")
    return {"status": "success", "casillero_id": datos.casillero_id, "estado": "En uso", "persona": persona}

@router_movimientos.get("/llaves", response_model=None)
async def listar_llaves() -> list[dict]:
    """Devuelve el estado de todos los casilleros registrados."""
    with closing(db()) as con:
        return [dict(r) for r in con.execute("SELECT * FROM llaves ORDER BY casillero_id")]


