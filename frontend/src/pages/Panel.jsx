import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

function notificar(titulo, texto) {
  try {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification(titulo, { body: texto })
    }
  } catch { /* La notificación del navegador es opcional. */ }
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
      </>}

      {pedido && <FormPedido aula={pedido} usuario={sesion.usuario} token={sesion.token}
                              onCerrar={() => setPedido(null)} onGuardado={pedidoGuardado} />}
    </main>
  )
}
