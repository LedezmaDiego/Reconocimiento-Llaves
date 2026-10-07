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

export function Admin() {
  const [clave, setClave] = useState('')
  const [token, setToken] = useState(null)
  const [usuarios, setUsuarios] = useState([])
  const [aviso, setAviso] = useState(null)
  const [version, setVersion] = useState(0)
  const pendientesAnteriores = useRef(null)

  function cerrar(expirada = false) {
    setToken(null)
    setUsuarios([])
    pendientesAnteriores.current = null
    document.title = 'Administración · Llavero ETEC'
    setAviso(expirada ? { texto: 'La sesión venció. Volvé a entrar.', tipo: 'err' } : null)
  }

  useEffect(() => {
    if (!token) return
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
        if (activo && error.status === 401) { cerrar(true); return }
      }
      if (activo) timer = setTimeout(refrescar, 3000)
    }
    refrescar()
    return () => { activo = false; clearTimeout(timer) }
  }, [token, version])

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

  async function decidir(usuario, accion) {
    try {
      await api('/admin/decidir', { method: 'POST', adminToken: token, body: { usuario, accion } })
      setAviso(null)
      setVersion((v) => v + 1)
    } catch (error) { if (error.status === 401) cerrar(true); else setAviso({ texto: error.message, tipo: 'err' }) }
  }

  async function eliminar(usuario) {
    if (!window.confirm(`¿Eliminar a ${usuario} y borrar sus fotos? No se puede deshacer.`)) return
    try {
      await api(`/admin/usuario/${encodeURIComponent(usuario)}`, { method: 'DELETE', adminToken: token })
      setVersion((v) => v + 1)
    } catch (error) { if (error.status === 401) cerrar(true); else setAviso({ texto: error.message, tipo: 'err' }) }
  }

  const pendientes = usuarios.filter((u) => u.estado === 'pendiente')
  const restantes = usuarios.filter((u) => u.estado !== 'pendiente')

  return (
    <main>
      <h1>Administración</h1>
      <p className="sub">Control de personal autorizado del casillero.</p>
      {aviso && <div role="status" className={`aviso ${aviso.tipo}`}>{aviso.texto}</div>}
      {!token ? <section className="card">
        <h2>Acceso restringido</h2>
        <form onSubmit={entrar}>
          <label>Contraseña de administrador<input type="password" value={clave} onChange={(e) => setClave(e.target.value)} required /></label>
          <button>Entrar</button>
        </form>
      </section> : <>
        <div className="barra"><span className="mut">Sesión de administrador</span><button className="ghost chico" onClick={() => cerrar()}>Salir</button></div>
        <section className="card"><h2>Solicitudes pendientes <span className="badge b-pendiente">{pendientes.length}</span></h2>
          {pendientes.length ? pendientes.map((u) => <FilaUsuario key={u.usuario} usuario={u} decidir={decidir} eliminar={eliminar} />) : <p className="mut">No hay solicitudes pendientes.</p>}
        </section>
        <section className="card"><h2>Personal registrado</h2>
          {restantes.length ? restantes.map((u) => <FilaUsuario key={u.usuario} usuario={u} decidir={decidir} eliminar={eliminar} />) : <p className="mut">Todavía no hay personal registrado.</p>}
        </section>
      </>}
    </main>
  )
}
