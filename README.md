# Llavero inteligente

Sistema FastAPI para control de casilleros de llaves con reconocimiento facial. La placa ESP32 envía imágenes periódicas a `/reconocimiento`; el servidor valida al usuario o PIN, actualiza `llaves.db` y muestra estado e historial por HTTP.

## Mapa del proyecto

- `main.py`: crea `app`, monta `/assets`, ejecuta el startup y registra los routers. Se mantiene el arranque `python -m uvicorn main:app --host 0.0.0.0 --port 8000`.
- `config.py`: variables de entorno, rutas de trabajo y constantes operativas.
- `logs.py`: helper `log(tag, texto)` con el mismo formato `[fecha] [TAG] texto`.
- `estado.py`: diccionarios y locks compartidos en memoria del proceso.
- `db.py`: persistencia SQLite de casilleros e historial.
- `pocketbase.py`: cliente PocketBase para usuarios y colecciones.
- `seguridad.py`: PIN, sesiones, bloqueo por intentos y cabeceras de autenticación.
- `reconocimiento.py`: embeddings DeepFace y comparación coseno.
- `fotos.py`: fotos aprobadas/pendientes, validación y worker en segundo plano.
- `schemas.py`: modelos Pydantic de las peticiones.
- `routers/`: endpoints agrupados por dominio: `placa.py`, `usuarios.py`, `paginas.py`, `admin.py`, `captura.py`.
- `frontend/`: aplicación React/Vite que sirve las vistas `/registro` y `/admin`.
- `src/` y `platformio.ini`: firmware ESP32-CAM.
- `scripts/smoke_test.py`: comprobación rápida sin servicios externos.
- `tests/`: pruebas de contrato y rutas.

## Arranque

### Linux

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
npm ci && npm run build --prefix frontend
ADMIN_CLAVE="una-clave-larga" PB_EMAIL="admin" PB_PASSWORD="admin" PB_URL="http://127.0.0.1:8090" \
  python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### Windows (PowerShell)

```powershell
pipenv install
npm ci; npm run build --prefix frontend
$env:ADMIN_CLAVE="una-clave-larga"; $env:PB_EMAIL="admin"; $env:PB_PASSWORD="admin"; $env:PB_URL="http://127.0.0.1:8090"
pipenv run python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

El proyecto usa **Pipenv** para gestionar dependencias; consulta `USO_PIPENV.md`. (Alternativa con pip/venv: `py -3.12 -m venv .venv`, `.\.venv\Scripts\Activate.ps1`, `pip install -r requirements.txt`.)

PocketBase debe estar corriendo aparte para registro/aprobación de usuarios.

## Variables de entorno

- `ADMIN_CLAVE`: contraseña del panel `/admin`; sin definir usa `cambiame-admin` y imprime advertencia.
- `PB_URL`: URL de PocketBase; por defecto `http://127.0.0.1:8090`.
- `PB_EMAIL` y `PB_PASSWORD`: superusuario de PocketBase.
- `ADMIN_SOLO_LOCAL` no se define por entorno en el código actual; está como `False` en `config.py`.

## Endpoints principales

Placa:

- `POST /reconocimiento` — envía `image/jpeg` crudo y cabecera `X-Casillero-Id`.
- `POST /retiro` — marca casillero en uso.
- `POST /devolucion` — marca casillero disponible.
- `GET /llaves` — lista estados.

Usuarios:

- `POST /solicitar_acceso`
- `POST /login`
- `POST /acceso_codigo`

Captura/frontend:

- `GET /registro`
- `GET /admin`
- `GET /estado`
- `POST /modo`
- `POST /guardar_foto`
- `GET /mis_fotos`
- `GET /ultima_foto`
- `GET/DELETE /foto/{archivo}`

Administración:

- `POST /admin/login`
- `GET /admin/usuarios`
- `POST /admin/decidir`
- `DELETE /admin/usuario/{usuario}`

## Comprobaciones

- `python -m py_compile ...` — sintaxis sin importar servicios.
- `python scripts/smoke_test.py` — corriendo con PocketBase caído debe dar 503 en `/login`; con PocketBase activo puede dar 401.
- `npm test --prefix frontend` — pruebas del cliente React.
- `npm run build --prefix frontend` — compila la interfaz que sirve FastAPI.
