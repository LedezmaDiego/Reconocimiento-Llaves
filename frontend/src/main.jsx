import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Registro } from './pages/Registro.jsx'
import { Login } from './pages/Login.jsx'
import { Panel } from './pages/Panel.jsx'
import { Admin } from './pages/Admin.jsx'
import { guardarSesion, leerSesion, borrarSesion } from './sesion.js'
import './styles.css'

const RUTAS = ['/registro', '/inicio-sesion', '/panel', '/admin']

// Router mínimo por URL, sin dependencias. La sesión se guarda en localStorage
// para sobrevivir recargas; el servidor valida el token en cada petición.
function App() {
  const [ruta, setRuta] = useState(window.location.pathname)
  const [sesion, setSesion] = useState(leerSesion)

  useEffect(() => {
    const alVolver = () => setRuta(window.location.pathname)
    window.addEventListener('popstate', alVolver)
    return () => window.removeEventListener('popstate', alVolver)
  }, [])

  function ir(destino) {
    if (window.location.pathname !== destino) window.history.pushState({}, '', destino)
    setRuta(destino)
  }

  useEffect(() => {
    if (!RUTAS.includes(ruta)) ir('/inicio-sesion')
    else if (sesion && (ruta === '/inicio-sesion' || ruta === '/registro')) ir('/panel')
    else if (!sesion && ruta === '/panel') ir('/inicio-sesion')
  }, [ruta, sesion])

  function entrar(datos) {
    guardarSesion(datos)
    setSesion(datos)
    ir('/panel')
  }

  function salir() {
    borrarSesion()
    setSesion(null)
    ir('/inicio-sesion')
  }

  if (ruta === '/admin') return <Admin />
  if (ruta === '/panel' && sesion) return <Panel sesion={sesion} onSalir={salir} />
  if (ruta === '/registro') return <Registro irLogin={() => ir('/inicio-sesion')} />
  return <Login alEntrar={entrar} irRegistro={() => ir('/registro')} />
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
