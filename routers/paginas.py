import os
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, Response

from config import FRONTEND_DIST, ADMIN_SOLO_LOCAL
from seguridad import es_local

router = APIRouter()

@router.get("/")
async def raiz() -> RedirectResponse:
    """Redirige la página principal al inicio de sesión."""
    return RedirectResponse("/inicio-sesion")

def pagina_react() -> Response:
    """Sirve el build de React o aviso si todavía no fue compilado."""
    indice = os.path.join(FRONTEND_DIST, "index.html")
    if not os.path.isfile(indice):
        return HTMLResponse("Frontend sin compilar: ejecutá npm install y npm run build en frontend/.",
                            status_code=503)
    return FileResponse(indice, media_type="text/html", headers={"Cache-Control": "no-store"})

@router.get("/registro")
async def pagina_usuario() -> Response:
    """Sirve la vista de solicitud de acceso del frontend React."""
    return pagina_react()

@router.get("/inicio-sesion")
async def pagina_login() -> Response:
    """Sirve la vista de inicio de sesión del frontend React."""
    return pagina_react()

@router.get("/panel")
async def pagina_panel() -> Response:
    """Sirve el panel del usuario (llaves, aulas y fotos) del frontend React."""
    return pagina_react()

@router.get("/admin")
async def pagina_admin(request: Request) -> Response:
    """Sirve la vista de administración del frontend React."""
    if ADMIN_SOLO_LOCAL and not es_local(request):
        raise HTTPException(status_code=404, detail="No encontrado")
    return pagina_react()


