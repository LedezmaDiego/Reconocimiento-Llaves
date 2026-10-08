import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

function FilaUsuario({ usuario, decidir, eliminar }) {
  return (
    <div className="fila">
      <div>
        <strong>{usuario.usuario}</strong> <span className={`badge b-${usuario.estado}`}>{usuario.estado}</span>
        <div className="mut">Solicitó: {usuario.creado}{usuario.estado === 'aprobado' ? ` · ${usuario.fotos} foto(s)` : ''}</div>
      </div>
      <div className="acciones">
        {usuario.estado !== 'aprobado' && <button className="ok chico" onClick={() => decidir(usuario.usuario, 'aprobar')}>Aprobar</button>}
        {usuario.estado === 'pendiente' && <button className="rojo chico" onClick={() => decidir(usuario.usuario, 'rechazar')}>Rechazar</button>}
        {usuario.estado !== 'pendiente' && <button className="ghost chico" onClick={() => eliminar(usuario.usuario)}>Eliminar</button>}
      </div>
    </div>
  )
}

const ETIQUETA_ESTADO = {
  disponible: { texto: 'Disponible', clase: 'b-aprobado' },
  ocupada: { texto: 'Ocupada', clase: 'b-ocupada' },
  vencida: { texto: 'Sin devolver', clase: 'b-gris' },
  inactiva: { texto: 'Deshabilitada', clase: 'b-gris' },
}

function FilaAula({ aula, guardar, liberar }) {
  const [edicion, setEdicion] = useState(null)
  const etiqueta = ETIQUETA_ESTADO[aula.estado] || ETIQUETA_ESTADO.inactiva

  if (edicion) {
    return (
      <div className="fila">
        <div className="crecer">
          <input value={edicion.nombre} onChange={(e) => setEdicion({ ...edicion, nombre: e.target.value })} />
          <input value={edicion.ubicacion} onChange={(e) => setEdicion({ ...edicion, ubicacion: e.target.value })} />
        </div>
        <div className="acciones">
          <button className="ok chico" onClick={() => { guardar(aula.id, edicion); setEdicion(null) }}>Guardar</button>
          <button className="ghost chico" onClick={() => setEdicion(null)}>Cancelar</button>
        </div>
      </div>
    )
  }

  return (
    <div className="fila">
      <div>
        <strong>{aula.nombre}</strong> <span className={`badge ${etiqueta.clase}`}>{etiqueta.texto}</span>
        {aula.ubicacion && <div className="mut">{aula.ubicacion}</div>}
        {aula.profesor && <div className="mut">{aula.profesor} · {aula.actividad} · hasta {aula.hasta.slice(11, 16)}</div>}
      </div>
      <div className="acciones">
        <button className="ghost chico" onClick={() => setEdicion({ nombre: aula.nombre, ubicacion: aula.ubicacion || '' })}>Editar</button>
        {aula.prestamo_id && <button className="chico" onClick={() => liberar(aula)}>Liberar</button>}
        <button className={aula.activa ? 'rojo chico' : 'ok chico'}
                onClick={() => guardar(aula.id, { activa: aula.activa ? false : true })}>
          {aula.activa ? 'Deshabilitar' : 'Habilitar'}
        </button>
      </div>
    </div>
  )
}

