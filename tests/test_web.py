"""Pruebas de las rutas sin arrancar PocketBase ni cargar modelos faciales."""
import asyncio
import importlib
import json
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from starlette.requests import Request


class RutasWeb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # La integración HTTP se verifica sin cargar TensorFlow ni modificar las bases de datos.
        with patch.dict(sys.modules, {"deepface": SimpleNamespace(DeepFace=object())}):
            cls.servidor = importlib.import_module("main")

    def test_contrato_de_rutas_api(self):
        rutas = {(ruta.path, metodo) for ruta in self.servidor.app.routes
                 for metodo in getattr(ruta, "methods", ())}
        esperadas = {
            ("/reconocimiento", "POST"), ("/solicitar_acceso", "POST"),
            ("/login", "POST"), ("/acceso_codigo", "POST"),
            ("/preparar_login", "POST"), ("/login_rostro", "POST"),
            ("/login_rostro/{solicitud_id}", "GET"), ("/login_rostro/{solicitud_id}", "DELETE"),
            ("/admin/login", "POST"), ("/admin/usuarios", "GET"),
            ("/admin/decidir", "POST"), ("/admin/usuario/{usuario}", "DELETE"),
            ("/ultima_foto", "GET"), ("/estado", "GET"),
            ("/modo", "POST"), ("/guardar_foto", "POST"),
            ("/guardar_lote", "POST"),
            ("/mis_fotos", "GET"), ("/foto/{archivo}", "GET"),
            ("/foto/{archivo}", "DELETE"), ("/devolucion", "POST"),
            ("/retiro", "POST"), ("/llaves", "GET"),
            ("/aulas", "GET"), ("/aulas/pedir", "POST"), ("/aulas/devolver", "POST"),
            ("/admin/aulas", "GET"), ("/admin/aulas", "POST"),
            ("/admin/aulas/{aula_id}", "PATCH"), ("/admin/aulas/{aula_id}/liberar", "POST"),
        }
        self.assertTrue(esperadas <= rutas, esperadas - rutas)

    def test_respuesta_que_espera_la_placa_en_modo_registro(self):
        async def recibir():
            return {"type": "http.request", "body": b"\xff\xd8" + b"0" * 1000,
                    "more_body": False}
        request = Request({"type": "http", "method": "POST",
                           "headers": [(b"x-casillero-id", b"C01")]}, recibir)
        ruta = next(r for r in self.servidor.app.routes if r.path == "/reconocimiento"
                    and "POST" in getattr(r, "methods", ()))
        modo = ruta.endpoint.__globals__["modo_actual"].__globals__["MODO"]
        ultima_foto = ruta.endpoint.__globals__["ULTIMA_FOTO"]
        with patch.dict(modo, {"valor": "registro", "hasta": time.time() + 60}), \
             patch.dict(ultima_foto):
            respuesta = asyncio.run(ruta.endpoint(request))
        texto = json.dumps(respuesta, separators=(",", ":"))
        self.assertIn('"modo":"registro"', texto)
        self.assertIn('"autorizado":false', texto)

    async def pedir(self, ruta):
        mensajes = []
        async def recibir():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def enviar(mensaje):
            mensajes.append(mensaje)
        await self.servidor.app({
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "GET", "scheme": "http", "path": ruta,
            "raw_path": ruta.encode(), "root_path": "", "query_string": b"",
            "headers": [], "client": ("127.0.0.1", 1234), "server": ("localhost", 8000),
        }, recibir, enviar)
        return next(m["status"] for m in mensajes if m["type"] == "http.response.start")

    def test_paginas_react_y_redireccion(self):
        self.assertEqual(asyncio.run(self.pedir("/")), 307)
        pagina = next(r.endpoint for r in self.servidor.app.routes if r.path == "/registro")
        compilado = (Path(pagina.__globals__["FRONTEND_DIST"]) / "index.html").is_file()
        for ruta in ("/registro", "/inicio-sesion", "/panel", "/admin"):
            self.assertEqual(asyncio.run(self.pedir(ruta)), 200 if compilado else 503)

    def test_sin_compilar_la_api_sigue_disponible(self):
        pagina = next(r.endpoint for r in self.servidor.app.routes if r.path == "/registro")
        with patch.dict(pagina.__globals__, {"FRONTEND_DIST": "directorio-que-no-existe"}):
            respuesta = asyncio.run(pagina())
            self.assertEqual(respuesta.status_code, 503)


if __name__ == "__main__":
    unittest.main()
