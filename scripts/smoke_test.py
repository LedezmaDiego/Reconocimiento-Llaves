"""Smoke test básico del backend Fase 2; no requiere cámara, placa ni PocketBase activo."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import db  # noqa: E402
import main as app_module  # noqa: E402
import seguridad  # noqa: E402

ADMIN_INCORRECTA = "clave incorrecta para prueba"


def main() -> int:
    """Ejecuta comprobaciones mínimas de las rutas sin servicios externos."""
    with tempfile.TemporaryDirectory(dir=RAIZ) as temporal:
        with patch.object(db, "DB_PATH", str(Path(temporal) / "llaves_prueba.db")):
            db.init_db()
            try:
                cliente = TestClient(app_module.app)  # Sin context manager: no corre startup.
                ok = True
                r = cliente.get("/estado")
                ok &= r.status_code == 200 and {"modo", "edad_foto"} <= r.json().keys()

                r = cliente.post("/reconocimiento", content=b"0123456789")
                ok &= r.status_code == 200 and r.json().get("status") == "error"
                ok &= r.json().get("mensaje") == "Imagen muy pequeña o corrupta"

                r = cliente.post("/admin/login", json={"clave": ADMIN_INCORRECTA})
                ok &= r.status_code == 401
                seguridad.INTENTOS.clear()

                r = cliente.get("/admin/usuarios")
                ok &= r.status_code == 401

                r = cliente.get("/registro")
                ok &= r.status_code == 200
                r = cliente.get("/admin")
                ok &= r.status_code in (200, 404)

                r = cliente.post("/login", json={"usuario": "zzzzzzzz", "pin": "0000"})
                ok &= r.status_code in (401, 503)

                print("smoke_test:", "OK" if ok else "FALLO")
                return 0 if ok else 1
            finally:
                seguridad.INTENTOS.clear()


if __name__ == "__main__":
    raise SystemExit(main())

