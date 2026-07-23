# Regla: Git — O.R.I.O.N.

## Commits
- Los hace el usuario manualmente. Ningún agente ejecuta `git commit`.
- Al terminar `orion-dev` o cuando `orion-qa` apruebe, entregar únicamente el mensaje sugerido:
```
📝 MENSAJE DE COMMIT SUGERIDO:
──────────────────────────────
feat(REQ-XXX): descripción breve

- Detalle 1
- Detalle 2
```

## Push y merge
- Nunca ejecutar `git push`, `git merge` ni `git rebase`.
- Nunca crear una rama sin preguntar antes al humano.

## Checklist antes de entregar el mensaje de commit
```
[ ] orion-qa aprobó (pruebas/qa-audit-XXX.md con veredicto ✅ COMPLETADO)
[ ] El humano hizo la prueba manual final y dio OK
[ ] requirements.txt actualizado si hay nuevas dependencias
[ ] Sin API keys ni tokens hardcodeados
[ ] Sin except: pass silencioso
[ ] El mensaje de commit incluye el REQ (feat(REQ-XXX): ...)
```

## Rama de trabajo
- Se registra en `REQ-XXX-context.md` bajo "Estado actual > Rama git".
- Si no hay rama activa y el cambio lo amerita: preguntar al humano antes de asumir una.
