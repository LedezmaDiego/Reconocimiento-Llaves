import sys
import requests

if len(sys.argv) < 2:
    print("Uso: python probar_foto.py ruta_de_la_foto.jpg")
    sys.exit(1)

ruta_foto = sys.argv[1]
url = "http://127.0.0.1:8000/reconocimiento"

with open(ruta_foto, "rb") as f:
    archivos = {"file": (ruta_foto, f, "image/jpeg")}
    respuesta = requests.post(url, files=archivos)

print(respuesta.status_code)
print(respuesta.json())