import React from 'react'
import { createRoot } from 'react-dom/client'
import { Registro } from './pages/Registro.jsx'
import { Admin } from './pages/Admin.jsx'
import './styles.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {window.location.pathname === '/admin' ? <Admin /> : <Registro />}
  </React.StrictMode>,
)
