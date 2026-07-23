# Regla: Testing — O.R.I.O.N.

## Framework
- Usar `pytest` para todos los tests.
- Los tests viven en `agente_ia/tests/`.
- Naming: `test_<modulo>.py`.

## Cobertura esperada
- **Nuevo código**: toda función pública debe tener al menos un test.
- **Skills**: test de `extract_params()` y `execute()` con entradas válidas e inválidas.
- **Handlers**: test de cada intent con parámetros típicos y casos borde.
- **Seguridad**: test que verifique que acciones destructivas piden confirmación.

## Ejecución
```bash
cd agente_ia && python -m pytest tests/ --tb=short -v
```

Para un archivo específico:
```bash
cd agente_ia && python -m pytest tests/test_archivo.py --tb=short -v
```

## Lo que NO debe hacer un test
- No depende de redes externas (API de Claude, DeepSeek, Google STT).
- No depende del micrófono o altavoces.
- No modifica archivos reales del sistema (usar `tmp_path` de pytest).
- No ejecuta `os.system()` o `subprocess` sin mocking.

## Mocks permitidos
- `unittest.mock.patch` para llamadas a API externas.
- `unittest.mock.MagicMock` para reemplazar dependencias como `pyttsx3`, `pyautogui`.
- `tmp_path` fixture de pytest para archivos temporales.

## Estructura de test para skills
```python
import pytest
from unittest.mock import patch, MagicMock

def test_mi_skill_extract_params():
    skill = MiSkill()
    result = skill.extract_params("abre chrome")
    assert result == {"app": "chrome"}

def test_mi_skill_execute_sin_parametros():
    skill = MiSkill()
    result = skill.execute({})
    assert "No entendí" in result
```

## Tests de regresión
- Ejecutar `pytest` completo antes de marcar un REQ como `LISTO_PARA_COMMIT`.
- Si se introducen nuevos fallos, el REQ vuelve a `orion-dev`.
