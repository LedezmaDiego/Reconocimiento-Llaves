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

const ETIQUETA_ESTADO = {
  disponible: { texto: 'Disponible', clase: 'b-aprobado' },
  ocupada: { texto: 'Ocupada', clase: 'b-ocupada' },
  vencida: { texto: 'Sin devolver', clase: 'b-gris' },
  inactiva: { texto: 'Deshabilitada', clase: 'b-gris' },
}

function Aula({ aula, onPedir, onDevolver, esMio }) {
  const etiqueta = ETIQUETA_ESTADO[aula.estado] || ETIQUETA_ESTADO.inactiva
  const libre = aula.estado === 'disponible'
  return (
    <div className={`aula${libre ? '' : ' aula-ocupada'}`}>
      <div className="fila-aula">
        <div>
          <strong>{aula.nombre}</strong> <span className={`badge ${etiqueta.clase}`}>{etiqueta.texto}</span>
          {aula.ubicacion && <div className="mut">{aula.ubicacion}</div>}
        </div>
        {libre && aula.activa && <button className="ok chico" onClick={() => onPedir(aula)}>Pedir llave</button>}
        {!libre && esMio && <button className="ghost chico" onClick={() => onDevolver(aula)}>Devolver</button>}
      </div>
      {!libre && aula.profesor && <div className="mut">
        A nombre de <strong>{aula.profesor}</strong> · {aula.actividad} · hasta las {aula.hasta.slice(11, 16)}
        {aula.desde && <> · tomada el {aula.desde.slice(0, 16)}</>}
      </div>}
    </div>
  )
}

function FormPedido({ aula, usuario, onCerrar, onGuardado }) {
  const [datos, setDatos] = useState({ profesor: usuario, actividad: '', hasta: '' })
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)

  async function pedir(evento) {
    evento.preventDefault()
    setEnviando(true)
    setError('')
    try {
      await api('/aulas/pedir', { method: 'POST', body: { aula_id: aula.id, ...datos } })
      onGuardado(aula.nombre)
    } catch (e) { setError(e.message); setEnviando(false) }
  }

  return (
    <div className="modal-fondo" onClick={onCerrar}>
      <div className="modal card" onClick={(e) => e.stopPropagation()}>
        <h2>Pedir llave: {aula.nombre}</h2>
        <form onSubmit={pedir}>
          <label>Profesor a cargo<input value={datos.profesor} onChange={(e) => setDatos({ ...datos, profesor: e.target.value })} required /></label>
          <label>Actividad / materia<input value={datos.actividad} onChange={(e) => setDatos({ ...datos, actividad: e.target.value })} required /></label>
          <label>Hasta qué hora<input type="time" value={datos.hasta} onChange={(e) => setDatos({ ...datos, hasta: e.target.value })} required /></label>
          {error && <p className="mut" role="alert">{error}</p>}
          <div className="acciones">
            <button className="ok" disabled={enviando}>{enviando ? 'Guardando…' : 'Confirmar retiro'}</button>
            <button type="button" className="ghost" onClick={onCerrar}>Cancelar</button>
          </div>
        </form>
      </div>
    </div>
  )
}