function PestanaAulas({ token }) {
  const [aulas, setAulas] = useState([])
  const [historial, setHistorial] = useState([])
  const [nueva, setNueva] = useState({ nombre: '', ubicacion: '' })
  const [aviso, setAviso] = useState(null)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    let activo = true
    let timer
    async function consultar() {
      try {
        const datos = await api('/admin/aulas', { adminToken: token })
        if (!activo) return
        setAulas(datos.aulas)
        setHistorial(datos.historial)
      } catch (error) {
        if (activo && error.status === 401) return
      }
      if (activo) timer = setTimeout(consultar, 5000)
    }
    consultar()
    return () => { activo = false; clearTimeout(timer) }
  }, [token, version])

  async function crear(evento) {
    evento.preventDefault()
    try {
      await api('/admin/aulas', { method: 'POST', adminToken: token, body: nueva })
      setNueva({ nombre: '', ubicacion: '' })
      setAviso(null)
      setVersion((v) => v + 1)
    } catch (error) { setAviso({ texto: error.message, tipo: 'err' }) }
  }

  async function guardar(aulaId, campos) {
    try {
      await api(`/admin/aulas/${aulaId}`, { method: 'PATCH', adminToken: token, body: campos })
      setVersion((v) => v + 1)
    } catch (error) { setAviso({ texto: error.message, tipo: 'err' }) }
  }

  async function liberar(aula) {
    if (!window.confirm(`¿Liberar la llave de ${aula.nombre}? Quedará marcada como devuelta.`)) return
    try {
      await api(`/admin/aulas/${aula.id}/liberar`, { method: 'POST', adminToken: token })
      setVersion((v) => v + 1)
    } catch (error) { setAviso({ texto: error.message, tipo: 'err' }) }
  }

  return <>
    {aviso && <div role="status" className={`aviso ${aviso.tipo}`}>{aviso.texto}</div>}
    <section className="card">
      <h2>Agregar aula</h2>
      <form onSubmit={crear}>
        <label>Nombre<input value={nueva.nombre} onChange={(e) => setNueva({ ...nueva, nombre: e.target.value })} required /></label>
        <label>Ubicación (opcional)<input value={nueva.ubicacion} onChange={(e) => setNueva({ ...nueva, ubicacion: e.target.value })} /></label>
        <button>Agregar</button>
      </form>
    </section>
    <section className="card">
      <h2>Aulas <span className="badge b-aprobado">{aulas.filter((a) => a.activa).length} activas</span></h2>
      {aulas.length ? aulas.map((a) => <FilaAula key={a.id} aula={a} guardar={guardar} liberar={liberar} />)
                    : <p className="mut">Todavía no hay aulas.</p>}
    </section>
    <section className="card">
      <h2>Historial de llaves</h2>
      {historial.length ? historial.map((h) => (
        <div className="fila" key={h.id}>
          <div>
            <strong>{h.aula}</strong>
            <div className="mut">{h.profesor} · {h.actividad} · {h.desde.slice(0, 16)} → hasta {h.hasta.slice(11, 16)}</div>
          </div>
          <span className={`badge ${h.devuelto ? 'b-aprobado' : 'b-gris'}`}>{h.devuelto ? `Devuelta ${h.devuelto.slice(0, 16)}` : 'Sin devolver'}</span>
        </div>
      )) : <p className="mut">Todavía no hay movimientos.</p>}
    </section>
  </>
}

