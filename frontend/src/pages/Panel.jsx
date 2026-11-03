import { useEffect, useRef, useState } from 'react'
import { api, subirFoto } from '../api.js'

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
      {url ? <img src={url} alt={`Foto ${archivo}`} /> : <div className="foto-vacia">Cargando…</div>}
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

function FormPedido({ aula, usuario, token, onCerrar, onGuardado }) {
  const [datos, setDatos] = useState({ profesor: usuario, actividad: '', hasta: '' })
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)

  async function pedir(evento) {
    evento.preventDefault()
    setEnviando(true)
    setError('')
    try {
      await api('/aulas/pedir', { method: 'POST', token, body: { aula_id: aula.id, ...datos } })
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
  const [aulas, setAulas] = useState([])
  const [mensajeAulas, setMensajeAulas] = useState('')
  const [pedido, setPedido] = useState(null)
  const [fotos, setFotos] = useState([])
  const [mensajeFoto, setMensajeFoto] = useState('')
  const [subiendo, setSubiendo] = useState(false)
  const [capturando, setCapturando] = useState(false)
  const estadoAnterior = useRef(null)

  // Una sola salida que apaga también el modo registro de la placa.
  async function salir() {
    try { await api('/modo?m=reconocimiento', { method: 'POST', token: sesion.token }) } catch { /* El modo caduca en el servidor. */ }
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
          setAviso({ texto: '¡Solicitud aprobada! Ya podés usar el sistema.', tipo: 'ok' })
          notificar('¡Solicitud aprobada!', 'Ya podés usar el sistema.')
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
        if (activo && error.status === 401) { onSalir(); return }
        if (activo) timer = setTimeout(consultar, 8000)
      }
    }
    consultar()
    return () => { activo = false; clearTimeout(timer) }
  }, [sesion.token, estado?.estado_usuario])

  async function refrescarFotos() {
    try {
      const datos = await api('/mis_fotos', { token: sesion.token })
      setFotos(datos.fotos)
      if (datos.avisos?.length) setMensajeFoto(`Foto rechazada: ${datos.avisos.join(' | ')}`)
    } catch { /* El sondeo periódico vuelve a intentar. */ }
  }

  async function borrarFoto(archivo) {
    if (!window.confirm(`¿Borrar la foto ${archivo}?`)) return
    try {
      await api(`/foto/${encodeURIComponent(archivo)}`, { method: 'DELETE', token: sesion.token })
      setMensajeFoto(`Foto borrada: ${archivo}`)
      await refrescarFotos()
    } catch (error) { setMensajeFoto(`Error: ${error.message}`) }
  }

  async function subirFotos(evento) {
    const archivos = Array.from(evento.target.files || [])
    evento.target.value = ''
    if (!archivos.length) return
    setSubiendo(true)
    setMensajeFoto('')
    let guardadas = 0
    const errores = []
    for (const archivo of archivos) {
      try {
        await subirFoto(archivo, sesion.token)
        guardadas += 1
      } catch (error) { errores.push(`${archivo.name}: ${error.message}`) }
    }
    setSubiendo(false)
    setMensajeFoto(guardadas
      ? `${guardadas} foto(s) subida(s). Se verifican solas en unos segundos.${errores.length ? ` ${errores[0]}` : ''}`
      : `No se pudo subir: ${errores[0] || 'archivo inválido'}`)
    await refrescarFotos()
  }

  async function capturarConCamara() {
    setCapturando(true)
    setMensajeFoto('')
    try {
      await api('/modo?m=registro', { method: 'POST', token: sesion.token })
      const res = await api('/guardar_lote?cantidad=5', { method: 'POST', token: sesion.token })
      setMensajeFoto(res.mensaje || 'Fotos capturadas. Se verifican solas en unos segundos.')
    } catch (error) {
      setMensajeFoto(`No se pudo capturar: ${error.message}`)
    } finally {
      try { await api('/modo?m=reconocimiento', { method: 'POST', token: sesion.token }) } catch { /* El modo caduca solo. */ }
      setCapturando(false)
    }
    await refrescarFotos()
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
          <h2>Fotos para el reconocimiento</h2>
          <p className="mut">Subí fotos de tu cara mirando de frente y con buena luz. Se verifican solas en unos segundos y quedan habilitadas para el llavero.</p>
          {mensajeFoto && <div role="status" className="aviso info">{mensajeFoto}</div>}
          <div className="fila">
            <label className="crecer">Subir desde la computadora
              <input type="file" accept="image/jpeg,image/png,image/webp" multiple
                     onChange={subirFotos} disabled={subiendo || capturando} />
            </label>
            <button className="ghost" onClick={capturarConCamara} disabled={subiendo || capturando}>
              {capturando ? 'Capturando…' : 'Capturar 5 fotos con la cámara'}
            </button>
          </div>
          {subiendo && <p className="mut">Subiendo fotos…</p>}
          <h3 className="separado">Mis fotos ({fotos.length})</h3>
          {fotos.length ? (
            <div className="grid">
              {fotos.map((f) => <Foto key={f.archivo} archivo={f.archivo} estado={f.estado}
                                      token={sesion.token} onDelete={borrarFoto} />)}
            </div>
          ) : <p className="mut">Todavía no cargaste fotos.</p>}
        </section>

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
      </>}

      {pedido && <FormPedido aula={pedido} usuario={sesion.usuario} token={sesion.token}
                              onCerrar={() => setPedido(null)} onGuardado={pedidoGuardado} />}
    </main>
  )
}
