import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Registro } from './pages/Registro.jsx'
import { Login } from './pages/Login.jsx'
import { Panel } from './pages/Panel.jsx'
import { Admin } from './pages/Admin.jsx'
import './styles.css'

const RUTAS = ['/registro', '/inicio-sesion', '/panel', '/admin']

// Router mínimo por URL, sin dependencias. La sesión vive en memoria:
// el servidor guarda los tokens y acá solo se mantienen mientras dura la pestaña.
function App() {
  const [ruta, setRuta] = useState(window.location.pathname)
  const [sesion, setSesion] = useState(null)

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
    setSesion(datos)
    ir('/panel')
  }

  function salir() {
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
