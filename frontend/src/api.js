export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

// El servidor mantiene las sesiones en memoria; nunca persistimos los tokens en el navegador.
export async function api(path, { method = 'GET', body, token, adminToken, response = 'json', signal } = {}) {
  const headers = {}
  if (token) headers['x-token'] = token
  if (adminToken) headers['x-admin'] = adminToken
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const result = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
  if (!result.ok) {
    let detail
    try {
      const data = await result.json()
      detail = data.detail || data.mensaje
    } catch { /* Algunas respuestas no tienen cuerpo JSON. */ }
    throw new ApiError(typeof detail === 'string' ? detail : `Error HTTP ${result.status}`, result.status)
  }
  return response === 'blob' ? result.blob() : result.json()
}

// Subida de una foto como multipart (no se puede mandar como JSON).
export async function subirFoto(archivo, token) {
  const datos = new FormData()
  datos.append('archivo', archivo)
  const result = await fetch('/subir_foto', {
    method: 'POST',
    headers: token ? { 'x-token': token } : {},
    body: datos,
  })
  if (!result.ok) {
    let detail
    try {
      const data = await result.json()
      detail = data.detail || data.mensaje
    } catch { /* Algunas respuestas no tienen cuerpo JSON. */ }
    throw new ApiError(typeof detail === 'string' ? detail : `Error HTTP ${result.status}`, result.status)
  }
  return result.json()
}
