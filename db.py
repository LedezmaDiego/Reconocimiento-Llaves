import sqlite3
from contextlib import closing

from config import DB_PATH, AULAS_EJEMPLO, PRESTAMOS_HISTORIAL
from logs import obtener_hora

def db() -> sqlite3.Connection:
    """Abre una conexión SQLite y configura el cursor tipo diccionario."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db() -> None:
    """Crea las tablas de llaves, historial, aulas y préstamos si no existen."""
    with closing(db()) as con, con:
        con.execute("""CREATE TABLE IF NOT EXISTS llaves (
            casillero_id TEXT PRIMARY KEY, estado TEXT NOT NULL DEFAULT 'Disponible',
            persona TEXT, actualizado TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS historial (
            id INTEGER PRIMARY KEY AUTOINCREMENT, casillero_id TEXT NOT NULL,
            evento TEXT NOT NULL, persona TEXT, fecha TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS aulas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL,
            ubicacion TEXT NOT NULL DEFAULT '', activa INTEGER NOT NULL DEFAULT 1,
            creada TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS prestamos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, aula_id INTEGER NOT NULL,
            profesor TEXT NOT NULL, actividad TEXT NOT NULL, desde TEXT NOT NULL,
            hasta TEXT NOT NULL, devuelto TEXT, registrado_por TEXT NOT NULL)""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_prestamos_aula ON prestamos (aula_id, devuelto)")
    cargar_aulas_ejemplo()

def cargar_aulas_ejemplo() -> None:
    """Carga unas aulas de ejemplo la primera vez (solo si la tabla está vacía)."""
    with closing(db()) as con, con:
        vacia = con.execute("SELECT COUNT(*) FROM aulas").fetchone()[0] == 0
        if vacia:
            ahora = obtener_hora()
            con.executemany("INSERT INTO aulas (nombre, ubicacion, activa, creada) VALUES (?, ?, 1, ?)",
                            [(nombre, ubicacion, ahora) for nombre, ubicacion in AULAS_EJEMPLO])

def aulas() -> list[dict]:
    """Lista las aulas con su préstamo activo (sin devolver), si lo tienen."""
    with closing(db()) as con:
        filas = con.execute("""
            SELECT a.id, a.nombre, a.ubicacion, a.activa,
                   p.id AS prestamo_id, p.profesor, p.actividad, p.desde, p.hasta, p.registrado_por
            FROM aulas a
            LEFT JOIN prestamos p ON p.aula_id = a.id AND p.devuelto IS NULL
            ORDER BY a.nombre COLLATE NOCASE""").fetchall()
    return [dict(f) for f in filas]

def aula_por_id(aula_id: int) -> dict | None:
    """Devuelve un aula por id o None si no existe."""
    with closing(db()) as con:
        fila = con.execute("SELECT * FROM aulas WHERE id = ?", (aula_id,)).fetchone()
    return dict(fila) if fila else None

def crear_aula(nombre: str, ubicacion: str) -> dict:
    """Da de alta un aula nueva."""
    with closing(db()) as con, con:
        cur = con.execute("INSERT INTO aulas (nombre, ubicacion, activa, creada) VALUES (?, ?, 1, ?)",
                          (nombre, ubicacion, obtener_hora()))
        aula_id = cur.lastrowid
    return aula_por_id(aula_id)

def actualizar_aula(aula_id: int, campos: dict) -> dict | None:
    """Actualiza nombre, ubicación o estado activo de un aula."""
    permitidos = {k: v for k, v in campos.items() if k in ("nombre", "ubicacion", "activa") and v is not None}
    if not permitidos:
        return aula_por_id(aula_id)
    asignaciones = ", ".join(f"{k} = ?" for k in permitidos)
    with closing(db()) as con, con:
        con.execute(f"UPDATE aulas SET {asignaciones} WHERE id = ?", (*permitidos.values(), aula_id))
    return aula_por_id(aula_id)

def prestamo_activo(aula_id: int) -> dict | None:
    """Devuelve el préstamo activo de un aula, si tiene."""
    with closing(db()) as con:
        fila = con.execute("""SELECT * FROM prestamos
            WHERE aula_id = ? AND devuelto IS NULL ORDER BY id DESC LIMIT 1""", (aula_id,)).fetchone()
    return dict(fila) if fila else None

def registrar_prestamo(aula_id: int, profesor: str, actividad: str, hasta: str, registrado_por: str) -> dict:
    """Registra la salida de una llave y devuelve el préstamo creado."""
    with closing(db()) as con, con:
        cur = con.execute("""INSERT INTO prestamos (aula_id, profesor, actividad, desde, hasta, registrado_por)
            VALUES (?, ?, ?, ?, ?, ?)""", (aula_id, profesor, actividad, obtener_hora(), hasta, registrado_por))
        prestamo_id = cur.lastrowid
    with closing(db()) as con:
        fila = con.execute("SELECT * FROM prestamos WHERE id = ?", (prestamo_id,)).fetchone()
    return dict(fila)

def devolver_prestamo(prestamo_id: int) -> None:
    """Marca un préstamo como devuelto con la hora actual."""
    with closing(db()) as con, con:
        con.execute("UPDATE prestamos SET devuelto = ? WHERE id = ?", (obtener_hora(), prestamo_id))

def historial_prestamos(limite: int = PRESTAMOS_HISTORIAL) -> list[dict]:
    """Devuelve los últimos movimientos de llaves, del más reciente al más viejo."""
    with closing(db()) as con:
        filas = con.execute("""
            SELECT p.id, a.nombre AS aula, p.profesor, p.actividad, p.desde, p.hasta,
                   p.devuelto, p.registrado_por
            FROM prestamos p JOIN aulas a ON a.id = p.aula_id
            ORDER BY p.id DESC LIMIT ?""", (limite,)).fetchall()
    return [dict(f) for f in filas]

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


