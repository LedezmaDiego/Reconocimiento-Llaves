# Cómo correr el proyecto completo

## Requisitos previos
- Python 3.12 + pip
- Node.js 18+ + npm
- Arduino IDE con soporte ESP32 (board manager: `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`)
- PocketBase ejecutable en `~/pocketbase/`

---

## 1. Primera vez (setup inicial)

### PocketBase
```bash
mkdir -p ~/pocketbase && cd ~/pocketbase
curl -sL -o pb.zip https://github.com/pocketbase/pocketbase/releases/download/v0.40.4/pocketbase_0.40.4_linux_amd64.zip
unzip -o pb.zip && rm pb.zip && chmod +x pocketbase
./pocketbase superuser upsert admin@llavero.local "LlaveroAdmin2026!"
```

### Backend (Python)
```bash
cd /home/etec/Reconocimiento-Llaves
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```
> `requirements.txt` está en UTF-16: si `pip` se queja de la codificación, instalalo con `pip install -r <(iconv -f UTF-16LE -t UTF-8 requirements.txt)`.

### Frontend (React + Vite)
```bash
cd /home/etec/Reconocimiento-Llaves/frontend
npm ci && npm run build
```

---

## 2. Cada vez que quieras usar el sistema

### Terminal 1 — PocketBase
```bash
cd ~/pocketbase
./pocketbase serve --http=127.0.0.1:8090
```
> Dashboard: http://127.0.0.1:8090/_/

---

### Terminal 2 — FastAPI (servidor principal)
```bash
cd /home/etec/Reconocimiento-Llaves
source venv/bin/activate
ADMIN_CLAVE="LlaveroPanel2026!" \
PB_EMAIL="admin@llavero.local" \
PB_PASSWORD="LlaveroAdmin2026!" \
PB_URL="http://127.0.0.1:8090" \
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```
> API + Web: http://10.56.2.9:8000

---

### Terminal 3 — Firmware (Arduino IDE)
1. Abrí **Arduino IDE**
2. **Archivo → Abrir** → `/home/etec/Reconocimiento-Llaves/llavero_esp32cam.ino`
3. **Herramientas**:
   - Placa: **AI Thinker ESP32-CAM** (o *ESP32-CAM*)
   - Partición: **Huge APP (3MB No OTA/1MB SPIFFS)**
   - PSRAM: **Enabled**
   - Flash Frequency: **80 MHz**
   - Upload Speed: **921600**
   - Puerto: **el COM/ttyUSB de tu placa**
4. **Ctrl+U** (subir)
5. **Ctrl+Shift+M** → Monitor serie a **115200 baudios**

> Si la placa no entra en boot: mantené **GPIO0 (botón IO0) pulsado**, pulsá **Reset (RST)**, soltá **IO0** cuando diga "Connecting...".

---

## 3. URLs de la web

| Ruta | Qué hace |
|------|----------|
| `http://10.56.2.9:8000/` | Redirige a `/inicio-sesion` |
| `/inicio-sesion` | Login en 2 pasos: usuario → (rostro o PIN) |
| `/registro` | Solicitud de acceso (usuario + PIN) |
| `/panel` | Aulas/llaves + captura facial + mis fotos (requiere login) |
| `/admin` | Administración: Usuarios + Aulas y llaves (requiere admin) |

**Credenciales admin:** `LlaveroPanel2026!`  
**Superusuario PocketBase:** `admin@llavero.local` / `LlaveroAdmin2026!`

---

## 4. Configuración de red (si cambia la IP)

Si tu PC cambia de IP (DHCP), actualizá en **dos lugares**:

1. **Firmware** (`llavero_esp32cam.ino`):
   ```cpp
   const char* serverUrl = "http://NUEVA_IP:8000/reconocimiento";
   ```

2. **Frontend proxy** (`frontend/vite.config.js`):
   ```js
   const backend = 'http://NUEVA_IP:8000'
   ```
   Luego: `cd frontend && npm run build`

> Para producción conviene IP fija en el router o mDNS (`http://llavero.local:8000`).

---

## 5. Comandos útiles

```bash
# Ver logs PocketBase
tail -f ~/pocketbase/pb.log

# Ver logs FastAPI (si corrió con nohup)
tail -f /tmp/opencode/uvicorn.log

# Recompilar frontend tras cambios
cd /home/etec/Reconocimiento-Llaves/frontend && npm run build

# Backup rápido de datos
cp /home/etec/Reconocimiento-Llaves/llaves.db ~/backup_llaves_$(date +%F).db
cp -r /home/etec/Reconocimiento-Llaves/personas_autorizadas ~/backup_fotos_$(date +%F)
```

---

## 6. Estructura mínima del proyecto

```
/home/etec/Reconocimiento-Llaves/
├── llavero_esp32cam.ino      # Firmware Arduino IDE
├── llaves.db                 # SQLite (aulas, préstamos, historial)
├── personas_autorizadas/     # Fotos aprobadas
├── fotos_pendientes/         # Fotos en revisión
├── .gitignore
├── requirements.txt
│
├── Backend (FastAPI)
│   ├── main.py, config.py, db.py, estado.py, fotos.py, logs.py
│   ├── pocketbase.py, reconocimiento.py, schemas.py, seguridad.py
│   └── routers/ (paginas.py, usuarios.py, captura.py, aulas.py, admin.py, placa.py)
│
└── Frontend (React + Vite)
    ├── frontend/ (src/pages: Registro.jsx, Login.jsx, Panel.jsx, Admin.jsx)
```

---

## 7. Solución de problemas rápidos

| Problema | Qué revisar |
|----------|-------------|
| Placa no conecta WiFi | SSID/pass exactos, red **2.4 GHz**, antena (jumper), alimentación 5V 2A |
| "Frontend sin compilar" | `cd frontend && npm run build` |
| PocketBase 503 | ¿Corre en 8090? ¿Credenciales correctas en env vars? |
| Cara no reconocida | Buena luz, de frente, varias fotos en `/panel` → "Guardar 5 fotos (ráfaga)" |
| Error HTTP 401 en /aulas | Sesión vencida → volvé a `/inicio-sesion` |
| Puerto 8000 ocupado | `pkill -f uvicorn` y volvé a arrancar |

---

**¡Listo!** Con las 3 terminales abiertas y la placa conectada, el sistema queda funcionando de punta a punta.