// Persistencia de sesiones en localStorage.
// El servidor sigue siendo la fuente de verdad: si un token restaurado ya
// venció, la API responde 401 y la app lo descarta y vuelve a pedir login.

const CLAVE_SESION = 'llavero_sesion'
const CLAVE_SESION_ADMIN = 'llavero_sesion_admin'

function guardar(clave, valor) {
  try { localStorage.setItem(clave, valor) } catch { /* storage no disponible (modo privado) */ }
}

function leer(clave) {
  try { return localStorage.getItem(clave) } catch { return null }
}

function borrar(clave) {
  try { localStorage.removeItem(clave) } catch { /* storage no disponible */ }
}

export function guardarSesion(datos) {
  guardar(CLAVE_SESION, JSON.stringify(datos))
}

export function leerSesion() {
  const crudo = leer(CLAVE_SESION)
  if (!crudo) return null
  try {
    const datos = JSON.parse(crudo)
    return datos && datos.token ? datos : null
  } catch { return null }
}

export function borrarSesion() {
  borrar(CLAVE_SESION)
}

export function guardarSesionAdmin(token) {
  guardar(CLAVE_SESION_ADMIN, token)
}

export function leerSesionAdmin() {
  return leer(CLAVE_SESION_ADMIN)
}

export function borrarSesionAdmin() {
  borrar(CLAVE_SESION_ADMIN)
}
