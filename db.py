import sqlite3
from contextlib import closing

from config import DB_PATH
from logs import obtener_hora

def db() -> sqlite3.Connection:
    """Abre una conexión SQLite y configura el cursor tipo diccionario."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db() -> None:
    """Crea las tablas de llaves e historial si todavía no existen."""
    with closing(db()) as con, con:
        con.execute("""CREATE TABLE IF NOT EXISTS llaves (
            casillero_id TEXT PRIMARY KEY, estado TEXT NOT NULL DEFAULT 'Disponible',
            persona TEXT, actualizado TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS historial (
            id INTEGER PRIMARY KEY AUTOINCREMENT, casillero_id TEXT NOT NULL,
            evento TEXT NOT NULL, persona TEXT, fecha TEXT NOT NULL)""")

def registrar_estado(casillero_id: str, estado: str, evento: str, persona: str | None = None) -> None:
    """Actualiza el estado de un casillero y agrega su evento al historial."""
    ahora = obtener_hora()
    with closing(db()) as con, con:
        con.execute("""INSERT INTO llaves (casillero_id, estado, persona, actualizado)
            VALUES (?, ?, ?, ?) ON CONFLICT(casillero_id) DO UPDATE SET
            estado = excluded.estado, persona = excluded.persona, actualizado = excluded.actualizado""",
                    (casillero_id, estado, persona, ahora))
        con.execute("INSERT INTO historial (casillero_id, evento, persona, fecha) VALUES (?, ?, ?, ?)",
                    (casillero_id, evento, persona, ahora))


