import re
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException

from config import (AULA_NOMBRE_MAX, AULA_UBICACION_MAX, PRESTAMO_TEXTO_MAX,
                    PRESTAMOS_HISTORIAL)
from db import (aulas, aula_por_id, crear_aula, actualizar_aula, registrar_prestamo,
                prestamo_activo, devolver_prestamo, historial_prestamos)
from logs import log, obtener_hora
from schemas import PedidoLlave, DevolucionLlave, AulaNueva, AulaEdicion
from seguridad import autenticar, autenticar_admin

router = APIRouter()

HORA_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _estado_aula(a: dict, ahora: str) -> str:
    """Calcula el estado visible de un aula: disponible, ocupada, vencida o inactiva."""
    if not a["activa"]:
        return "inactiva"
    if a["prestamo_id"]:
        # Las fechas son texto "YYYY-MM-DD HH:MM[:SS]", comparables directamente.
        return "vencida" if a["hasta"] < ahora else "ocupada"
    return "disponible"


def _texto(valor: str, campo: str, maximo: int) -> str:
    """Normaliza y valida un texto corto obligatorio."""
    limpio = (valor or "").strip()
    if not limpio:
        raise HTTPException(status_code=400, detail=f"Falta completar {campo}.")
    if len(limpio) > maximo:
        raise HTTPException(status_code=400, detail=f"{campo} no puede superar {maximo} caracteres.")
    return limpio


@router.get("/aulas", response_model=None)
async def listar_aulas(request: Request) -> list[dict]:
    """Lista las aulas con su estado y el préstamo activo, para el panel."""
    autenticar(request)
    ahora = obtener_hora()
    return [{**a, "estado": _estado_aula(a, ahora)} for a in aulas()]


@router.post("/aulas/pedir")
async def pedir_llave(datos: PedidoLlave, request: Request):
    """Registra el retiro de la llave de un aula."""
    usuario = autenticar(request)
    aula = aula_por_id(datos.aula_id)
    if not aula:
        raise HTTPException(status_code=404, detail="Ese aula no existe.")
    if not aula["activa"]:
        raise HTTPException(status_code=409, detail="Ese aula está deshabilitada.")

    actividad = _texto(datos.actividad, "la actividad", PRESTAMO_TEXTO_MAX)
    profesor = _texto(datos.profesor, "el profesor", PRESTAMO_TEXTO_MAX) if datos.profesor.strip() else usuario.capitalize()

    if not HORA_RE.fullmatch(datos.hasta or ""):
        raise HTTPException(status_code=400, detail="Elegí una hora de fin válida (HH:MM).")
    hasta = f"{obtener_hora()[:10]} {datos.hasta}"
    if hasta <= obtener_hora():
        raise HTTPException(status_code=400, detail="Esa hora ya pasó. Elegí una hora de fin posterior.")

    if prestamo_activo(datos.aula_id):
        raise HTTPException(status_code=409, detail="Esa llave todavía no fue devuelta. Avisá al administrador.")

    prestamo = registrar_prestamo(datos.aula_id, profesor, actividad, hasta, usuario)
    log("LLAVE", f"{aula['nombre']}: retirada por {profesor} ({actividad}) hasta {datos.hasta}")
    return {"ok": True, "prestamo": prestamo}


@router.post("/aulas/devolver")
async def devolver_llave(datos: DevolucionLlave, request: Request):
    """Marca la devolución de la llave. Puede hacerlo quien la pidió o el admin."""
    try:
        autenticar_admin(request)
        usuario = None
    except HTTPException:
        usuario = autenticar(request)

    prestamo = prestamo_activo(datos.aula_id)
    if not prestamo:
        raise HTTPException(status_code=409, detail="Esa llave ya figura como devuelta.")
    if usuario is not None and prestamo["registrado_por"] != usuario:
        raise HTTPException(status_code=403, detail="Solo quien retiró la llave o el administrador puede devolverla.")

    devolver_prestamo(prestamo["id"])
    aula = aula_por_id(datos.aula_id)
    log("LLAVE", f"{aula['nombre'] if aula else datos.aula_id}: devuelta")
    return {"ok": True}


# ---------------- Administración de aulas ----------------

@router.get("/admin/aulas", response_model=None)
async def admin_aulas(request: Request) -> dict:
    """Devuelve aulas, préstamos activos e historial para el panel de administración."""
    autenticar_admin(request)
    ahora = obtener_hora()
    lista = [{**a, "estado": _estado_aula(a, ahora)} for a in aulas()]
    return {"aulas": lista, "historial": historial_prestamos(PRESTAMOS_HISTORIAL)}


@router.post("/admin/aulas")
async def admin_crear_aula(datos: AulaNueva, request: Request):
    """Da de alta un aula nueva."""
    autenticar_admin(request)
    nombre = _texto(datos.nombre, "el nombre", AULA_NOMBRE_MAX)
    ubicacion = (datos.ubicacion or "").strip()
    if len(ubicacion) > AULA_UBICACION_MAX:
        raise HTTPException(status_code=400, detail=f"La ubicación no puede superar {AULA_UBICACION_MAX} caracteres.")
    aula = crear_aula(nombre, ubicacion)
    log("AULAS", f"Creada: {nombre}")
    return {"ok": True, "aula": aula}


@router.patch("/admin/aulas/{aula_id}")
async def admin_editar_aula(aula_id: int, datos: AulaEdicion, request: Request):
    """Edita nombre, ubicación o estado activo de un aula."""
    autenticar_admin(request)
    if not aula_por_id(aula_id):
        raise HTTPException(status_code=404, detail="Ese aula no existe.")
    campos = datos.model_dump(exclude_none=True)
    if "nombre" in campos:
        campos["nombre"] = _texto(campos["nombre"], "el nombre", AULA_NOMBRE_MAX)
    if "ubicacion" in campos and len(campos["ubicacion"].strip()) > AULA_UBICACION_MAX:
        raise HTTPException(status_code=400, detail=f"La ubicación no puede superar {AULA_UBICACION_MAX} caracteres.")
    aula = actualizar_aula(aula_id, campos)
    log("AULAS", f"Actualizada #{aula_id}: {campos}")
    return {"ok": True, "aula": aula}


@router.post("/admin/aulas/{aula_id}/liberar")
async def admin_liberar_aula(aula_id: int, request: Request):
    """Fuerza la devolución de una llave (por ejemplo, si quedó sin devolver)."""
    autenticar_admin(request)
    aula = aula_por_id(aula_id)
    if not aula:
        raise HTTPException(status_code=404, detail="Ese aula no existe.")
    prestamo = prestamo_activo(aula_id)
    if not prestamo:
        raise HTTPException(status_code=409, detail="Esa llave ya figura como devuelta.")
    devolver_prestamo(prestamo["id"])
    log("AULAS", f"{aula['nombre']}: liberada por el administrador")
    return {"ok": True}
