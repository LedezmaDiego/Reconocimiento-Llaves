import asyncio
import os
import time
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response, JSONResponse, FileResponse

from config import (REGISTRO_TIMEOUT_S, FOTO_RECIENTE_S, FOTOS_LOTE_DEFECTO,
                    FOTOS_LOTE_MAX, ESPERA_ENTRE_FOTOS_S)
from estado import (ULTIMA_FOTO, ULTIMO_RESULTADO, MODO, AVISOS, BASE_EMBEDDINGS, LOCK_BASE, modo_actual)
from fotos import guardar_pendiente, archivos_de, pendientes_de, ruta_foto_de
from logs import log
from pocketbase import estado_de
from seguridad import autenticar, usuario_de_sesion

router = APIRouter()

@router.get("/ultima_foto")
async def ultima_foto(request: Request):
    """Devuelve la última imagen JPEG vista por la placa si la sesión es válida."""
    autenticar(request)
    if ULTIMA_FOTO["bytes"] is None:
        return Response(status_code=404)
    return Response(content=ULTIMA_FOTO["bytes"], media_type="image/jpeg", headers={"Cache-Control": "no-store"})

@router.get("/estado")
async def estado(request: Request):
    """Devuelve modo actual, frescura de la última foto y datos de sesión."""
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

@router.post("/modo")
async def cambiar_modo(request: Request, m: str):
    """Permite a una sesión aprobada alternar entre registro y reconocimiento."""
    autenticar(request)
    if m not in ("registro", "reconocimiento"):
        raise HTTPException(status_code=400, detail="Modo inválido")
    if MODO["valor"] != m:
        log("MODO", f"{m}")
    MODO["valor"] = m
    MODO["hasta"] = time.time() + REGISTRO_TIMEOUT_S
    return {"modo": m}

@router.post("/guardar_foto")
async def guardar_foto(request: Request):
    """Guarda la última foto recibida de la placa como pendiente."""
    usuario = autenticar(request)
    if ULTIMA_FOTO["bytes"] is None or time.time() - ULTIMA_FOTO["ts"] > FOTO_RECIENTE_S:
        return JSONResponse(status_code=400, content={
            "ok": False, "mensaje": "No hay una foto reciente. ¿La placa está enviando? Inicia la captura."})
    res = guardar_pendiente(usuario, ULTIMA_FOTO["bytes"])
    return JSONResponse(status_code=200 if res["ok"] else 422, content=res)

async def _esperar_frame_nuevo(ts_anterior: float, timeout: float) -> bool:
    """Espera a que la placa envíe un frame más reciente que ts_anterior."""
    limite = time.time() + timeout
    while time.time() < limite:
        if ULTIMA_FOTO["ts"] > ts_anterior and ULTIMA_FOTO["bytes"] is not None:
            return True
        await asyncio.sleep(0.05)
    return False

@router.post("/guardar_lote")
async def guardar_lote(request: Request, cantidad: int = FOTOS_LOTE_DEFECTO):
    """Guarda varias fotos distintas con una sola pulsación (captura en ráfaga)."""
    usuario = autenticar(request)
    cantidad = max(1, min(cantidad, FOTOS_LOTE_MAX))

    guardadas, errores = [], []
    ts_previo = float("-inf")
    for _ in range(cantidad):
        if not await _esperar_frame_nuevo(ts_previo, 3.0):
            # La placa dejó de enviar: no seguir esperando en vano.
            errores.append("La placa no envió una foto nueva a tiempo.")
            break
        ts_previo = ULTIMA_FOTO["ts"]
        res = guardar_pendiente(usuario, ULTIMA_FOTO["bytes"])
        if res["ok"]:
            guardadas.append(res["archivo"])
        else:
            errores.append(res["mensaje"])
            break
        if len(guardadas) < cantidad:
            await asyncio.sleep(ESPERA_ENTRE_FOTOS_S)

    if not guardadas and errores:
        return JSONResponse(status_code=422, content={"ok": False, "mensaje": errores[0]})
    resumen = f"{len(guardadas)} foto(s) guardada(s)"
    if errores:
        resumen += f" · {errores[0]}"
    return {"ok": True, "guardadas": guardadas, "mensaje": resumen, "errores": errores}

@router.get("/mis_fotos")
async def mis_fotos(request: Request):
    """Lista fotos aprobadas y pendientes del usuario autenticado."""
    usuario = autenticar(request)
    fotos = [{"archivo": f, "estado": "ok"} for f in archivos_de(usuario)]
    fotos += [{"archivo": f, "estado": "pendiente"} for f in pendientes_de(usuario)]
    return {"fotos": fotos, "avisos": AVISOS.pop(usuario, [])}

@router.get("/foto/{archivo}")
async def ver_foto(archivo: str, request: Request):
    """Sirve una foto propia, autorizada o pendiente, del usuario autenticado."""
    usuario = autenticar(request)
    return FileResponse(ruta_foto_de(usuario, archivo))

@router.delete("/foto/{archivo}")
async def borrar_foto(archivo: str, request: Request):
    """Elimina una foto propia y descarta su embedding asociado."""
    usuario = autenticar(request)
    ruta = ruta_foto_de(usuario, archivo)
    try:
        os.remove(ruta)
    except FileNotFoundError:
        pass
    with LOCK_BASE:
        BASE_EMBEDDINGS.pop(os.path.basename(ruta), None)
    log("REGISTRO", f"{usuario}: borrada {os.path.basename(ruta)}")
    return {"ok": True}


