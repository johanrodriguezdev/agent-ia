"""
skills/skill_creator_skill.py
═══════════════════════════════════════════════════════════
 SkillCreator — La habilidad máxima de Noddoo.
 Permite CREAR, MODIFICAR, EVALUAR y OPTIMIZAR skills
 autónomamente sin intervención del usuario.

 Flujo completo:
   1. Usuario pide crear/modificar una skill
   2. Noddoo genera el código Python usando el LLM
   3. Se valida la sintaxis antes de guardar
   4. Se guarda en skills/ y se recarga en caliente
   5. Noddoo confirma que la nueva habilidad está activa
═══════════════════════════════════════════════════════════
"""

import os
import ast
import importlib
import sys
import logging
from typing import Dict, List, Tuple, Any
from skills.base_skill import BaseSkill

logger = logging.getLogger(__name__)

SKILLS_DIR = os.path.dirname(__file__)

# Plantilla base que se inyecta al LLM para que genere código correcto
SKILL_TEMPLATE = '''
from typing import Dict, List, Tuple, Any
from skills.base_skill import BaseSkill
from core.address import vocative, vocative_start

class {class_name}(BaseSkill):
    """
    {description}
    Creada automáticamente por SkillCreator de Noddoo.
    """

    @property
    def name(self) -> str:
        return "{skill_name}"

    @property
    def description(self) -> str:
        return "{description}"

    def get_intents(self) -> List[str]:
        return {intents}

    def get_training_data(self) -> List[Tuple[str, str]]:
        """Frases de ejemplo que activarán esta skill."""
        return {training_data}

    def extract_params(self, intent: str, text: str) -> Dict[str, Any]:
        return {{}}

    def execute(self, intent: str, params: Dict[str, Any]) -> str:
        # === CÓDIGO GENERADO POR NODDOO ===
        {execute_body}
'''