function PestanaUsuarios({ token }) {
  const [usuarios, setUsuarios] = useState([])
  const [aviso, setAviso] = useState(null)
  const [version, setVersion] = useState(0)
  const pendientesAnteriores = useRef(null)

  useEffect(() => {
    let activo = true
    let timer
    async function refrescar() {
      try {
        const datos = await api('/admin/usuarios', { adminToken: token })
        if (!activo) return
        const pendientes = datos.usuarios.filter((u) => u.estado === 'pendiente')
        setUsuarios(datos.usuarios)
        document.title = pendientes.length ? `(${pendientes.length}) Solicitudes · Llavero ETEC` : 'Administración · Llavero ETEC'
        if (pendientesAnteriores.current !== null && pendientes.length > pendientesAnteriores.current) {
          setAviso({ texto: `Nueva solicitud de acceso: ${pendientes.at(-1).usuario}`, tipo: 'info' })
          try {
            if ('Notification' in window && Notification.permission === 'granted') {
              new Notification('Nueva solicitud', { body: `${pendientes.at(-1).usuario} pide acceso` })
            }
          } catch { /* El panel sigue funcionando sin notificaciones. */ }
        }
        pendientesAnteriores.current = pendientes.length
      } catch (error) {
        if (activo && error.status === 401) { setAviso({ texto: 'La sesión venció. Volvé a entrar.', tipo: 'err' }); return }
      }
      if (activo) timer = setTimeout(refrescar, 3000)
    }
    refrescar()
    return () => { activo = false; clearTimeout(timer) }
  }, [token, version])

  async function decidir(usuario, accion) {
    try {
      await api('/admin/decidir', { method: 'POST', adminToken: token, body: { usuario, accion } })
      setAviso(null)
      setVersion((v) => v + 1)
    } catch (error) { setAviso({ texto: error.message, tipo: 'err' }) }
  }

  async function eliminar(usuario) {
    if (!window.confirm(`¿Eliminar a ${usuario} y borrar sus fotos? No se puede deshacer.`)) return
    try {
      await api(`/admin/usuario/${encodeURIComponent(usuario)}`, { method: 'DELETE', adminToken: token })
      setVersion((v) => v + 1)
    } catch (error) { setAviso({ texto: error.message, tipo: 'err' }) }
  }

  const pendientes = usuarios.filter((u) => u.estado === 'pendiente')
  const restantes = usuarios.filter((u) => u.estado !== 'pendiente')

  return <>
    {aviso && <div role="status" className={`aviso ${aviso.tipo}`}>{aviso.texto}</div>}
    <section className="card"><h2>Solicitudes pendientes <span className="badge b-pendiente">{pendientes.length}</span></h2>
      {pendientes.length ? pendientes.map((u) => <FilaUsuario key={u.usuario} usuario={u} decidir={decidir} eliminar={eliminar} />) : <p className="mut">No hay solicitudes pendientes.</p>}
    </section>
    <section className="card"><h2>Personal registrado</h2>
      {restantes.length ? restantes.map((u) => <FilaUsuario key={u.usuario} usuario={u} decidir={decidir} eliminar={eliminar} />) : <p className="mut">Todavía no hay personal registrado.</p>}
    </section>
  </>
}

export function Admin() {
  const [clave, setClave] = useState('')
  const [token, setToken] = useState(null)
  const [pestana, setPestana] = useState('usuarios')
  const [aviso, setAviso] = useState(null)

  function cerrar(expirada = false) {
    setToken(null)
    setPestana('usuarios')
    document.title = 'Administración · Llavero ETEC'
    setAviso(expirada ? { texto: 'La sesión venció. Volvé a entrar.', tipo: 'err' } : null)
  }

  async function entrar(evento) {
    evento.preventDefault()
    try {
      const datos = await api('/admin/login', { method: 'POST', body: { clave } })
      setToken(datos.token)
      setClave('')
      setAviso(null)
      try {
        if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission()
      } catch { /* El inicio de sesión no depende de las notificaciones. */ }
    } catch (error) { setAviso({ texto: error.message, tipo: 'err' }) }
  }

  return (
    <main>
      <h1>Administración</h1>
      <p className="sub">Control del personal autorizado y de las llaves de las aulas.</p>
      {aviso && <div role="status" className={`aviso ${aviso.tipo}`}>{aviso.texto}</div>}
      {!token ? <section className="card">
        <h2>Acceso restringido</h2>
        <form onSubmit={entrar}>
          <label>Contraseña de administrador<input type="password" value={clave} onChange={(e) => setClave(e.target.value)} required /></label>
          <button>Entrar</button>
        </form>
      </section> : <>
        <div className="barra">
          <div className="acciones">
            <button className={pestana === 'usuarios' ? 'chico' : 'ghost chico'} onClick={() => setPestana('usuarios')}>Usuarios</button>
            <button className={pestana === 'aulas' ? 'chico' : 'ghost chico'} onClick={() => setPestana('aulas')}>Aulas y llaves</button>
          </div>
          <button className="ghost chico" onClick={() => cerrar()}>Salir</button>
        </div>
        {pestana === 'usuarios' ? <PestanaUsuarios token={token} /> : <PestanaAulas token={token} />}
      </>}
    </main>
  )
}
