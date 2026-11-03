# Endpoints del Llavero Inteligente


Servidor por defecto: `http://localhost:8000` (PocketBase aparte en `:8090`).

### Páginas (HTML del frontend)

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/` | — | Redirige (307) a `/inicio-sesion` |
| GET | `/registro` | — | SPA: solicitud de acceso |
| GET | `/inicio-sesion` | — | SPA: login |
| GET | `/panel` | — | SPA: panel del usuario (la sesión la valida el frontend) |
| GET | `/admin` | — | SPA: administración (404 si `ADMIN_SOLO_LOCAL` y no es local) |

### Usuarios y sesión

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| POST | `/solicitar_acceso` | — | Crea una solicitud pendiente |
| POST | `/preparar_login` | — | Paso 1 del login: existe el usuario y qué métodos tiene |
| POST | `/login` | — | Login con usuario + PIN |
| POST | `/login_rostro` | — | Abre una espera de login por rostro |
| GET | `/login_rostro/{solicitud_id}` | — | Consulta la espera (entrega el token una vez) |
| DELETE | `/login_rostro/{solicitud_id}` | — | Cancela la espera |
| POST | `/acceso_codigo` | — | Autoriza un casillero por 30 s con usuario + PIN |
| POST | `/modo?m=` | token | Cambia entre `registro` y `reconocimiento` |

### Estado y fotos

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/estado` | token (opcional) | Modo, edad de la última foto, estado del usuario |
| GET | `/ultima_foto` | token | Último JPEG recibido de la placa |
| POST | `/guardar_foto` | token | Guarda el último frame como foto pendiente |
| POST | `/guardar_lote?cantidad=5` | token | Guarda una ráfaga de fotos pendientes |
| POST | `/subir_foto` | token | Sube una foto desde la computadora (multipart) |
| GET | `/mis_fotos` | token | Fotos aprobadas/pendientes propias |
| GET | `/foto/{archivo}` | token | Sirve una foto propia |
| DELETE | `/foto/{archivo}` | token | Borra una foto propia |

### Cámara / placa

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| POST | `/reconocimiento` | — | Recibe el JPEG de la ESP32-CAM |
| POST | `/retiro` | — | Marca un casillero en uso |
| POST | `/devolucion` | — | Marca un casillero disponible |
| GET | `/llaves` | — | Estado de todos los casilleros |

### Aulas y llaves (panel de usuario)

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/aulas` | token | Aulas con estado, préstamo y tags |
| POST | `/aulas/pedir` | token | Registra el retiro de una llave |
| POST | `/aulas/devolver` | token o admin | Marca la devolución |

### Administración

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| POST | `/admin/login` | — | Login del administrador |
| GET | `/admin/usuarios` | admin | Lista usuarios y cantidad de fotos |
| POST | `/admin/decidir` | admin | Aprueba o rechaza un usuario |
| DELETE | `/admin/usuario/{usuario}` | admin | Elimina usuario, fotos y sesiones |
| GET | `/admin/aulas` | admin | Aulas + historial de préstamos |
| POST | `/admin/aulas` | admin | Crea un aula |
| PATCH | `/admin/aulas/{aula_id}` | admin | Edita nombre/ubicación/activa/rfid |
| POST | `/admin/aulas/{aula_id}/rfid/{rfid}` | admin | Asigna tag legacy |
| DELETE | `/admin/aulas/{aula_id}/rfid` | admin | Quita tag legacy |
| POST | `/admin/aulas/{aula_id}/liberar` | admin | Fuerza la devolución |
| GET | `/admin/tags` | admin | Lista llaveros RFID |
| POST | `/admin/tags` | admin | Crea un llavero (UID + número de aula) |
| PATCH | `/admin/tags/{tag_id}` | admin | Edita un llavero |
| DELETE | `/admin/tags/{tag_id}` | admin | Borra un llavero |
| POST | `/admin/escaneo/iniciar` | admin | Pide escanear una tarjeta (30 s) |
| POST | `/admin/escaneo/cancelar` | admin | Cancela el escaneo |
| GET | `/admin/escaneo` | admin | Estado del escaneo |

### Dispensador (ESP32)

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/dispensador/reconocido` | — | Último rostro autorizado (saludo en el LCD) |
| GET | `/dispensador/solicitud` | — | Solicitud de llave vigente |
| POST | `/dispensador/solicitar` | — | Crea/reemplaza una solicitud |
| POST | `/dispensador/cancelar` | — | Cancela la solicitud |
| POST | `/dispensador/pin` | — | Valida el PIN tecleado |
| POST | `/dispensador/confirmar` | — | Eventos: encontrada / entregada / error / bloqueado |
| POST | `/dispensador/rostro/fallo?aula_id=` | — | Cuenta un fallo de rostro |
| POST | `/dispensador/rostro/ok?aula_id=&persona=` | — | Limpia los fallos de rostro |
| GET | `/dispensador/estado` | — | Estado completo para el panel de admin |
| GET | `/dispensador/llave/{numero_aula}` | — | Disponibilidad + UIDs de un aula |
| GET | `/dispensador/llave-por-uid/{uid}` | — | Aula a la que pertenece un UID |
| POST | `/dispensador/llave/evento` | — | Log de eventos del teclado |
| GET | `/dispensador/modo-escaneo` | — | ¿Debe escanear una tarjeta? |
| POST | `/dispensador/escaneo` | — | Envía el UID escaneado |

