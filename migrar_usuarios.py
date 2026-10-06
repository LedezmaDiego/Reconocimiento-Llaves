"""Pasa los usuarios de llaves.db (SQLite) a PocketBase. Se corre una sola vez.

Antes de correrlo, arrancá PocketBase y el servidor una vez (para que se cree la colección 'personal').
    export PB_EMAIL="tu@correo.com" PB_PASSWORD="tu-clave"
    python migrar_usuarios.py
"""
import os
import sqlite3
import sys

import requests

PB_URL = os.environ.get("PB_URL", "http://127.0.0.1:8090")
PB_EMAIL = os.environ.get("PB_EMAIL", "")
PB_PASSWORD = os.environ.get("PB_PASSWORD", "")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llaves.db")
COLECCION = "personal"

if not PB_EMAIL or not PB_PASSWORD:
    sys.exit("Definí PB_EMAIL y PB_PASSWORD (el superusuario de PocketBase).")

r = requests.post(f"{PB_URL}/api/collections/_superusers/auth-with-password",
                  json={"identity": PB_EMAIL, "password": PB_PASSWORD}, timeout=5)
if r.status_code != 200:
    sys.exit(f"No pude entrar a PocketBase: {r.status_code} {r.text[:150]}")
H = {"Authorization": r.json()["token"]}

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
cols = [c["name"] for c in con.execute("PRAGMA table_info(usuarios)")]
if not cols:
    sys.exit("No hay tabla 'usuarios' en llaves.db: no hay nada para migrar.")

migrados = salteados = 0
for u in con.execute("SELECT * FROM usuarios"):
    estado = u["estado"] if "estado" in cols else "aprobado"
    body = {"usuario": u["usuario"], "salt": bytes(u["salt"]).hex(), "pin_hash": bytes(u["pin_hash"]).hex(),
            "estado": estado, "creado": u["creado"]}
    r = requests.post(f"{PB_URL}/api/collections/{COLECCION}/records", json=body, headers=H, timeout=5)
    if r.status_code in (200, 201):
        migrados += 1
        print(f"  migrado: {u['usuario']} ({estado})")
    else:
        salteados += 1
        print(f"  salteado: {u['usuario']} -> {r.status_code} {r.text[:120]}")

print(f"\nListo: {migrados} migrados, {salteados} salteados.")
print("Podés dejar la tabla vieja en llaves.db como respaldo; el servidor ya no la usa.")