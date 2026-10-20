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
    rfid: str | None = None

class PedidoDispensador(BaseModel):
    """Petición para dispensar la llave de un aula (la crea el frontend o la ESP32-CAM)."""
    aula_id: int
    persona: str = ""
    requiere_pin: bool = False

class PinDispensador(BaseModel):
    """Validación de PIN ingresado en el teclado del dispensador."""
    aula_id: int
    pin: str
    persona: str = ""

class EventoDispensador(BaseModel):
    """Evento reportado por el ESP32 dispensador."""
    evento: str                      # encontrada | entregada | error | bloqueado
    aula_id: int | None = None
    persona: str = ""
    rfid: str = ""
    detalle: str = ""