class SkillCreatorSkill(BaseSkill):
    """Crea, modifica, evalúa y optimiza nuevas skills de forma autónoma."""

    @property
    def name(self) -> str:
        return "SkillCreatorSkill"

    @property
    def description(self) -> str:
        return "Crea, modifica, evalúa y optimiza nuevas habilidades de Noddoo de forma autónoma."

    def get_intents(self) -> List[str]:
        return ["CREATE_SKILL", "MODIFY_SKILL", "LIST_SKILLS", "DELETE_SKILL"]

    def get_training_data(self) -> List[Tuple[str, str]]:
        return [
            ("crea una nueva skill para", "CREATE_SKILL"),
            ("crea una habilidad que", "CREATE_SKILL"),
            ("aprende a hacer", "CREATE_SKILL"),
            ("enséñate a", "CREATE_SKILL"),
            ("programate para poder", "CREATE_SKILL"),
            ("añade la capacidad de", "CREATE_SKILL"),
            ("quiero que puedas", "CREATE_SKILL"),
            ("modifica la skill", "MODIFY_SKILL"),
            ("actualiza la habilidad", "MODIFY_SKILL"),
            ("mejora la skill de", "MODIFY_SKILL"),
            ("qué skills tienes", "LIST_SKILLS"),
            ("lista tus habilidades", "LIST_SKILLS"),
            ("qué puedes hacer", "LIST_SKILLS"),
            ("cuáles son tus skills", "LIST_SKILLS"),
            ("elimina la skill", "DELETE_SKILL"),
            ("borra la habilidad", "DELETE_SKILL"),
        ]

    def extract_params(self, intent: str, text: str) -> Dict[str, Any]:
        return {"raw_text": text, "intent": intent}

    def execute(self, intent: str, params: Dict[str, Any]) -> str:
        """Crear, modificar o eliminar una skill según el intent recibido.

        INVARIANTE DE SEGURIDAD (REQ-005): este método NO se auto-protege. Asume estar
        gateado por el punto central (`security_manager.require_confirmation()`), que
        `skills/skill_manager.py:execute()` y `_make_gated_tool_fn()` ejecutan con los
        intents `CREATE_SKILL`/`MODIFY_SKILL`/`DELETE_SKILL` (YELLOW) antes de
        invocarlo. No llamarlo directamente sin pasar por `skill_manager`: quedaría sin
        confirmación. (`LIST_SKILLS` es GREEN y no requiere confirmación.)
        """
        if intent == "CREATE_SKILL":
            return self._create_skill(params.get("raw_text", ""))
        elif intent == "MODIFY_SKILL":
            return self._modify_skill(params.get("raw_text", ""))
        elif intent == "DELETE_SKILL":
            return self._delete_skill(params.get("raw_text", ""))
        return f"No entendí qué operación realizar sobre las skills{vocative()}."

    # ─────────────────────────────────────────────────────────────────
    #  CREAR SKILL
    # ─────────────────────────────────────────────────────────────────
    def _create_skill(self, user_request: str) -> str:
        """Genera una nueva skill completa a partir de una descripción."""
        try:
            from ai.llm_provider import generate_response

            system_prompt = f"""Eres un experto en Python y en la arquitectura de Noddoo.
Tu tarea es generar código Python COMPLETO y FUNCIONAL para una nueva skill.

REGLAS ESTRICTAS:
1. El código DEBE heredar de BaseSkill
2. DEBE implementar: name, description, get_intents(), get_training_data(), execute()
3. El nombre del archivo debe ser snake_case (ej: web_browser_skill.py)
4. El nombre de la clase debe ser PascalCase (ej: WebBrowserSkill)
5. Responde ÚNICAMENTE con un bloque de código Python válido entre triple backticks
6. NO expliques, NO añadas texto extra fuera del bloque de código
7. El método execute() DEBE retornar un string con el resultado

Plantilla de referencia:
{SKILL_TEMPLATE}

Genera la skill completa según lo que pide el usuario.
El código debe ser completamente funcional y no tener errores de sintaxis.
"""
            messages = [{"role": "user", "content": (
                f"Necesito que crees una skill con esta descripción: {user_request}\n\n"
                "Responde SOLO con el bloque ```python ... ``` con el código completo."
            )}]

            response = generate_response(messages, system_prompt)
            return self._process_generated_code(response, user_request)

        except Exception as e:
            return f"{vocative_start()}ocurrió un error al generar la skill: {str(e)}"

    def _process_generated_code(self, llm_response: str, original_request: str) -> str:
        """Extrae, valida y guarda el código generado por el LLM."""
        import re

        # 1. Extraer bloque de código Python
        code_match = re.search(r'```python\s*(.*?)\s*```', llm_response, re.DOTALL)
        if not code_match:
            # Intentar sin el lenguaje especificado
            code_match = re.search(r'```\s*(.*?)\s*```', llm_response, re.DOTALL)

        if not code_match:
            return (
                f"{vocative_start()}el motor de IA no generó código válido. "
                "Intente reformular la petición con más detalles."
            )

        code = code_match.group(1).strip()

        # 2. Validar sintaxis Python (sin ejecutar)
        try:
            ast.parse(code)
        except SyntaxError as e:
            return (
                f"{vocative_start()}detecté un error de sintaxis en el código generado "
                f"(línea {e.lineno}: {e.msg}). No lo instalé para proteger el sistema. "
                "Intente de nuevo para que el LLM lo regenere."
            )

        # 3. Extraer nombre de clase y generar nombre de archivo
        class_match = re.search(r'class\s+(\w+)\s*\(', code)
        if not class_match:
            return f"{vocative_start()}no pude identificar el nombre de la clase en el código generado."

        class_name = class_match.group(1)
        # Convertir PascalCase a snake_case para el nombre de archivo
        file_name = re.sub(r'(?<!^)(?=[A-Z])', '_', class_name).lower()
        if not file_name.endswith('_skill'):
            file_name += '_skill'
        file_name += '.py'

        # 4. Verificar que no sobreescriba archivos del sistema
        protected = ['base_skill.py', 'skill_manager.py', 'skill_creator_skill.py', '__init__.py']
        if file_name in protected:
            return f"{vocative_start()}no puedo sobreescribir el archivo protegido del sistema: {file_name}"

        # 5. Guardar el archivo
        skill_path = os.path.join(SKILLS_DIR, file_name)
        already_existed = os.path.exists(skill_path)

        with open(skill_path, 'w', encoding='utf-8') as f:
            f.write(f'# Skill generada automáticamente por SkillCreator de Noddoo\n')
            f.write(f'# Petición original: {original_request[:100]}\n')
            f.write(f'# ─────────────────────────────────────────────────────────\n\n')
            f.write(code)

        # 6. Intentar recarga en caliente del sistema de skills
        reload_msg = self._reload_skill_manager()

        action = "actualizada" if already_existed else "creada e instalada"
        return (
            f"✅ {vocative_start()}la skill **{class_name}** ha sido {action} exitosamente.\n"
            f"📁 Archivo: `skills/{file_name}`\n"
            f"🔄 {reload_msg}\n"
            f"Ya puede usar la nueva habilidad inmediatamente."
        )

    # ─────────────────────────────────────────────────────────────────
    #  MODIFICAR SKILL
    # ─────────────────────────────────────────────────────────────────
    def _modify_skill(self, user_request: str) -> str:
        """Modifica una skill existente con el LLM."""
        import re

        # Buscar qué skill quiere modificar
        skill_files = self._get_skill_files()
        target_file = None

        for sf in skill_files:
            skill_id = sf.replace('_skill.py', '').replace('_', ' ').lower()
            if skill_id in user_request.lower() or sf.replace('.py', '') in user_request.lower():
                target_file = sf
                break

        if not target_file:
            skills_list = ', '.join([s.replace('.py', '') for s in skill_files])
            return (
                f"{vocative_start()}no identifiqué qué skill desea modificar. "
                f"Las skills disponibles son: {skills_list}"
            )

        # Leer código actual
        skill_path = os.path.join(SKILLS_DIR, target_file)
        with open(skill_path, 'r', encoding='utf-8') as f:
            current_code = f.read()

        from ai.llm_provider import generate_response

        system_prompt = """Eres un experto Python. El usuario quiere modificar una skill existente de Noddoo.
Recibirás el código actual y las instrucciones de modificación.
Responde ÚNICAMENTE con el código Python COMPLETO modificado entre triple backticks.
Mantén la estructura BaseSkill intacta. No expliques nada."""

        messages = [{"role": "user", "content": (
            f"Código actual de la skill:\n```python\n{current_code}\n```\n\n"
            f"Instrucción de modificación: {user_request}\n\n"
            "Responde solo con el código completo modificado."
        )}]

        response = generate_response(messages, system_prompt)
        return self._process_generated_code(response, f"Modificación: {user_request}")

    # ─────────────────────────────────────────────────────────────────
    #  LISTAR SKILLS
    # ─────────────────────────────────────────────────────────────────
    def _list_skills(self) -> str:
        """Lista todas las skills instaladas con su descripción."""
        try:
            from skills.skill_manager import skill_manager
            skills = skill_manager.get_all_skills()

            if not skills:
                return f"{vocative_start()}actualmente no hay skills modulares cargadas."

            lines = ["📦 **Skills instaladas en Noddoo:**\n"]
            for skill in skills:
                intents = skill.get_intents()
                lines.append(
                    f"• **{skill.name}** — {skill.description}\n"
                    f"  Intents: {', '.join(intents) if intents else 'ninguno'}"
                )

            lines.append(f"\nTotal: {len(skills)} skill(s) activa(s).")
            return "\n".join(lines)
        except Exception as e:
            return f"Error al listar skills: {str(e)}"

    # ─────────────────────────────────────────────────────────────────
    #  ELIMINAR SKILL
    # ─────────────────────────────────────────────────────────────────
    def _delete_skill(self, user_request: str) -> str:
        """Elimina una skill del sistema."""
        skill_files = self._get_skill_files()
        protected = ['base_skill.py', 'skill_manager.py', 'skill_creator_skill.py', '__init__.py']
        target_file = None

        for sf in skill_files:
            skill_id = sf.replace('_skill.py', '').replace('_', ' ').lower()
            if skill_id in user_request.lower():
                target_file = sf
                break

        if not target_file:
            return f"{vocative_start()}no identifiqué qué skill desea eliminar. Especifique el nombre."

        if target_file in protected:
            return f"{vocative_start()}no puedo eliminar el archivo protegido del sistema: {target_file}"

        skill_path = os.path.join(SKILLS_DIR, target_file)
        os.remove(skill_path)
        self._reload_skill_manager()
        return f"✅ {vocative_start()}la skill `{target_file}` ha sido eliminada del sistema."

    # ─────────────────────────────────────────────────────────────────
    #  UTILIDADES
    # ─────────────────────────────────────────────────────────────────
    def _get_skill_files(self) -> List[str]:
        """Retorna lista de archivos .py en la carpeta skills."""
        return [
            f for f in os.listdir(SKILLS_DIR)
            if f.endswith('.py') and not f.startswith('__')
        ]

    def _reload_skill_manager(self) -> str:
        """Recarga el SkillManager en caliente para detectar nuevas skills."""
        try:
            from skills import skill_manager as sm_module
            importlib.reload(sm_module)
            # Forzar recarga de la instancia global
            sm_module.skill_manager._discover_skills()
            return "✅ Sistema de skills recargado en caliente."
        except Exception as e:
            return f"⚠️ La skill fue guardada pero reinicia el sistema para activarla: {str(e)}"
