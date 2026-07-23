#!/usr/bin/env node
// Hook PreToolUse (Bash|PowerShell): bloquea `git commit` y `git push`.
// Ver .claude/rules/git.md — los commits y pushes son manuales.

let data = "";
process.stdin.on("data", (chunk) => (data += chunk));
process.stdin.on("end", () => {
  let cmd = "";
  try {
    const input = JSON.parse(data);
    cmd = input?.tool_input?.command || "";
  } catch {
    console.log("{}");
    return;
  }

  const bloqueado = /(^|[;&|]|\s)git\s+(commit|push)(\s|$)/i.test(cmd);

  if (bloqueado) {
    console.log(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason:
          "git commit / git push son manuales — el usuario los ejecuta. Ver .claude/rules/git.md. " +
          "Si ya pasaste QA y el humano validó, entrega el mensaje de commit sugerido sin ejecutarlo.",
      },
    }));
  } else {
    console.log("{}");
  }
});
