from deepface import DeepFace
import sys

if len(sys.argv) < 2:
    print("Uso: python probar_deteccion.py ruta/a/la/foto.jpg")
    sys.exit(1)

ruta = sys.argv[1]

for det in ["opencv", "yunet", "mediapipe", "retinaface"]:
    try:
        caras = DeepFace.extract_faces(img_path=ruta,
                                       detector_backend=det,
                                       enforce_detection=True)
        print(f"{det:12} -> OK ({len(caras)} cara/s)")
    except Exception as e:
        print(f"{det:12} -> NO ({str(e)[:80]})")