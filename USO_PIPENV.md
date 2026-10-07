# Uso de Pipenv en este proyecto

Este proyecto usa **Pipenv** para gestionar dependencias y el entorno virtual.
Los archivos clave son:

- `Pipfile` → lista de dependencias (editable a mano).
- `Pipfile.lock` → versiones exactas fijadas (no editar a mano).

## Instalación inicial

```powershell
pip install pipenv
pipenv install
```

Si quieres instalar exactamente lo del `Pipfile.lock` (en CI/producción):

```powershell
pipenv install --deploy
```

## Agregar / quitar paquetes

```powershell
pipenv install nombre-paquete        # para producción
pipenv install --dev nombre-paquete  # solo para desarrollo
pipenv uninstall nombre-paquete
```

## Ejecutar el servidor

```powershell
pipenv run python main.py
```

o bien activar la shell del entorno virtual:

```powershell
pipenv shell
python main.py
exit
```

## Otros comandos útiles

```powershell
pipenv graph          # árbol de dependencias
pipenv lock           # regenerar Pipfile.lock
pipenv sync           # sincronizar el venv con el lock
pipenv --rm           # borrar el entorno virtual
pipenv --python 3.12  # recrear usando otra versión de Python
```

## Notas

- Se usa Python **3.12** (requerido por TensorFlow/DeepFace).
- `requirements.txt` se conserva por compatibilidad, pero la fuente de
  verdad ahora es `Pipfile` / `Pipfile.lock`.
- No mezcles `pip` directo con `pipenv` dentro del mismo entorno.
