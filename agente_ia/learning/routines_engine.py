import json
import os
from agents.action_registry import ACTION_REGISTRY, execute_action

ROUTINES_FILE = os.path.join(os.path.dirname(__file__), "routines.json")

def _load_routines() -> dict:
    try:
        with open(ROUTINES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Routines] No pude cargar rutinas: {e}")
        return {}

def list_routine_names() -> list[str]:
    return list(_load_routines().keys())

def get_routine(name: str) -> dict | None:
    routines = _load_routines()
    return routines.get(name.lower().strip())

def match_routine(user_text: str) -> dict | None:
    text = user_text.lower().strip()
    for name, routine in _load_routines().items():
        triggers = routine.get("triggers", [name])
        for trigger in triggers:
            if trigger in text:
                return {"name": name, **routine}
    return None

def execute_routine_actions(actions: list[dict], channel=None) -> str:
    results = []
    for step in actions:
        action_name = step.get("action", "")
        params = step.get("params", {})
        info = ACTION_REGISTRY.get(action_name)
        if not info:
            results.append(f"  ❌ '{action_name}': acción no registrada")
            continue
        try:
            output = execute_action(action_name, params, channel=channel)
            results.append(f"  ✅ {output}")
        except Exception as e:
            results.append(f"  ❌ '{action_name}': {e}")
    return "\n".join(results)

def try_routine(user_text: str, channel=None) -> str | None:
    match = match_routine(user_text)
    if not match:
        return None
    actions = match.get("actions", [])
    if not actions:
        return None
    details = execute_routine_actions(actions, channel=channel)
    return f"Rutina '{match['name']}' ejecutada:\n{details}"