---

## Detalle

### Páginas

#### `GET /`
`307` → `/inicio-sesion`.

#### `GET /registro`, `GET /inicio-sesion`, `GET /panel`, `GET /admin`
Devuelven `frontend/dist/index.html`. Si falta el build: `503` con texto plano.
`/admin` responde `404` si `ADMIN_SOLO_LOCAL=true` y la petición no es local.

---

### Usuarios y sesión

#### `POST /solicitar_acceso`
```json
{ "usuario": "juan", "pin": "1234" }
```
- Usuario: 3–20 letras. PIN: 4–8 dígitos.
- `200` → `{ "ok": true, "usuario": "juan" }`
- `400` datos inválidos · `409` ya existe · `429` demasiadas pendientes · `503` PocketBase.

#### `POST /preparar_login`
```json
{ "usuario": "juan" }
```
`200` → `{ "usuario": "juan", "estado": "aprobado", "puede_rostro": true }`
`404` no existe.

#### `POST /login`
```json
{ "usuario": "juan", "pin": "1234" }
```
`200` → `{ "token": "...", "usuario": "juan", "estado": "aprobado" }`
`401` credenciales incorrectas.

#### `POST /login_rostro`
```json
{ "usuario": "juan" }
```
`200` → `{ "ok": true, "solicitud_id": "a1b2...", "espera_s": 90 }`
`404` no existe · `409` sin fotos · `429` ya hay una espera.

#### `GET /login_rostro/{solicitud_id}`
`200` → `{ "estado": "esperando|autorizado|expirado", "usuario": "juan", "aviso": null }`
Cuando se autoriza: `{ "estado": "autorizado", "token": "...", "usuario": "juan" }` (el token se entrega una sola vez).
`404` la espera no existe o venció.

#### `DELETE /login_rostro/{solicitud_id}`
`200` → `{ "ok": true }`

#### `POST /acceso_codigo`
```json
{ "usuario": "juan", "pin": "1234", "casillero_id": "C01" }
```
`200` → `{ "ok": true, "mensaje": "Código correcto..." }` (vale 30 s)
`401` credenciales · `403` cuenta no aprobada.

#### `POST /modo?m=reconocimiento`
`m`: `registro` o `reconocimiento`. Requiere `x-token`.
`200` → `{ "modo": "reconocimiento" }` · `400` modo inválido.

---

### Estado y fotos

