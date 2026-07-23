#!/usr/bin/env node
// Hook PostToolUse (Write|Edit): recuerda las reglas de .claude/rules/ cuando se toca
// código de O.R.I.O.N. — API keys hardcodeadas, except: pass, os.system sin validación,
// skills sin BaseSkill, etc.
// Solo informa (additionalContext) — nunca bloquea.

let data = "";
process.stdin.on("data", (chunk) => (data += chunk));
process.stdin.on("end", () => {
  let input;
  try {
    input = JSON.parse(data);
  } catch {
    console.log("{}");
    return;
  }

  const filePath = input?.tool_input?.file_path || "";
  const contenido = input?.tool_input?.content ?? input?.tool_input?.new_string ?? "";

  const avisos = [];

  // Detectar API keys hardcodeadas
  if (/\.py$/i.test(filePath)) {
    const apiKeyPatterns = [
      /api[-_]?key\s*=\s*["'](sk-|AI)/i,
      /ANTHROPIC_API_KEY\s*=\s*["']/i,
      /OPENAI_API_KEY\s*=\s*["']/i,
      /DEEPSEEK_API_KEY\s*=\s*["']/i,
      /GEMINI_API_KEY\s*=\s*["']/i,
      /telegram[-_]?token\s*=\s*["']/i,
      /discord[-_]?token\s*=\s*["']/i,
    ];
    if (apiKeyPatterns.some((p) => p.test(contenido))) {
      avisos.push(
        "⚠️  Posible API key hardcodeada — ver .claude/rules/security-levels.md. " +
        "Las claves deben ir en variables de entorno o .env, no en código."
      );
    }

    // Detectar except: pass silencioso
    if (/except\s*(Exception)?\s*:\s*pass\b/.test(contenido)) {
      avisos.push(
        "⚠️  Se detectó `except: pass` silencioso — ver .claude/rules/python-style.md. " +
        "Siempre registrar el error antes de ignorarlo."
      );
    }

    // Detectar os.system() sin validación
    if (/os\.system\s*\(/.test(contenido)) {
      avisos.push(
        "⚠️  Se detectó os.system() — ver .claude/rules/security-levels.md. " +
        "Asegúrate de validar el input y clasificar la acción como Verde/Amarillo/Rojo."
      );
    }
  }

  // Detectar skills que no heredan de BaseSkill
  if (/\/skills\/.*\.py$/i.test(filePath) && /class\s+\w+/.test(contenido)) {
    if (!/BaseSkill/.test(contenido)) {
      avisos.push(
        "⚠️  Posible skill sin BaseSkill — ver .claude/rules/skills.md. " +
        "Los skills deben heredar de skills/base_skill.py:BaseSkill."
      );
    }
  }

  // Detectar config.json con tokens
  if (/config\.json$/i.test(filePath) && /telegram_token|api_key/i.test(contenido)) {
    avisos.push(
      "⚠️  Se editó config.json con tokens — ver .claude/rules/security-levels.md. " +
      "Considera mover secretos a variables de entorno."
    );
  }

  if (avisos.length === 0) {
    console.log("{}");
    return;
  }

  console.log(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: "PostToolUse",
      additionalContext: avisos.join(" "),
    },
  }));
});
