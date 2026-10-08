import { useState } from 'react'
import { api } from '../api.js'

export function Registro({ irLogin }) {
  const [registro, setRegistro] = useState({ usuario: '', pin: '', confirmar: '' })
  const [aviso, setAviso] = useState(null)

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
      setRegistro({ usuario: '', pin: '', confirmar: '' })
    } catch (error) { setAviso({ texto: error.message, tipo: 'err' }) }
  }

  return (
    <main>
      <h1>Llavero Inteligente</h1>
      <p className="sub">Solicitá tu acceso al sistema de llaves del centro educativo.</p>
      {aviso && <div role="status" className={`aviso ${aviso.tipo}`}>{aviso.texto}</div>}

      <section className="card">
        <h2>Solicitar acceso</h2>
        <p className="mut">El administrador revisa tu solicitud. Cuando la apruebe vas a poder registrar tu cara y pedir llaves.</p>
        <form onSubmit={solicitar}>
          <label>Usuario (solo letras)<input value={registro.usuario} onChange={(e) => setRegistro({ ...registro, usuario: e.target.value })} autoCapitalize="none" required /></label>
          <label>Código personal (4 a 8 números)<input type="password" inputMode="numeric" value={registro.pin} onChange={(e) => setRegistro({ ...registro, pin: e.target.value })} required /></label>
          <label>Repetir código<input type="password" inputMode="numeric" value={registro.confirmar} onChange={(e) => setRegistro({ ...registro, confirmar: e.target.value })} required /></label>
          <button>Enviar solicitud</button>
        </form>
      </section>

      <section className="card">
        <h2>¿Ya tenés usuario?</h2>
        <p className="mut">Entrá al panel para ver las aulas y pedir una llave.</p>
        <button className="ghost" onClick={irLogin}>Ir a inicio de sesión</button>
      </section>
    </main>
  )
}