#### `GET /estado`
Sin token devuelve lo global. Con `x-token` agrega datos del usuario.
```json
{ "modo": "reconocimiento", "edad_foto": 4, "estado_usuario": "aprobado",
  "ultimo": "ACCESO PERMITIDO: Juan (18:20:11)" }
```

#### `GET /ultima_foto`
JPEG (`image/jpeg`) o `404` si todavía no llegó ningún frame.

#### `POST /guardar_foto`
Sin cuerpo: usa el último frame recibido (<10 s).
`200` → `{ "ok": true, "archivo": "juan3.jpg", "estado": "pendiente" }`
`400` no hay foto reciente · `422` límite de fotos alcanzado.

#### `POST /guardar_lote?cantidad=5`
`cantidad` entre 1 y 10.
`200` → `{ "ok": true, "guardadas": ["juan4.jpg"], "mensaje": "1 foto(s) guardada(s)", "errores": [] }`
`422` si no se guardó ninguna.

#### `POST /subir_foto`
`multipart/form-data` con el campo `archivo` (JPEG, PNG o WebP, máx. 8 MB).
La imagen se endereza según el EXIF, se redimensiona y se guarda como JPEG pendiente
de verificación (el worker la aprueba sola si detecta un rostro válido).
`200` → `{ "ok": true, "archivo": "juan5.jpg", "estado": "pendiente" }`
`400` archivo vacío o inválido · `413` supera los 8 MB · `422` límite de fotos alcanzado.

#### `GET /mis_fotos`
`200` → `{ "fotos": [{ "archivo": "juan1.jpg", "estado": "ok" }], "avisos": [] }`

#### `GET /foto/{archivo}` / `DELETE /foto/{archivo}`
Solo fotos propias del usuario autenticado. `DELETE` → `{ "ok": true }`.

---

### Cámara / placa

#### `POST /reconocimiento`
Cuerpo: JPEG crudo (sin multipart). Cabecera `X-Casillero-Id`.
Respuestas:
```json
{ "status": "success", "modo": "reconocimiento", "autorizado": true,
  "persona": "Juan", "metodo": "rostro", "mensaje": "Bienvenido/a, Juan.",
  "distancia": 0.231 }
```
```json
{ "status": "success", "modo": "reconocimiento", "autorizado": false,
  "persona": "Desconocido", "mensaje": "Persona no registrada.",
  "requiere_pin": false }
```
- Modo registro: `{ "status": "success", "modo": "registro", "autorizado": false, "mensaje": "Modo registro" }`
- Sin fotos base: `{ "status": "error", "modo": "reconocimiento", "mensaje": "No hay fotos de referencia válidas en el sistema." }`
- Imagen chica/corrupta: `{ "status": "error", "mensaje": "Imagen muy pequeña o corrupta" }`

> Al autorizar, además se guarda el rostro para que el dispensador salude
> (`/dispensador/reconocido`) y se registra una foto de reconocimiento.

#### `POST /retiro`
```json
{ "casillero_id": "C01" }
```
`200` → `{ "status": "success", "casillero_id": "C01", "estado": "En uso", "persona": "Juan" }`

#### `POST /devolucion`
```json
{ "casillero_id": "C01" }
```
`200` → `{ "status": "success", "casillero_id": "C01", "estado": "Disponible" }`

#### `GET /llaves`
`200` → lista de `{ "casillero_id", "estado", "persona", "actualizado" }`.

---

### Aulas y llaves (panel de usuario)

#### `GET /aulas`
Requiere sesión aprobada.
`200` → lista de aulas:
```json
[{ "id": 1, "nombre": "Aula 1", "ubicacion": "Planta baja", "activa": 1,
   "rfid": "", "prestamo_id": null, "profesor": null, "actividad": null,
   "desde": null, "hasta": null, "registrado_por": null,
   "estado": "disponible", "tags": [] }]
```
`estado`: `disponible` · `ocupada` · `vencida` · `inactiva`.

