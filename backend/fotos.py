import os
import re
import time
from fastapi import HTTPException

from config import (DIRECTORIO_CARAS, DIRECTORIO_PENDIENTES, MAX_FOTOS_POR_USUARIO,
                    UMBRAL, WORKER_PENDIENTES_ESPERA_S)
from estado import LOCK_NOMBRES, LOCK_BASE, BASE_EMBEDDINGS, AVISOS
from logs import log
from reconocimiento import calcular_embedding, distancia_coseno

def _archivos_en(carpeta: str, usuario: str) -> list[str]:
    """Lista los archivos de una carpeta que corresponden a un usuario."""
    if not os.path.exists(carpeta):
        return []
    patron = re.compile(rf"{usuario}\d+\.(jpg|jpeg|png)", re.IGNORECASE)
    return sorted(f for f in os.listdir(carpeta) if patron.fullmatch(f))

def archivos_de(usuario: str) -> list[str]:
    """Devuelve las fotos aprobadas del usuario indicado."""
    return _archivos_en(DIRECTORIO_CARAS, usuario)

def pendientes_de(usuario: str) -> list[str]:
    """Devuelve las fotos pendientes de revisión del usuario indicado."""
    return _archivos_en(DIRECTORIO_PENDIENTES, usuario)

def ruta_foto_de(usuario: str, archivo: str) -> str:
    """Resuelve la ruta de una foto del usuario entre autorizadas y pendientes."""
    archivo = os.path.basename(archivo)
    if archivo in archivos_de(usuario):
        return os.path.join(DIRECTORIO_CARAS, archivo)
    if archivo in pendientes_de(usuario):
        return os.path.join(DIRECTORIO_PENDIENTES, archivo)
    raise HTTPException(status_code=404, detail="Foto no encontrada")

def guardar_pendiente(usuario: str, datos: bytes) -> dict:
    """Guarda una nueva foto pendiente respetando el límite por usuario."""
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
    log("REGISTRO", f"{usuario}: foto {archivo} guardada en fotos_pendientes")
    return {"ok": True, "archivo": archivo, "estado": "pendiente"}

def rechazar_pendiente(usuario: str, archivo: str, ruta: str, motivo: str):
    """Elimina una foto verificada y registra el aviso para el usuario."""
    try:
        os.remove(ruta)
    except OSError:
        pass
    AVISOS.setdefault(usuario, []).append(f"{archivo}: {motivo}")
    log("REGISTRO", f"{archivo} rechazada: {motivo}")

def procesar_pendiente(archivo: str):
    """Verifica una foto pendiente, la aprueba o la rechaza con motivo."""
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
        log("REGISTRO", f"{archivo} aprobada y movida a personas_autorizadas")

def worker_pendientes() -> None:
    """Procesa en segundo plano las fotos pendientes cada segundo."""
    while True:
        try:
            pendientes = sorted(f for f in os.listdir(DIRECTORIO_PENDIENTES) if f.lower().endswith(".jpg"))
        except Exception:
            pendientes = []
        if not pendientes:
            time.sleep(WORKER_PENDIENTES_ESPERA_S)
            continue
        for f in pendientes:
            try:
                procesar_pendiente(f)
            except Exception as e:
                log("ERROR", f"Verificando {f}: {e}")
                try:
                    os.remove(os.path.join(DIRECTORIO_PENDIENTES, f))
                except OSError:
                    pass


