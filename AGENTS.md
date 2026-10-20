# AGENTS.md — Llavero Inteligente

## Componentes
- `backend/main.py`: servidor FastAPI (puerto 8000). Sirve la API y el frontend React compilado en `frontend/dist/` (`/registro`, `/admin`, `/assets`). Todo el código Python vive en `backend/`.
- `firmware/llavero_esp32cam.ino`: firmware ESP32-CAM (reconocimiento facial).
- `firmware/dispensador.ino`: firmware ESP32 dispensador (carrusel motor + RFID RC522 + LCD I2C + teclado 4x4 + LED).
- Ambos son sketches **Arduino IDE** (no PlatformIO). Librerías Arduino: `MFRC522` (miguelbalboa), `Keypad`, `LiquidCrystal I2C` (fdebrabander), `ArduinoJson`.

## Arranque (canonical)
```
./iniciar.sh              # levanta PocketBase (8090) + FastAPI (8000)
./iniciar.sh --build      # recompila el frontend antes de arrancar
./iniciar.sh --parar      # detiene procesos
./iniciar.sh --reiniciar
```
`iniciar.sh` espera:
- Entorno virtual en `venv/` (no `.venv`, no Pipenv):
  ```
  python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
  ```
- `requirements.txt` está en **UTF-16 LE con BOM**: `pip install -r requirements.txt` puede fallar por la codificación.
- Ejecutable `pocketbase` en la raíz del repo (no está versionado): descargar de https://github.com/pocketbase/pocketbase/releases.

## Variables de entorno
Copiar `.env.example` a `.env` y ajustar. `iniciar.sh` lee `.env` si existe.
```
ADMIN_CLAVE=...      # contraseña /admin (default inseguro: admin123)
PB_EMAIL=...         # superusuario PocketBase
PB_PASSWORD=...
PB_URL=http://127.0.0.1:8090
```

## Startup del servidor
Al iniciar `backend/main.py` crea las colecciones privadas `personal` y `sesiones` en PocketBase, crea `personas_autorizadas/` y `fotos_pendientes/`, y arranca un hilo de verificación de fotos. Si PocketBase no responde, el servidor sigue arriba pero las operaciones de usuarios/admin lo necesitan.

## Firmware
- `firmware/llavero_esp32cam.ino` tiene Wi-Fi, IP/URL del servidor e ID del casillero: ajustar a la red de destino **sin copiar credenciales en la documentación**.
- La placa envía JPEG sin envoltorio a `/reconocimiento` con cabecera `X-Casillero-Id`; la respuesta usa `"modo"` y `"autorizado"` — conservar ese formato al tocar la API.
- Por ahora solo informa autorización por puerto serie: **no** llama `/retiro` ni `/devolucion`, ni acciona cerradura.
- `firmware/dispensador.ino`: pines GPIO fijos (GPIO 34-39 son entrada only). No cambiar sin revisar la tabla de conexiones.

## Frontend
- `/panel` (usuario) **solo muestra llaves de aulas**: la sección de cámara y fotos ("Registrar mi cara" / "Mis fotos") está eliminada del panel. Los endpoints `/modo`, `/guardar_foto`, `/guardar_lote`, `/mis_fotos` y `/ultima_foto` siguen en el backend pero ya no tienen UI.
- Las sesiones (usuario y admin) se persisten en `localStorage` (`frontend/src/sesion.js`), así sobreviven recargas. Si un token restaurado venció (401), la app lo descarta y pide login de nuevo.
- Tras cambios en `frontend/src/`, rebuild obligatorio: `cd frontend && npm run build` (el backend sirve `frontend/dist/`).
- Tests del frontend: `cd frontend && npm test` (`node --test src/*.test.js`).

## Almacenamiento
- PocketBase: usuarios, hashes de PIN, aprobaciones y sesiones (colección `sesiones`, caché en memoria en `backend/seguridad.py`).
- `llaves.db` (SQLite): estados, historial, aulas y préstamos.
- `personas_autorizadas/` (fotos aprobadas) y `fotos_pendientes/` (en revisión).
- Modo, acceso por código, última foto y caché de embeddings viven **en memoria del proceso** (no se comparten entre workers).

## Pruebas / verificación
No hay suite automática ni lint.
```
python -m py_compile backend/main.py        # solo sintaxis, sin servicios
python backend/scripts/smoke_test.py        # rutas rápidas, no necesita PocketBase
```
La integración completa requiere PocketBase y una ESP32-CAM accesible.

## Cuidados
- No sobrescribir, restaurar ni incluir por accidente cambios en `llaves.db`, `pb_data/*.db` ni `pws.txt`.
- No exponer fotos reales de rostros ni contraseñas.
