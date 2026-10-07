import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

function notificar(titulo, texto) {
  try {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification(titulo, { body: texto })
    }
  } catch { /* La notificación del navegador es opcional. */ }
}

function Foto({ archivo, estado, token, onDelete }) {
  const [url, setUrl] = useState(null)
  useEffect(() => {
    let activo = true
    let imagen
    api(`/foto/${encodeURIComponent(archivo)}`, { token, response: 'blob' })
      .then((blob) => {
        imagen = URL.createObjectURL(blob)
        if (activo) setUrl(imagen)
        else URL.revokeObjectURL(imagen)
      })
      .catch(() => {})
    return () => {
      activo = false
      if (imagen) URL.revokeObjectURL(imagen)
    }
  }, [archivo, token])

  return (
    <div className="item">
      {url ? <img src={url} alt={`Foto ${archivo}`} /> : <div className="foto-vacia">Cargando foto…</div>}
      <div className={estado === 'pendiente' ? 'pend' : ''}>
        {archivo}{estado === 'pendiente' ? ' (verificando…)' : ''}
      </div>
      <button className="rojo chico" onClick={() => onDelete(archivo)}>Borrar</button>
    </div>
  )
}

export function Registro() {
  const [sesion, setSesion] = useState(null)
  const [estado, setEstado] = useState(null)
  const [aviso, setAviso] = useState(null)
  const [registro, setRegistro] = useState({ usuario: '', pin: '', confirmar: '' })
  const [login, setLogin] = useState({ usuario: '', pin: '' })
  const [codigo, setCodigo] = useState({ usuario: '', pin: '' })
  const [capturando, setCapturando] = useState(false)
  const [preview, setPreview] = useState(null)
  const previewUrl = useRef(null)
  const estadoAnterior = useRef(null)
  const [fotos, setFotos] = useState([])
  const [mensajeFoto, setMensajeFoto] = useState('')
  const [refrescarFotos, setRefrescarFotos] = useState(0)

  function cerrar(expirada = false) {
    setCapturando(false)
    setSesion(null)
    setEstado(null)
    setFotos([])
    if (previewUrl.current) URL.revokeObjectURL(previewUrl.current)
    previewUrl.current = null
    setPreview(null)
    estadoAnterior.current = null
    document.title = 'Llavero ETEC'
    setAviso(expirada ? { texto: 'Tu sesión venció. Volvé a entrar.', tipo: 'err' } : null)
  }

  useEffect(() => {
    if (!sesion) return
    let activo = true
    let timer
    async function consultar() {
      try {
        const datos = await api('/estado', { token: sesion.token })
        if (!activo) return
        if (!datos.estado_usuario) { cerrar(true); return }
        if (estadoAnterior.current === 'pendiente' && datos.estado_usuario === 'aprobado') {
          setAviso({ texto: '¡Solicitud aprobada! Ya podés registrar tu cara.', tipo: 'ok' })
          notificar('¡Solicitud aprobada!', 'Ya podés registrar tu cara.')
        }
        estadoAnterior.current = datos.estado_usuario
        setEstado(datos)
      } catch (error) {
        if (activo && error.status === 401) { cerrar(true); return }
      }
      if (activo) timer = setTimeout(consultar, 2000)
    }
    consultar()
    return () => { activo = false; clearTimeout(timer) }
  }, [sesion?.token])

  useEffect(() => {
    if (estado?.estado_usuario !== 'aprobado' || !sesion) return
    let activo = true
    let timer
    async function consultar() {
      try {
        const datos = await api('/mis_fotos', { token: sesion.token })
        if (!activo) return
        setFotos(datos.fotos)
        if (datos.avisos?.length) setMensajeFoto(`Foto rechazada: ${datos.avisos.join(' | ')}`)
        timer = setTimeout(consultar, datos.fotos.some((f) => f.estado === 'pendiente') ? 2000 : 6000)
      } catch (error) {
        if (activo && error.status === 401) cerrar(true)
        else if (activo) timer = setTimeout(consultar, 6000)
      }
    }
    consultar()
    return () => { activo = false; clearTimeout(timer) }
  }, [sesion?.token, estado?.estado_usuario, refrescarFotos])

  useEffect(() => {
    if (!capturando || !sesion) return
    let activo = true
    let timer
    const controller = new AbortController()
    async function siguienteFoto() {
      try {
        const foto = await api(`/ultima_foto?t=${Date.now()}`, {
          token: sesion.token, response: 'blob', signal: controller.signal,
        })
        if (activo) {
          const url = URL.createObjectURL(foto)
          if (previewUrl.current) URL.revokeObjectURL(previewUrl.current)
          previewUrl.current = url
          setPreview(url)
        }
      } catch (error) {
        if (activo && error.status === 401) { cerrar(true); return }
      }
      if (activo) timer = setTimeout(siguienteFoto, 400)
    }
    siguienteFoto()
    const renovar = setInterval(() => api('/modo?m=registro', { method: 'POST', token: sesion.token }).catch(() => {}), 30000)
    return () => { activo = false; controller.abort(); clearTimeout(timer); clearInterval(renovar) }
  }, [capturando, sesion?.token])

  useEffect(() => () => { if (previewUrl.current) URL.revokeObjectURL(previewUrl.current) }, [])

  async function solicitar(evento) {
    evento.preventDefault()
    if (registro.pin !== registro.confirmar) {
      setAviso({ texto: 'Los códigos personales no coinciden.', tipo: 'err' }); return
    }
    try {
      const datos = await api('/solicitar_acceso', {
        method: 'POST', body: { usuario: registro.usuario, pin: registro.pin },
      })
      setAviso({ texto: `Solicitud enviada. Entrá con "${datos.usuario}" para ver cuándo la aprueban.`, tipo: 'ok' })
      setLogin((actual) => ({ ...actual, usuario: datos.usuario }))
      setRegistro({ usuario: registro.usuario, pin: '', confirmar: '' })
    } catch (error) { setAviso({ texto: error.message, tipo: 'err' }) }
  }

  async function entrar(evento) {
    evento.preventDefault()
    try {
      const datos = await api('/login', { method: 'POST', body: login })
      estadoAnterior.current = datos.estado
      setSesion({ token: datos.token, usuario: datos.usuario })
      setEstado({ estado_usuario: datos.estado })
      setAviso(null)
      setLogin((actual) => ({ ...actual, pin: '' }))
      try {
        if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission()
      } catch { /* La sesión no depende de permisos de notificación. */ }
    } catch (error) { setAviso({ texto: error.message, tipo: 'err' }) }
  }

  async function abrirConCodigo(evento) {
    evento.preventDefault()
    try {
      const datos = await api('/acceso_codigo', {
        method: 'POST', body: { usuario: codigo.usuario, pin: codigo.pin, casillero_id: 'C01' },
      })
      setAviso({ texto: datos.mensaje, tipo: 'ok' })
      setCodigo((actual) => ({ ...actual, pin: '' }))
    } catch (error) { setAviso({ texto: error.message, tipo: 'err' }) }
  }

  async function salir() {
    if (capturando) {
      try { await api('/modo?m=reconocimiento', { method: 'POST', token: sesion.token }) } catch { /* El modo caduca en el servidor. */ }
    }
    cerrar()
  }

  async function cambiarCaptura() {
    try {
      await api(`/modo?m=${capturando ? 'reconocimiento' : 'registro'}`, { method: 'POST', token: sesion.token })
      setCapturando(!capturando)
    } catch (error) { setAviso({ texto: error.message, tipo: 'err' }) }
  }

  async function guardar() {
    setMensajeFoto('Guardando…')
    try {
      const datos = await api('/guardar_foto', { method: 'POST', token: sesion.token })
      setMensajeFoto(`Guardada: ${datos.archivo} (verificando la cara en segundo plano…)`)
      setRefrescarFotos((valor) => valor + 1)
    } catch (error) { setMensajeFoto(`Error: ${error.message}`) }
  }

  async function borrar(archivo) {
    if (!window.confirm(`¿Borrar ${archivo}?`)) return
    try {
      await api(`/foto/${encodeURIComponent(archivo)}`, { method: 'DELETE', token: sesion.token })
      setRefrescarFotos((valor) => valor + 1)
    } catch (error) { setMensajeFoto(`Error: ${error.message}`) }
  }

  return (
    <main>
      <h1>Llavero Inteligente</h1>
      <p className="sub">Acceso al casillero de llaves con reconocimiento facial.</p>
      {aviso && <div role="status" className={`aviso ${aviso.tipo}`}>{aviso.texto}</div>}

      {!sesion ? <>
        <section className="card">
          <h2>Solicitar acceso</h2>
          <p className="mut">El administrador revisa tu solicitud. Cuando la apruebe vas a poder registrar tu cara.</p>
          <form onSubmit={solicitar}>
            <label>Usuario (solo letras)<input value={registro.usuario} onChange={(e) => setRegistro({ ...registro, usuario: e.target.value })} autoCapitalize="none" required /></label>
            <label>Código personal (4 a 8 números)<input type="password" inputMode="numeric" value={registro.pin} onChange={(e) => setRegistro({ ...registro, pin: e.target.value })} required /></label>
            <label>Repetir código<input type="password" inputMode="numeric" value={registro.confirmar} onChange={(e) => setRegistro({ ...registro, confirmar: e.target.value })} required /></label>
            <button>Enviar solicitud</button>
          </form>
        </section>
        <section className="card">
          <h2>Ya tengo usuario</h2>
          <form onSubmit={entrar}>
            <label>Usuario<input value={login.usuario} onChange={(e) => setLogin({ ...login, usuario: e.target.value })} autoCapitalize="none" required /></label>
            <label>Código personal<input type="password" inputMode="numeric" value={login.pin} onChange={(e) => setLogin({ ...login, pin: e.target.value })} required /></label>
            <button>Entrar</button>
          </form>
        </section>
        <section className="card">
          <h2>Si falla el reconocimiento facial</h2>
          <form onSubmit={abrirConCodigo}>
            <label>Usuario<input value={codigo.usuario} onChange={(e) => setCodigo({ ...codigo, usuario: e.target.value })} autoCapitalize="none" required /></label>
            <label>Código personal<input type="password" inputMode="numeric" value={codigo.pin} onChange={(e) => setCodigo({ ...codigo, pin: e.target.value })} required /></label>
            <button className="ghost">Abrir con código</button>
          </form>
        </section>
      </> : <>
        <div className="barra"><span>Hola, <strong>{sesion.usuario}</strong></span><button className="ghost chico" onClick={salir}>Salir</button></div>
        {estado?.estado_usuario === 'pendiente' && <section className="card"><h2>Solicitud en revisión <span className="badge b-pendiente">Pendiente</span></h2><p>Esperando la aprobación del administrador. Esta página se actualiza sola.</p></section>}
        {estado?.estado_usuario === 'rechazado' && <section className="card"><h2>Solicitud rechazada <span className="badge b-rechazado">Rechazada</span></h2><p>Hablá con el administrador si creés que es un error.</p></section>}
        {estado?.estado_usuario === 'aprobado' && <>
          <section className="card">
            <h2>Registrar mi cara</h2>
            <div className="mut">Modo: <strong>{estado.modo === 'registro' ? 'REGISTRO' : 'RECONOCIMIENTO'}</strong> · {estado.edad_foto == null ? 'la placa todavía no envió fotos' : `última foto hace ${estado.edad_foto} s`}</div>
            <div className="mut">Último resultado: <strong>{estado.ultimo || '—'}</strong></div>
            <button onClick={cambiarCaptura} className="separado">{capturando ? 'Terminar captura' : 'Iniciar captura'}</button>
            {preview ? <img className="live" src={preview} alt="Vista de la cámara" /> : <div className="live placeholder">Esperando una foto de la placa…</div>}
            <p className="mut">Mirá de frente, con buena luz, y guardá varias fotos cambiando un poco el ángulo.</p>
            <button className="ok" onClick={guardar}>Guardar foto</button>
            <p role="status" className="mut">{mensajeFoto}</p>
          </section>
          <section className="card"><h2>Mis fotos</h2><div className="grid">{fotos.length ? fotos.map((foto) => <Foto key={foto.archivo} {...foto} token={sesion.token} onDelete={borrar} />) : <p className="mut">Todavía no tenés fotos.</p>}</div></section>
        </>}
      </>}
    </main>
  )
}
