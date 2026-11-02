import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from seguridad import autenticar_admin
from pocketbase import pb, normalizar_uid, UID_RE

router = APIRouter()

COLECCION = "tags"          # campos: uid, numero_aula


class TagNuevo(BaseModel):
    uid: str
    numero_aula: str


class TagEditar(BaseModel):
    uid: str | None = None
    numero_aula: str | None = None


def _check(r):
    if r.status_code in (200, 201, 204):
        return r.json() if r.content else {"ok": True}
    if r.status_code == 400:
        raise HTTPException(status_code=400, detail="Datos inválidos")
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Llavero no encontrado")
    raise HTTPException(status_code=503, detail="Base de datos no disponible")


def _listar() -> list:
    r = pb("GET", f"/api/collections/{COLECCION}/records", params={"perPage": 500, "sort": "numero_aula"})
    if r.status_code != 200:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    items = r.json().get("items", [])
    return [{"id": i["id"], "uid": normalizar_uid(i.get("uid", "")),
             "numero_aula": str(i.get("numero_aula", ""))} for i in items]


def _uid_repetido(uid: str, excepto_id: str = "") -> bool:
    return any(t["uid"] == uid and t["id"] != excepto_id for t in _listar())


def _validar_aula(numero: str) -> str:
    numero = (numero or "").strip()
    if not re.fullmatch(r"\d{1,6}", numero):
        raise HTTPException(status_code=400, detail="El número de aula debe ser numérico (ej. 214)")
    return numero


def _validar_uid(uid: str) -> str:
    uid = normalizar_uid(uid)
    if not re.fullmatch(UID_RE, uid):
        raise HTTPException(status_code=400, detail="UID inválido (hexadecimal, 4 a 20 caracteres)")
    return uid


def _crear(uid: str, numero_aula: str):
    if _uid_repetido(uid):
        raise HTTPException(status_code=400, detail="Ese UID ya está registrado")
    return _check(pb("POST", f"/api/collections/{COLECCION}/records",
                     json={"uid": uid, "numero_aula": numero_aula}))


def _editar(tag_id: str, campos: dict):
    if "uid" in campos and _uid_repetido(campos["uid"], tag_id):
        raise HTTPException(status_code=400, detail="Ese UID ya está registrado")
    return _check(pb("PATCH", f"/api/collections/{COLECCION}/records/{tag_id}", json=campos))


@router.get("/admin/tags")
async def api_listar(request: Request):
    autenticar_admin(request)
    return await run_in_threadpool(_listar)


@router.post("/admin/tags")
async def api_crear(t: TagNuevo, request: Request):
    autenticar_admin(request)
    uid = _validar_uid(t.uid)
    aula = _validar_aula(t.numero_aula)
    return await run_in_threadpool(_crear, uid, aula)


@router.patch("/admin/tags/{tag_id}")
async def api_editar(tag_id: str, t: TagEditar, request: Request):
    autenticar_admin(request)
    if not re.fullmatch(r"[a-z0-9]{15}", tag_id):
        raise HTTPException(status_code=400, detail="Id inválido")
    campos = {}
    if t.uid is not None:
        campos["uid"] = _validar_uid(t.uid)
    if t.numero_aula is not None:
        campos["numero_aula"] = _validar_aula(t.numero_aula)
    if not campos:
        raise HTTPException(status_code=400, detail="No hay nada para cambiar")
    return await run_in_threadpool(_editar, tag_id, campos)


@router.delete("/admin/tags/{tag_id}")
async def api_borrar(tag_id: str, request: Request):
    autenticar_admin(request)
    if not re.fullmatch(r"[a-z0-9]{15}", tag_id):
        raise HTTPException(status_code=400, detail="Id inválido")
    return _check(await run_in_threadpool(
        lambda: pb("DELETE", f"/api/collections/{COLECCION}/records/{tag_id}")))