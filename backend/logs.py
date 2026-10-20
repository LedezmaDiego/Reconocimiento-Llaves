from datetime import datetime

def obtener_hora() -> str:
    """Devuelve la hora actual con el formato estándar de la aplicación."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(tag: str, texto: str) -> None:
    """Imprime un mensaje con fecha y etiqueta, manteniendo el formato actual."""
    print(f"[{obtener_hora()}] [{tag}] {texto}")

