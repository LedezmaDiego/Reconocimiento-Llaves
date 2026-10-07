import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIRECTORIO_CARAS = os.path.join(BASE_DIR, "personas_autorizadas")
DIRECTORIO_PENDIENTES = os.path.join(BASE_DIR, "fotos_pendientes")
DB_PATH = os.path.join(BASE_DIR, "llaves.db")
FRONTEND_DIST = os.path.join(BASE_DIR, "frontend", "dist")

EXTENSIONES = (".jpg", ".jpeg", ".png")

# ---------------- Reconocimiento facial ----------------
MODELO = "VGG-Face"
DETECTOR = "yunet"
UMBRAL = 0.40
EXIGIR_ROSTRO = True
VENTANA_RETIRO_S = 60

# ---------------- Administración ----------------
# Contraseña del panel de administración. Definila antes de arrancar:
#   PowerShell:  $env:ADMIN_CLAVE="tu-clave-larga"
CLAVE_ADMIN = os.environ.get("ADMIN_CLAVE", "cambiame-admin")
ADMIN_SOLO_LOCAL = False    # True = el panel /admin solo se abre desde esta misma PC
ADMIN_SESION_S = 1800
MAX_PENDIENTES = 20         # tope de solicitudes sin resolver (evita spam)

# ---------------- PocketBase (guarda los usuarios) ----------------
# El servidor entra como superusuario de PocketBase. Definí estas variables:
#   PB_EMAIL y PB_PASSWORD = el superusuario que creaste en PocketBase
PB_URL = os.environ.get("PB_URL", "http://127.0.0.1:8090")
PB_EMAIL = os.environ.get("PB_EMAIL", "")
PB_PASSWORD = os.environ.get("PB_PASSWORD", "")
COLECCION = "personal"

# ---------------- Usuarios ----------------
MAX_FOTOS_POR_USUARIO = 15
REGISTRO_TIMEOUT_S = 120
SESION_S = 1800
CODIGO_VALIDO_S = 30
MAX_INTENTOS = 5
BLOQUEO_S = 60
CASILLERO_DEFECTO = "C01"
RESERVADOS = {"admin", "administrador", "root"}

# ---------------- Constantes operativas ----------------
PB_TIMEOUT_S = 5
CACHE_ESTADO_S = 2
WORKER_PENDIENTES_ESPERA_S = 1
FOTO_RECIENTE_S = 10
PBKDF2_ITERACIONES = 100_000
LONGITUD_ERROR_BREVE = 80
LONGITUD_ERROR_PB = 100
LONGITUD_TEXTO_COLECCION = 200
DISTANCIA_DESCONOCIDA = 999.0
MIN_BYTES_IMAGEN = 1000

