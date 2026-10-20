# Llavero Inteligente - ETEC

Sistema de control de casilleros de llaves con reconocimiento facial y dispensador motorizado.

## Arranque rápido

```bash
./iniciar.sh
```

Eso levanta **PocketBase** (puerto 8090) + **FastAPI** (puerto 8000) y muestra las URLs.
Al final te dice dónde entrar.

### Opciones

| Comando | Qué hace |
|---------|----------|
| `./iniciar.sh` | Arranca PocketBase + FastAPI |
| `./iniciar.sh --build` | Recompila el frontend y arranca |
| `./iniciar.sh --parar` | Detiene todo |
| `./iniciar.sh --reiniciar` | Reinicia todo |

### Configuración

Copiá `.env.example` a `.env` y ajustá:

```bash
cp .env.example .env
```

| Variable | Default | Descripción |
|----------|---------|-------------|
| `ADMIN_CLAVE` | `admin123` | Contraseña del panel `/admin` |
| `PB_EMAIL` | `admin@llavero.local` | Superusuario de PocketBase |
| `PB_PASSWORD` | `LlaveroAdmin2026!` | Password del superusuario |
| `PB_URL` | `http://127.0.0.1:8090` | URL de PocketBase |

## Instalación desde cero

```bash
# 1. Backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Frontend
cd frontend && npm install && npm run build && cd ..

# 3. PocketBase (descargar el binario y ponerlo en la raíz)
# https://github.com/pocketbase/pocketbase/releases

# 4. Crear el superusuario de PocketBase (una sola vez)
./pocketbase admin create admin@llavero.local LlaveroAdmin2026!

# 5. Arrancar
./iniciar.sh
```

## URLs

| Ruta | Descripción |
|------|-------------|
| `http://localhost:8000/registro` | Registro / login de usuarios |
| `http://localhost:8000/admin` | Panel de administración |
| `http://localhost:8090/_/` | Admin de PocketBase |

Desde la red (ESP32-CAM, dispenser, otros equipos): usá la IP del servidor, por ejemplo
`http://10.56.16.134:8000`.

## Componentes

| Componente | Descripción |
|------------|-------------|
| **FastAPI** | Servidor principal (`main.py`) |
| **PocketBase** | Usuarios, PINs, aprobaciones y sesiones |
| **ESP32-CAM** | Cámara de reconocimiento (`llavero_esp32cam.ino`) |
| **ESP32 Dispensador** | Carrusel motorizado + RFID + LCD (`dispensador.ino`) |
| **Frontend React** | Vistas `/registro` y `/admin` |

## Estructura

```
├── iniciar.sh             # Script de arranque
├── .env.example           # Configuración de ejemplo
├── main.py                # Servidor FastAPI
├── config.py              # Constantes y variables
├── db.py                  # SQLite (casilleros, aulas, préstamos)
├── estado.py              # Estado en memoria
├── pocketbase.py          # Cliente PocketBase
├── reconocimiento.py      # DeepFace (embeddings)
├── fotos.py               # Gestión de fotos + worker
├── seguridad.py           # PIN, sesiones, tokens
├── schemas.py             # Modelos Pydantic
├── logs.py                # Logging
├── llavero_esp32cam.ino   # Firmware cámara (Arduino IDE)
├── dispensador.ino        # Firmware dispensador (Arduino IDE)
├── frontend/              # React + Vite
├── routers/               # Endpoints por dominio
├── scripts/smoke_test.py  # Comprobación rápida
├── requirements.txt
└── README.md
```

## Almacenamiento

| Dato | Dónde | Persiste |
|------|-------|-----------|
| Usuarios, PINs, aprobaciones | PocketBase (`pb_data/`) | Sí |
| Sesiones (tokens) | PocketBase, colección `sesiones` | Sí (1 año) |
| Fotos aprobadas | `personas_autorizadas/` | Sí |
| Fotos pendientes | `fotos_pendientes/` | Sí |
| Casilleros, aulas, préstamos | `llaves.db` (SQLite) | Sí |

## Firmware

### ESP32-CAM (`llavero_esp32cam.ino`)
Abrir en Arduino IDE con placa **AI Thinker ESP32-CAM** y PSRAM habilitada.

```cpp
const char* ssid         = "TU_WIFI";
const char* password     = "TU_PASSWORD";
const char* serverUrl    = "http://IP_DEL_SERVIDOR:8000/reconocimiento";
const char* CASILLERO_ID = "C01";
```

### ESP32 Dispensador (`dispensador.ino`)
Abrir en Arduino IDE con placa **ESP32 Dev Module** y estas librerías:
`MFRC522` (miguelbalboa), `Keypad`, `LiquidCrystal I2C` (fdebrabander), `ArduinoJson`.

```cpp
const char* WIFI_SSID      = "TU_WIFI";
const char* WIFI_PASSWORD  = "TU_PASSWORD";
const char* SERVER_URL     = "http://IP_DEL_SERVIDOR:8000";
const char* DISPENSADOR_ID = "D01";
```

## Comprobaciones

```bash
# Sintaxis (sin servicios)
source venv/bin/activate && python -m py_compile main.py

# Smoke test (no necesita PocketBase activo)
python scripts/smoke_test.py

# Tests del frontend
npm test --prefix frontend
```
