import os
import re
import tempfile
import subprocess
import logging
from typing import Dict, List, Tuple, Any
from skills.base_skill import BaseSkill
from ai.llm_provider import generate_response

logger = logging.getLogger(__name__)

class CodeExecutionSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "CodeExecutionSkill"

    @property
    def description(self) -> str:
        return "Permite escribir y ejecutar código Python en tiempo real para resolver tareas complejas de automatización, cálculo u obtención de datos (Estilo OpenInterpreter/OpenClaw)."

    def get_intents(self) -> List[str]:
        return ["EXECUTE_CODE"]

    def get_training_data(self) -> List[Tuple[str, str]]:
        return [
            ("crea un script en python que", "EXECUTE_CODE"),
            ("escribe y ejecuta un codigo para", "EXECUTE_CODE"),
            ("escribe un programa que", "EXECUTE_CODE"),
            ("ejecuta un script que", "EXECUTE_CODE"),
            ("programa en python algo para", "EXECUTE_CODE"),
            ("haz un script de automatizacion para", "EXECUTE_CODE"),
            ("crea un codigo que", "EXECUTE_CODE"),
            ("ejecuta codigo python para", "EXECUTE_CODE"),
            ("programa un script que", "EXECUTE_CODE")
        ]

    def extract_params(self, intent: str, text: str) -> Dict[str, Any]:
        params = {"prompt": text}
        m = re.search(r'(?:script|codigo|programa|python)(?: que| para)?\s+(.+)', text.lower())
        if m:
            params["task"] = m.group(1).strip()
        else:
            params["task"] = text
        return params

    def execute(self, intent: str, params: Dict[str, Any]) -> str:
        """Generar y ejecutar un script Python para resolver la tarea pedida.

        INVARIANTE DE SEGURIDAD (REQ-005): este método NO se auto-protege. Asume estar
        gateado por el punto central (`security_manager.require_confirmation()`), que
        `skills/skill_manager.py:execute()` y `_make_gated_tool_fn()` ejecutan con el
        intent `EXECUTE_CODE` (YELLOW) antes de invocarlo. No llamarlo directamente
        sin pasar por `skill_manager`: quedaría sin confirmación.
        """
        task = params.get("task", "")
        if not task:
            return "Señor, por favor sea más específico con lo que desea que programe y ejecute."

        system_prompt = (
            "Eres el núcleo lógico de un agente de IA autónomo (Estilo OpenClaw/Devin). "
            "Debes resolver la tarea escribiendo un script en Python. Responde SOLO con el código de Python válido encerrado entre ```python y ```. "
            "Reglas críticas:\n"
            "1. Asume que tienes permisos completos. Usa librerías estándar donde sea posible.\n"
            "2. El código obligatoriamente debe usar 'print' explícito para mostrar el output final.\n"
            "3. Asegúrate de manejar errores y no crear interfaces gráficas."
        )
        
        messages = [{"role": "user", "content": f"Escribe un script de Python para: {task}"}]
        max_retries = 3
        last_code = ""
        output_msg = ""
        
        for attempt in range(max_retries):
            try:
                # 1. Le pedimos a la IA que escriba o corrija el código
                response = generate_response(messages, system_prompt)
                
                code_match = re.search(r'```python\s*(.*?)\s*```', response, re.DOTALL)
                if code_match:
                    code = code_match.group(1).strip()
                else:
                    code = response.strip()
                    if "print" not in code and "=" not in code:
                        return f"No logré generar un código válido. La IA respondió: {response}"
                
                last_code = code

                # 2. Guardar en un archivo temporal
                with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode='w', encoding='utf-8') as f:
                    tmp_path = f.name
                    f.write(code)

                # 3. Ejecutar en modo aislado (-I: sin site-packages, sin .pth)
                try:
                    result = subprocess.run(
                        ["python", "-I", "-u", tmp_path],
                        capture_output=True, text=True, timeout=45,
                        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
                    )
                    stdout = result.stdout.strip()
                    stderr = result.stderr.strip()
                    
                    if result.returncode == 0:
                        output_msg = f"\n*Salida:*\n{stdout}" if stdout else "\nEl script se ejecutó con éxito pero no imprimió nada (faltó el print)."
                        # Eliminamos el archivo temp de forma limpia dentro del try/finally
                        break  # ¡Ejecución exitosa!
                    else:
                        # Falló, hacer auto-healing
                        error_log = stderr if stderr else stdout
                        output_msg = f"\n*Error final tras {attempt+1} intentos:*\n{error_log}"
                        
                        # Le mandamos el error a Gemini para que lo arregle en la siguiente iteración
                        messages.append({"role": "assistant", "content": f"```python\n{code}\n```"})
                        messages.append({"role": "user", "content": f"Al ejecutar tu código, falló con este error en consola:\n{error_log}\nPor favor, corrige el error y devuelve el script Python completo y arreglado."})
                        print(f"[CodeExecutionSkill] Self-Healing Intento {attempt+1}/{max_retries}...")
                        
                except subprocess.TimeoutExpired:
                    output_msg = "Señor, el script tardó demasiado tiempo en ejecutarse y fue abortado."
                    break
                finally:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
                        
            except Exception as api_err:
                return f"Hubo un problema de conexión al intentar generar el código: {api_err}"
                
        return (
            f"He operado de manera autónoma (Self-Healing mode) resolviendo su tarea.\n\n"
            f"*Último Código Generado:*\n```python\n{last_code[:500]}{'...' if len(last_code)>500 else ''}\n```\n"
            f"*Resultado:*{output_msg}"
        )
