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