#### `POST /aulas/pedir`
```json
{ "aula_id": 1, "profesor": "Juan", "actividad": "Matemática", "hasta": "18:30" }
```
`profesor` es opcional (default: el usuario). `hasta` es hora local `HH:MM`.
`200` → `{ "ok": true, "prestamo": { "id": 3, "aula_id": 1, ... } }`
`404` no existe · `409` deshabilitada o llave no devuelta · `400` datos/horario inválidos.

#### `POST /aulas/devolver`
```json
{ "aula_id": 1 }
```
Acepta `x-token` (solo quien retiró) o `x-admin`.
`200` → `{ "ok": true }` · `403` no es el dueño · `409` ya devuelta.

---

### Administración

#### `POST /admin/login`
```json
{ "clave": "admin123" }
```
`200` → `{ "token": "..." }` · `401` clave incorrecta.

#### `GET /admin/usuarios`
`200` → `{ "usuarios": [{ "usuario": "juan", "estado": "pendiente", "creado": "...", "fotos": 2 }] }`

#### `POST /admin/decidir`
```json
{ "usuario": "juan", "accion": "aprobar" }
```
`accion`: `aprobar` o `rechazar`.
`200` → `{ "ok": true, "usuario": "juan", "estado": "aprobado" }`
`400` acción inválida · `404` no existe.

#### `DELETE /admin/usuario/{usuario}`
Borra usuario, fotos, embeddings y sesiones. `200` → `{ "ok": true }`.

#### `GET /admin/aulas`
`200` → `{ "aulas": [ ...igual que /aulas... ], "historial": [ ... ] }`

#### `POST /admin/aulas`
```json
{ "nombre": "Aula 214", "ubicacion": "Primer piso" }
```
`200` → `{ "ok": true, "aula": { "id": 4, ... } }`

#### `PATCH /admin/aulas/{aula_id}`
Cualquier combinación de:
```json
{ "nombre": "Aula 214", "ubicacion": "Primer piso", "activa": true, "rfid": "CAA8EA81" }
```
`200` → `{ "ok": true, "aula": { ... } }` · `404` no existe.

#### `POST /admin/aulas/{aula_id}/rfid/{rfid}`
Tag legacy (texto, máx. 32). Rechaza un tag ya usado por otra aula.
`200` → `{ "ok": true, "aula": { ... } }` · `409` tag duplicado.

#### `DELETE /admin/aulas/{aula_id}/rfid`
`200` → `{ "ok": true, "aula": { ... } }`

#### `POST /admin/aulas/{aula_id}/liberar`
Fuerza la devolución del préstamo activo.
`200` → `{ "ok": true }` · `409` ya estaba devuelta.

#### `GET /admin/tags`
`200` → `[{ "id": "abc123...", "uid": "CAA8EA81", "numero_aula": "214" }]`

#### `POST /admin/tags`
```json
{ "uid": "CAA8EA81", "numero_aula": "214" }
```
El backend completa `nombre`, `llave_id` y `tipo` a partir del número de aula.
`200` → registro creado · `400` UID inválido o repetido.

#### `PATCH /admin/tags/{tag_id}`
```json
{ "uid": "CAA8EA81", "numero_aula": "215" }
```
`200` → registro actualizado.

#### `DELETE /admin/tags/{tag_id}`
`200` → `{ "ok": true }`

#### `POST /admin/escaneo/iniciar`
`200` → `{ "ok": true, "vence_en": 30 }`
El dispensador consulta `/dispensador/modo-escaneo` y manda el UID a `/dispensador/escaneo`.

#### `POST /admin/escaneo/cancelar`
`200` → `{ "ok": true }`

#### `GET /admin/escaneo`
`200` → `{ "activo": false, "uid": "CAA8EA81", "ya_registrado": false }`

---

### Dispensador

