# Regla: Skills — O.R.I.O.N.

## Arquitectura de skills
Todo skill debe heredar de `skills/base_skill.py:BaseSkill` e implementar:

```python
class MiNuevoSkill(BaseSkill):
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    def get_intents(self) -> List[str]: ...
    def get_training_data(self) -> List[Tuple[str, str]]: ...
    def extract_params(self, text: str) -> Optional[Dict[str, Any]]: ...
    def execute(self, params: Dict[str, Any]) -> str: ...
```

## Registro automático
- Los skills se descubren automáticamente via `skill_manager.py`.
- Solo con crear el archivo en `skills/` y que herede de `BaseSkill`, se registra solo.
- No es necesario tocar `skill_manager.py` ni ningún registro manual.

## Training data
- `get_training_data()` debe devolver `[(frase_ejemplo, intent_name), ...]`.
- Esto alimenta automáticamente el clasificador TF-IDF + SVM.
- Incluir al menos 5-10 ejemplos por intent.

## Hot-reload
- `skill_creator_skill.py` puede recargar skills en caliente.
- No es necesario reiniciar O.R.I.O.N. al crear o modificar un skill.

## Ciclo de vida
1. Crear archivo en `skills/` heredando de `BaseSkill`
2. `skill_manager` lo descubre automáticamente al iniciar
3. `get_training_data()` alimenta el clasificador
4. `dispatcher.py` lo prioriza sobre handlers legacy
5. `execute()` se llama cuando el intent coincide

## Prohibido
- No importar funciones de otros skills directamente — usar `dispatcher.py` como intermediario.
- No llamar `os.system()` o `subprocess` sin validar el input antes.
- No hardcodear rutas absolutas — usar `os.path` relativo al proyecto.
