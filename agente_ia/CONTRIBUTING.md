# Cómo contribuir

Gracias por querer meterle mano. Este documento explica cómo se trabaja en el proyecto para que
tu cambio entre sin fricción. Todo el proyecto —código, comentarios, commits y documentación—
está en **español**.

## Preparar el entorno

```bash
git clone https://github.com/johanrodriguezdev/agent-ia.git
cd agent-ia/agente_ia
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
python main.py                  # abre Configuración → Conexiones para pegar una clave de API
```

Requisitos: Python 3.12+, Windows (la integración con el sistema operativo es específica de
Windows; el núcleo es portable), FFmpeg en el PATH solo si vas a tocar voz.

Al primer arranque se crean `config.json`, `USER.md` y `MEMORY.md` a partir de sus plantillas
`.example`. Los tres son tuyos y están ignorados por git: no los subas.

## Correr los tests

```bash
python -m pytest tests/ --tb=short -q
```

La suite completa tarda unos minutos. Reglas:

- Ningún test depende de red, micrófono, altavoces ni de una clave de API real.
- Ningún test modifica archivos reales del sistema: usa `tmp_path`.
- Si te falta una dependencia opcional (`python-docx`, `uiautomation`, `pymupdf`…), los tests
  que la necesitan se **saltan** y lo dicen; no fallan. Si ves un rojo, es un bug de verdad.
- Antes de proponer un cambio, la suite completa tiene que quedar como la encontraste o mejor.

Las reglas completas están en [.claude/rules/testing.md](.claude/rules/testing.md).

## Qué tipo de cambio es el tuyo

**Un arreglo puntual o una mejora pequeña**: abre el PR directamente, con tests. Explica en la
descripción qué fallaba y por qué tu cambio es la forma correcta de arreglarlo.

**Una capacidad nueva o un cambio de diseño**: abre primero un issue contando qué quieres que
el agente pueda hacer y cómo lo imaginas. El proyecto se desarrolla con un flujo de
requerimientos (REQ) documentado en [CLAUDE.md](CLAUDE.md): cada cambio grande deja
especificación, arquitectura y evidencia de pruebas en `workspace/adjuntos/REQ-XXX/`. Acordar
la dirección antes de escribir código evita tirar trabajo.

## Reglas que no se negocian

Están en `.claude/rules/` y se aplican a todo cambio:

- **Seguridad** ([security-levels.md](.claude/rules/security-levels.md)): toda acción nueva se
  clasifica 🟢/🟡/🔴 y se registra en `core/security_manager.py`. Una acción sin clasificar se
  bloquea. La confirmación se pide en el punto de entrada (`execute_tool()`,
  `SkillManager.execute()`…), nunca dentro de la acción. Ningún canal remoto alcanza acciones
  amarillas. Si tu cambio abre una superficie nueva (red, archivos, procesos), dilo en el PR.
- **Estilo Python** ([python-style.md](.claude/rules/python-style.md)): type hints, líneas de
  hasta 100 caracteres, `logging` en vez de `print`, y ningún `except` que se trague un error
  sin registrarlo.
- **Skills** ([skills.md](.claude/rules/skills.md)): heredan de `BaseSkill`, se descubren solas,
  no importan otras skills directamente, y validan el input antes de tocar `subprocess`.
- **Nada de secretos en el código**: claves y tokens salen de `config.json` o de variables de
  entorno. Si subes uno por error, revócalo primero y avisa.

## Commits y pull requests

- Un commit por cambio coherente. El mensaje, en español, dice **qué se arregla y por qué**,
  no qué archivos se tocaron. Si corresponde a un REQ: `feat(REQ-XXX): …`, `fix(REQ-XXX): …`.
- El PR va contra `main`. Describe el problema, la solución y cómo lo probaste. Si cambia algo
  visible para el usuario, una captura ayuda.
- No se hace `push --force` sobre ramas compartidas ni se reescribe el historial de `main`.

## Comentarios en el código

Este proyecto comenta **por qué**, no qué. Un comentario que repite la línea de abajo sobra; uno
que explica la decisión que no se ve en el código (por qué `>=` y no `>`, por qué esta acción es
amarilla, qué se probó y no funcionó) vale oro. Si tu cambio revierte una decisión documentada,
actualiza el comentario: un comentario viejo es peor que ninguno.

## Licencia

Al contribuir aceptas que tu aporte se distribuya bajo la GPL-3.0 del proyecto (ver `LICENSE`).
Si incluyes código o recursos de terceros, agrégalos a `THIRD_PARTY_NOTICES.md` con su licencia.