#### `GET /dispensador/reconocido`
Último rostro autorizado por la cámara (vigencia 30 s).
```json
{ "reconocido": true, "persona": "Juan", "seq": 7, "edad": 2 }
```
```json
{ "reconocido": false }
```
`seq` sube cuando hay un aviso nuevo (cambio de persona o pasaron 60 s), para que el
dispensador no repita el saludo.

#### `GET /dispensador/solicitud`
```json
{ "activa": true, "aula_id": 1, "aula_nombre": "Aula 1", "persona": "Juan",
  "rfid": "CAA8EA81", "rfids": ["CAA8EA81"], "requiere_pin": false,
  "intentos_rostro": 0 }
```
Sin solicitud: `{ "activa": false }`.

#### `POST /dispensador/solicitar`
```json
{ "aula_id": 1, "persona": "Juan", "requiere_pin": false }
```
`200` → `{ "ok": true, "aula_nombre": "Aula 1", "rfid": "CAA8EA81", "rfids": ["CAA8EA81"] }`
`200` con error: `{ "ok": false, "error": "Ese aula no tiene tag RFID asignado." }`

#### `POST /dispensador/cancelar`
`200` → `{ "ok": true }`

#### `POST /dispensador/pin`
```json
{ "aula_id": 1, "pin": "1234", "persona": "juan" }
```
`200` → `{ "ok": true, "persona": "juan" }` · `200` con `{ "ok": false, "error": "PIN incorrecto." }`

#### `POST /dispensador/confirmar`
```json
{ "evento": "entregada", "aula_id": 1, "persona": "Juan",
  "rfid": "CAA8EA81", "detalle": "llave retirada" }
```
`evento`: `encontrada` · `entregada` · `error` · `bloqueado`.
Al recibir `entregada`, si no había préstamo, lo registra a nombre de `persona`
con vencimiento a `PRESTAMO_DURACION_H` horas.
`200` → `{ "ok": true }`

#### `POST /dispensador/rostro/fallo?aula_id=1`
`200` → `{ "ok": true, "restantes": 4, "requiere_pin": false }`
A los 5 fallos: `requiere_pin: true` y bloqueo de 5 minutos.

#### `POST /dispensador/rostro/ok?aula_id=1&persona=Juan`
`200` → `{ "ok": true }`

#### `GET /dispensador/estado`
```json
{ "solicitud": { ... }, "ultimo_evento": { "evento": "entregada", "detalle": "", "ts": 0 },
  "aulas": [{ "id": 1, "nombre": "Aula 1", "tiene_rfid": true, ... }] }
```

#### `GET /dispensador/llave/{numero_aula}`
`numero_aula` se resuelve primero por **nombre** (`"214"` o `"Aula 214"`) y después por **id**.
```json
{ "ok": true, "disponible": true, "aula": "214", "aula_id": 4,
  "aula_nombre": "Aula 214", "uids": ["CAA8EA81"] }
```
```json
{ "ok": true, "disponible": false, "aula": "214", "aula_id": 4,
  "aula_nombre": "Aula 214", "motivo": "La llave no se encuentra disponible." }
```
```json
{ "ok": false, "disponible": false, "error": "Esa aula no existe." }
```
Otros errores: aula deshabilitada, sin llavero cargado, base no disponible.

#### `GET /dispensador/llave-por-uid/{uid}`
`200` → `{ "ok": true, "uid": "CAA8EA81", "aula": "214" }` · `{ "ok": false, "error": "Llavero desconocido." }`

#### `POST /dispensador/llave/evento`
```json
{ "numero_aula": "214", "evento": "entregada", "uid": "CAA8EA81", "detalle": "" }
```
`200` → `{ "ok": true }` (solo registra en el log).

#### `GET /dispensador/modo-escaneo`
`200` → `{ "activo": false }`

#### `POST /dispensador/escaneo`
```json
{ "uid": "CAA8EA81" }
```
`200` → `{ "ok": true, "uid": "CAA8EA81", "ya_registrado": false }`
`200` con error: `{ "ok": false, "error": "No hay un escaneo pedido." }`

---

