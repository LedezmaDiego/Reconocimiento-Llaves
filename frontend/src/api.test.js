import { afterEach, test } from 'node:test'
import assert from 'node:assert/strict'
import { api, ApiError } from './api.js'

const fetchOriginal = globalThis.fetch
afterEach(() => { globalThis.fetch = fetchOriginal })

test('envía JSON y token de usuario sin cambiar las rutas del servidor', async () => {
  globalThis.fetch = async (path, options) => {
    assert.equal(path, '/solicitar_acceso')
    assert.equal(options.method, 'POST')
    assert.equal(options.headers['x-token'], 'token-de-prueba')
    assert.equal(options.headers['Content-Type'], 'application/json')
    assert.deepEqual(JSON.parse(options.body), { usuario: 'ana', pin: '1234' })
    return new Response(JSON.stringify({ ok: true }), { status: 200 })
  }
  assert.deepEqual(await api('/solicitar_acceso', {
    method: 'POST', token: 'token-de-prueba', body: { usuario: 'ana', pin: '1234' },
  }), { ok: true })
})

test('envía x-admin y permite obtener imágenes como blob', async () => {
  globalThis.fetch = async (path, options) => {
    assert.equal(path, '/ultima_foto')
    assert.equal(options.headers['x-admin'], 'admin-de-prueba')
    return new Response(new Blob(['imagen'], { type: 'image/jpeg' }), { status: 200 })
  }
  const imagen = await api('/ultima_foto', { adminToken: 'admin-de-prueba', response: 'blob' })
  assert.equal(imagen.type, 'image/jpeg')
})

test('conserva el mensaje y código HTTP de errores de la API', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Sesión no válida' }), { status: 401 })
  await assert.rejects(api('/mis_fotos'), (error) =>
    error instanceof ApiError && error.status === 401 && error.message === 'Sesión no válida')
})
