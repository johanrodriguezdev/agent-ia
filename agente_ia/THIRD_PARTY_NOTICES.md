# Avisos de terceros

O.R.I.O.N. se distribuye bajo la **GNU General Public License v3.0** (ver `LICENSE`). La
licencia la impone la dependencia principal de la interfaz: PyQt6 y PyQt6-WebEngine se
publican bajo GPL v3 (o licencia comercial de Riverbank Computing), y un programa que los
enlaza tiene que distribuirse en términos compatibles. Migrar a PySide6 (LGPL) permitiría
otra licencia; hoy no está previsto.

Este archivo lista el código y los recursos de terceros que viajan **dentro del
repositorio**. Las dependencias que se instalan con `pip install -r requirements.txt` no
se copian aquí: cada una conserva su propia licencia en su paquete.

## Código incluido en el repositorio

| Recurso | Ubicación | Autor / copyright | Licencia |
|---|---|---|---|
| qwebchannel.js | `ui/webview/frontend/vendor/qwebchannel.js` | © 2016 The Qt Company Ltd.; © 2016 Klarälvdalens Datakonsult AB (KDAB) | LGPL-3.0-only, GPL-2.0-only o GPL-3.0-only (se usa bajo GPL-3.0). La cabecera SPDX original se conserva en el archivo. |
| xterm.js, addon-fit, addon-search, xterm.css | `ui/webview/frontend/vendor/` | © 2017-2019 The xterm.js authors; © 2014-2016 SourceLair Private Company; © 2012-2013 Christopher Jeffrey | MIT — texto completo en `ui/webview/frontend/vendor/LICENSE-xterm.txt` |
| Inter (Regular, Medium, Bold, `.woff2`) | `ui/webview/frontend/fonts/` | © 2016 The Inter Project Authors (https://github.com/rsms/inter) | SIL Open Font License 1.1 — texto completo en `ui/webview/frontend/fonts/LICENSE-Inter.txt` |

## Material de referencia

`workspace/referencias/openclaw/*.md` son notas de análisis del proyecto
[OpenClaw](https://github.com/openclaw/openclaw) escritas para este repositorio. Para
explicar cada mecanismo transcriben fragmentos literales de su código TypeScript.

- Copyright (c) 2026 OpenClaw Foundation. Licencia MIT: se permite copiar y redistribuir
  el código con la condición de conservar este aviso de copyright y el de permiso.
- Los fragmentos se reproducen con fines de estudio y están marcados como tales en cada
  documento. **Ningún archivo de código de O.R.I.O.N. copia ni traduce código de OpenClaw**:
  el proyecto está escrito en Python de forma independiente y solo toma ideas de su
  documentación pública (aislamiento de entradas no confiables, gateway de canales,
  política por canal).

Texto del aviso de permiso MIT que acompaña a esos fragmentos:

> Permission is hereby granted, free of charge, to any person obtaining a copy of this
> software and associated documentation files (the "Software"), to deal in the Software
> without restriction, including without limitation the rights to use, copy, modify, merge,
> publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
> to whom the Software is furnished to do so, subject to the following conditions: The above
> copyright notice and this permission notice shall be included in all copies or substantial
> portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

## Dependencias con licencia distinta de MIT/BSD/Apache que conviene conocer

| Paquete | Licencia | Nota |
|---|---|---|
| PyQt6, PyQt6-WebEngine, PyQt6-Qt6 | GPL-3.0 / comercial | Es lo que fija la licencia del proyecto. |
| PyMuPDF (`pymupdf`) | AGPL-3.0 / comercial (Artifex) | Se usa para leer PDF y maquetarlos sin Office. El AGPL solo añade obligaciones si el programa se ofrece como servicio por red; O.R.I.O.N. corre en el equipo del usuario. |
| edge-tts | LGPL-3.0 | Síntesis de voz. Se usa como biblioteca sin modificar. |

Si añades un recurso de terceros al repositorio (una fuente, un script vendorizado, un
icono), agrégalo a la tabla de arriba con su licencia y conserva su archivo de licencia al
lado del recurso.