export function Panel({ sesion, onSalir }) {
  const [estado, setEstado] = useState(null)
  const [aviso, setAviso] = useState(null)
  const [mensajeFoto, setMensajeFoto] = useState('')
  const [capturando, setCapturando] = useState(false)
  const [preview, setPreview] = useState(null)
  const [guardandoLote, setGuardandoLote] = useState(false)
  const previewUrl = useRef(null)
  const estadoAnterior = useRef(null)
  const [fotos, setFotos] = useState([])
  const [refrescarFotos, setRefrescarFotos] = useState(0)
  const [aulas, setAulas] = useState([])
  const [mensajeAulas, setMensajeAulas] = useState('')
  const [pedido, setPedido] = useState(null)

  // Una sola salida que apaga también el modo registro de la placa.
  async function salir() {
    if (capturando) {
      try { await api('/modo?m=reconocimiento', { method: 'POST', token: sesion.token }) } catch { /* El modo caduca en el servidor. */ }
    }
    onSalir()
  }

  useEffect(() => {
    let activo = true
    let timer
    async function consultar() {
      try {
        const datos = await api('/estado', { token: sesion.token })
        if (!activo) return
        if (!datos.estado_usuario) { onSalir(); return }
        if (estadoAnterior.current === 'pendiente' && datos.estado_usuario === 'aprobado') {
          setAviso({ texto: '¡Solicitud aprobada! Ya podés registrar tu cara.', tipo: 'ok' })
          notificar('¡Solicitud aprobada!', 'Ya podés registrar tu cara.')
        }
        estadoAnterior.current = datos.estado_usuario
        setEstado(datos)
      } catch (error) {
        if (activo && error.status === 401) { onSalir(); return }
      }
      if (activo) timer = setTimeout(consultar, 2000)
    }
    consultar()
    return () => { activo = false; clearTimeout(timer) }
  }, [sesion.token])

  useEffect(() => {
    if (estado?.estado_usuario !== 'aprobado') return
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
        if (activo && error.status === 401) salir()
        else if (activo) timer = setTimeout(consultar, 6000)
      }
    }
    consultar()
    return () => { activo = false; clearTimeout(timer) }
  }, [sesion.token, estado?.estado_usuario, refrescarFotos])

  useEffect(() => {
    if (estado?.estado_usuario !== 'aprobado') return
    let activo = true
    let timer
    async function consultar() {
      try {
        const datos = await api('/aulas', { token: sesion.token })
        if (!activo) return
        setAulas(datos)
        timer = setTimeout(consultar, 5000)
      } catch (error) {
        if (activo && error.status === 401) salir()
        else if (activo) timer = setTimeout(consultar, 8000)
      }
    }
    consultar()
    return () => { activo = false; clearTimeout(timer) }
  }, [sesion.token, estado?.estado_usuario])

  useEffect(() => {
    if (!capturando) return
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
        if (activo && error.status === 401) { salir(); return }
      }
      if (activo) timer = setTimeout(siguienteFoto, 400)
    }
    siguienteFoto()
    const renovar = setInterval(() => api('/modo?m=registro', { method: 'POST', token: sesion.token }).catch(() => {}), 30000)
    return () => { activo = false; controller.abort(); clearTimeout(timer); clearInterval(renovar) }
  }, [capturando, sesion.token])

  useEffect(() => () => { if (previewUrl.current) URL.revokeObjectURL(previewUrl.current) }, [])

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

  async function guardarLote() {
    setGuardandoLote(true)
    setMensajeFoto('Capturando 5 fotos… no te muevas mucho.')
    try {
      const datos = await api('/guardar_lote?cantidad=5', { method: 'POST', token: sesion.token })
      setMensajeFoto(`${datos.mensaje}: ${datos.guardadas.join(', ')} (verificando en segundo plano…)`)
      setRefrescarFotos((valor) => valor + 1)
    } catch (error) { setMensajeFoto(`Error: ${error.message}`) }
    finally { setGuardandoLote(false) }
  }

  async function borrar(archivo) {
    if (!window.confirm(`¿Borrar ${archivo}?`)) return
    try {
      await api(`/foto/${encodeURIComponent(archivo)}`, { method: 'DELETE', token: sesion.token })
      setRefrescarFotos((valor) => valor + 1)
    } catch (error) { setMensajeFoto(`Error: ${error.message}`) }
  }

  async function devolver(aula) {
    if (!window.confirm(`¿Devolver la llave de ${aula.nombre}?`)) return
    try {
      await api('/aulas/devolver', { method: 'POST', token: sesion.token, body: { aula_id: aula.id } })
      setMensajeAulas(`Llave devuelta: ${aula.nombre}`)
    } catch (error) { setMensajeAulas(`Error: ${error.message}`) }
  }

  function pedidoGuardado(nombre) {
    setPedido(null)
    setMensajeAulas(`Llave de ${nombre} registrada.`)
  }

  const aprobado = estado?.estado_usuario === 'aprobado'
  const ahora = new Date()
  const hoy = ahora.toISOString().slice(0, 10)
  const ocupadas = aulas.filter((a) => a.estado === 'ocupada' || a.estado === 'vencida')
  const disponibles = aulas.filter((a) => a.estado !== 'ocupada' && a.estado !== 'vencida')

  return (
    <main>
      <div className="barra"><span>Hola, <strong>{sesion.usuario}</strong></span><button className="ghost chico" onClick={salir}>Salir</button></div>
      {aviso && <div role="status" className={`aviso ${aviso.tipo}`}>{aviso.texto}</div>}

      {estado?.estado_usuario === 'pendiente' && <section className="card"><h2>Solicitud en revisión <span className="badge b-pendiente">Pendiente</span></h2><p>Esperando la aprobación del administrador. Esta página se actualiza sola.</p></section>}
      {estado?.estado_usuario === 'rechazado' && <section className="card"><h2>Solicitud rechazada <span className="badge b-rechazado">Rechazada</span></h2><p>Hablá con el administrador si creés que es un error.</p></section>}

      {aprobado && <>
        <section className="card">
          <h2>Llaves de aulas</h2>
          {mensajeAulas && <div role="status" className="aviso info">{mensajeAulas}</div>}
          {disponibles.length > 0 && <>
            <h3>Disponibles</h3>
            <div className="lista-aulas">
              {disponibles.map((a) => <Aula key={a.id} aula={a} onPedir={setPedido} onDevolver={devolver} esMio={false} />)}
            </div>
          </>}
          <h3 className="separado">Ocupadas ahora</h3>
          <div className="lista-aulas">
            {ocupadas.length ? ocupadas.map((a) => (
              <Aula key={a.id} aula={a} onPedir={setPedido} onDevolver={devolver}
                    esMio={a.prestamo_id && a.registrado_por === sesion.usuario} />
            )) : <p className="mut">No hay llaves prestadas.</p>}
          </div>
          <p className="mut separado">Hoy: {hoy}. Las llaves sin devolver quedan marcadas en gris hasta que alguien las devuelva.</p>
        </section>

        <section className="card">
          <h2>Registrar mi cara</h2>
          <div className="mut">Modo: <strong>{estado.modo === 'registro' ? 'REGISTRO' : 'RECONOCIMIENTO'}</strong> · {estado.edad_foto == null ? 'la placa todavía no envió fotos' : `última foto hace ${estado.edad_foto} s`}</div>
          <div className="mut">Último resultado: <strong>{estado.ultimo || '—'}</strong></div>
          <button onClick={cambiarCaptura} className="separado">{capturando ? 'Terminar captura' : 'Iniciar captura'}</button>
          {preview ? <img className="live" src={preview} alt="Vista de la cámara" /> : <div className="live placeholder">Esperando una foto de la placa…</div>}
          <p className="mut">Mirá de frente, con buena luz, y guardá varias fotos cambiando un poco el ángulo.</p>
          <button className="ok" onClick={guardarLote} disabled={guardandoLote}>{guardandoLote ? 'Capturando…' : 'Guardar 5 fotos (ráfaga)'}</button>
          <button className="ghost separado" onClick={guardar} disabled={guardandoLote}>Guardar 1 foto</button>
          <p role="status" className="mut">{mensajeFoto}</p>
        </section>

        <section className="card"><h2>Mis fotos</h2><div className="grid">{fotos.length ? fotos.map((foto) => <Foto key={foto.archivo} {...foto} token={sesion.token} onDelete={borrar} />) : <p className="mut">Todavía no tenés fotos.</p>}</div></section>
      </>}

      {pedido && <FormPedido aula={pedido} usuario={sesion.usuario} onCerrar={() => setPedido(null)} onGuardado={pedidoGuardado} />}
    </main>
  )
}