## Verificación rápida (copiar y pegar)

```bash
BASE=http://localhost:8000

# 1) Servicios arriba
curl -s -o /dev/null -w "SPA %{http_code}\n"        $BASE/inicio-sesion
curl -s -o /dev/null -w "estado %{http_code}\n"     $BASE/estado
curl -s -o /dev/null -w "PocketBase %{http_code}\n" http://localhost:8090/api/health

# 2) Login de administrador (guarda el token)
ADMIN=$(curl -s -X POST $BASE/admin/login \
  -H 'Content-Type: application/json' -d '{"clave":"admin123"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
echo "admin token: ${ADMIN:0:8}..."

# 3) Aulas y llaveros
curl -s $BASE/admin/aulas -H "x-admin: $ADMIN"
curl -s $BASE/admin/tags   -H "x-admin: $ADMIN"

# 4) Estado del dispensador y último rostro
curl -s $BASE/dispensador/estado
curl -s $BASE/dispensador/reconocido

# 5) ¿Está disponible el aula 1? (id o nombre: 1, "Aula 1", "214"...)
curl -s $BASE/dispensador/llave/1

# 6) Simular que el dispensador entrega una llave (¡registra un préstamo!)
# curl -s -X POST $BASE/dispensador/confirmar -H 'Content-Type: application/json' \
#   -d '{"evento":"entregada","aula_id":1,"persona":"Prueba","detalle":"test"}'

# 7) Liberar el aula si quedó un préstamo de prueba
# curl -s -X POST $BASE/admin/aulas/1/liberar -H "x-admin: $ADMIN"

# 8) Subir una foto para el reconocimiento (token de un usuario aprobado)
# curl -s -X POST $BASE/subir_foto -H "x-token: $TOKEN" -F "archivo=@foto.jpg"
```

### Simular un rostro reconocido
No hay atajo por API: `/dispensador/reconocido` se llena solo cuando la ESP32-CAM manda
un JPEG a `/reconocimiento` y el rostro está autorizado. Para probar sin placa:

1. Poné una foto en `personas_autorizadas/` con el nombre de la persona como archivo
   (ej. `juan.jpg`; el nombre se deriva del archivo, sin dígitos).
2. Reiniciá el servidor (`./iniciar.sh --reiniciar`).
3. Enviá una foto de esa persona:
   ```bash
   curl -s -X POST $BASE/reconocimiento \
     -H 'Content-Type: image/jpeg' -H 'X-Casillero-Id: C01' \
     --data-binary @foto.jpg
   ```
4. Consultá `$BASE/dispensador/reconocido` (debe traer `persona` y `seq`).

### Flujo completo del dispensador (hardware)

1. Cámara reconoce → `POST /reconocimiento` → backend guarda el rostro.
2. Dispensador consulta `GET /dispensador/reconocido` → muestra `Bienvenido <persona>`.
3. Persona escribe el número de aula y `#`.
4. Dispensador consulta `GET /dispensador/llave/{numero}`.
5. Si `disponible: true`, gira, encuentra el tag y avisa:
   - `POST /dispensador/confirmar` con `evento: "encontrada"`
   - al retirar, `evento: "entregada"` → se registra el préstamo.

## Variables que afectan el comportamiento

| Variable | Default | Efecto |
|---|---|---|
| `RECONOCIDO_VIGENCIA_S` | 30 s | Cuánto vale un rostro para el dispensador |
| `RECONOCIDO_REPETIR_S` | 60 s | Cada cuánto se vuelve a avisar del mismo rostro |
| `PRESTAMO_DURACION_H` | 2 h | Vencimiento del préstamo entregado por el dispensador |
| `MAX_INTENTOS` | 5 | Fallos de rostro antes de pedir PIN |
| `CODIGO_VALIDO_S` | 30 s | Validez de `/acceso_codigo` |
| `LOGIN_ROSTRO_TIMEOUT_S` | 90 s | Validez de una espera de login por rostro |
