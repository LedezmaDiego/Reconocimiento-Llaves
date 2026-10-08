import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

export function Login({ alEntrar, irRegistro }) {
  const [paso, setPaso] = useState(1)
  const [usuario, setUsuario] = useState('')
  const [datosUsuario, setDatosUsuario] = useState(null)   // respuesta de /preparar_login
  const [metodo, setMetodo] = useState(null)               // 'pin' | 'rostro'
  const [pin, setPin] = useState('')
  const [aviso, setAviso] = useState(null)
  const [esperaRostro, setEsperaRostro] = useState(null)   // solicitud de reconocimiento en curso
  const [avisoRostro, setAvisoRostro] = useState('')
  const solicitudRef = useRef(null)

  // Paso 1: verificar que el usuario existe y ver qué métodos tiene disponibles.
  async function continuar(evento) {
    evento.preventDefault()
    setAviso(null)
    try {
      const datos = await api('/preparar_login', { method: 'POST', body: { usuario } })
      setDatosUsuario(datos)
      setMetodo(datos.puede_rostro ? null : 'pin')
      setPaso(2)
    } catch (error) { setAviso({ texto: error.message, tipo: 'err' }) }
  }

  // Login con PIN.
  async function entrarPin(evento) {
    evento.preventDefault()
    try {
      const datos = await api('/login', { method: 'POST', body: { usuario, pin } })
      alEntrar({ token: datos.token, usuario: datos.usuario, estado: datos.estado })
    } catch (error) { setAviso({ texto: error.message, tipo: 'err' }) }
  }

  // Login por rostro: abre la espera y consulta el estado cada 1,5 s.
  async function iniciarRostro() {
    setAviso(null)
    setAvisoRostro('Mirá a la cámara…')
    try {
      const datos = await api('/login_rostro', { method: 'POST', body: { usuario } })
      solicitudRef.current = datos.solicitud_id
      setEsperaRostro(datos.solicitud_id)
    } catch (error) { setAviso({ texto: error.message, tipo: 'err' }) }
  }

  function cancelarRostro() {
    if (solicitudRef.current) api(`/login_rostro/${solicitudRef.current}`, { method: 'DELETE' }).catch(() => {})
    solicitudRef.current = null
    setEsperaRostro(null)
    setAvisoRostro('')
  }

  useEffect(() => {
    if (!esperaRostro) return
    let activo = true
    let timer
    async function consultar() {
      try {
        const datos = await api(`/login_rostro/${esperaRostro}`)
        if (!activo) return
        if (datos.estado === 'autorizado') {
          setEsperaRostro(null)
          alEntrar({ token: datos.token, usuario: datos.usuario })
          return
        }
        if (datos.estado === 'expirado') {
          setEsperaRostro(null)
          setAviso({ texto: 'Se agotó el tiempo. Probá de nuevo o entrá con tu PIN.', tipo: 'err' })
          return
        }
        if (datos.aviso) setAvisoRostro(datos.aviso)
      } catch (error) {
        if (activo && error.status === 404) {
          setEsperaRostro(null)
          setAviso({ texto: 'La espera venció. Probá de nuevo.', tipo: 'err' })
          return
        }
      }
      if (activo) timer = setTimeout(consultar, 1500)
    }
    consultar()
    return () => { activo = false; clearTimeout(timer) }
  }, [esperaRostro])

  useEffect(() => () => { if (solicitudRef.current) api(`/login_rostro/${solicitudRef.current}`, { method: 'DELETE' }).catch(() => {}) }, [])

  function volver() {
    cancelarRostro()
    setPaso(1)
    setDatosUsuario(null)
    setMetodo(null)
    setPin('')
    setAviso(null)
  }

  return (
    <main>
      <h1>Llavero Inteligente</h1>
      <p className="sub">Acceso al sistema de llaves del centro educativo.</p>
      {aviso && <div role="status" className={`aviso ${aviso.tipo}`}>{aviso.texto}</div>}

      {paso === 1 && <section className="card">
        <h2>Iniciar sesión</h2>
        <p className="mut">Escribí tu usuario para continuar.</p>
        <form onSubmit={continuar}>
          <label>Usuario<input value={usuario} onChange={(e) => setUsuario(e.target.value)} autoCapitalize="none" required /></label>
          <button>Continuar</button>
        </form>
        <p className="mut separado">¿No tenés usuario? <button className="ghost chico" onClick={irRegistro}>Solicitar acceso</button></p>
      </section>}

      {paso === 2 && datosUsuario && <section className="card">
        <h2>Hola, {datosUsuario.usuario}</h2>
        {datosUsuario.estado !== 'aprobado'
          ? <p className="mut">Tu cuenta está {datosUsuario.estado === 'pendiente' ? 'pendiente de aprobación' : 'rechazada'}. Hablá con el administrador.</p>
          : <>
            {datosUsuario.puede_rostro && <p className="mut">Elegí cómo querés entrar.</p>}
            {datosUsuario.puede_rostro && !metodo && <div className="acciones separado">
              <button onClick={() => setMetodo('rostro')}>Reconocimiento facial</button>
              <button className="ghost" onClick={() => setMetodo('pin')}>Usar mi PIN</button>
            </div>}

            {metodo === 'rostro' && <div className="separado">
              {!esperaRostro
                ? <button onClick={iniciarRostro}>Buscar mi rostro</button>
                : <>
                  <p role="status" className="mut">Mirá a la cámara… {avisoRostro}</p>
                  <button className="ghost" onClick={cancelarRostro}>Cancelar</button>
                </>}
            </div>}

            {metodo === 'pin' && <form onSubmit={entrarPin} className="separado">
              <label>Tu PIN<input type="password" inputMode="numeric" value={pin} onChange={(e) => setPin(e.target.value)} required /></label>
              <button>Entrar con PIN</button>
            </form>}

            <button className="ghost chico separado" onClick={volver}>Volver</button>
          </>}
      </section>}
    </main>
  )
}
