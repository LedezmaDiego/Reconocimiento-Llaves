"""Pruebas de aulas y préstamos de llaves, con una base SQLite temporal por test."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import db as db_module

RAIZ = Path(__file__).resolve().parents[1]


class AulasYPrestamos(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(dir=RAIZ)
        self.ruta = str(Path(self.temporal.name) / "llaves_prueba.db")
        self.db_original = db_module.DB_PATH
        db_module.DB_PATH = self.ruta
        db_module.init_db()

    def tearDown(self):
        db_module.DB_PATH = self.db_original
        self.temporal.cleanup()

    def test_carga_aulas_de_ejemplo(self):
        lista = db_module.aulas()
        self.assertEqual(len(lista), 3)
        self.assertTrue(all(a["prestamo_id"] is None for a in lista))

    def test_alta_de_aula(self):
        aula = db_module.crear_aula("Taller", "Planta baja")
        self.assertEqual(aula["nombre"], "Taller")
        self.assertEqual(aula["activa"], 1)
        db_module.actualizar_aula(aula["id"], {"activa": False})
        self.assertEqual(db_module.aula_por_id(aula["id"])["activa"], 0)

    def test_prestamo_y_devolucion(self):
        aula = db_module.aulas()[0]
        prestamo = db_module.registrar_prestamo(aula["id"], "Profesora Ana", "Matemática",
                                               "2026-10-07 23:00", "ana")
        self.assertIsNotNone(db_module.prestamo_activo(aula["id"]))
        self.assertIn(prestamo["id"], [a["prestamo_id"] for a in db_module.aulas() if a["id"] == aula["id"]])

        db_module.devolver_prestamo(prestamo["id"])
        self.assertIsNone(db_module.prestamo_activo(aula["id"]))
        historial = db_module.historial_prestamos()
        registro = next(h for h in historial if h["id"] == prestamo["id"])
        self.assertIsNotNone(registro["devuelto"])

    def test_historial_ordenado_y_limitado(self):
        aula = db_module.aulas()[0]
        for i in range(3):
            db_module.registrar_prestamo(aula["id"], f"Profesor {i}", "Clase", "2026-10-07 23:00", "admin")
        historial = db_module.historial_prestamos(limite=2)
        self.assertEqual(len(historial), 2)
        ids = [h["id"] for h in db_module.historial_prestamos()]
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_estado_de_aula_vencida(self):
        from routers.aulas import _estado_aula
        aula = {"activa": 1, "prestamo_id": 7, "hasta": "2020-01-01 10:00"}
        self.assertEqual(_estado_aula(aula, "2026-10-07 12:00"), "vencida")
        aula["hasta"] = "2030-01-01 10:00"
        self.assertEqual(_estado_aula(aula, "2026-10-07 12:00"), "ocupada")
        aula["prestamo_id"] = None
        self.assertEqual(_estado_aula(aula, "2026-10-07 12:00"), "disponible")
        aula["activa"] = 0
        self.assertEqual(_estado_aula(aula, "2026-10-07 12:00"), "inactiva")

    def test_esquema_de_prestamos(self):
        with closing(sqlite3.connect(self.ruta)) as con:
            columnas = {f[1] for f in con.execute("PRAGMA table_info(prestamos)")}
        self.assertEqual(columnas, {"id", "aula_id", "profesor", "actividad", "desde",
                                    "hasta", "devuelto", "registrado_por"})


if __name__ == "__main__":
    unittest.main()
