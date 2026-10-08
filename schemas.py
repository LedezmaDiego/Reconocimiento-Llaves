from pydantic import BaseModel

from config import CASILLERO_DEFECTO

class SolicitudAcceso(BaseModel):
    usuario: str
    pin: str

class LoginDatos(BaseModel):
    usuario: str
    pin: str

class AccesoCodigo(BaseModel):
    usuario: str
    pin: str
    casillero_id: str = CASILLERO_DEFECTO

class AdminLogin(BaseModel):
    clave: str

class Decision(BaseModel):
    usuario: str
    accion: str

class EventoCasillero(BaseModel):
    casillero_id: str

class UsuarioSimple(BaseModel):
    usuario: str

class PedidoLlave(BaseModel):
    aula_id: int
    profesor: str = ""
    actividad: str
    hasta: str    # hora local en formato "HH:MM"

class DevolucionLlave(BaseModel):
    aula_id: int

class AulaNueva(BaseModel):
    nombre: str
    ubicacion: str = ""

class AulaEdicion(BaseModel):
    nombre: str | None = None
    ubicacion: str | None = None
    activa: bool | None = None


