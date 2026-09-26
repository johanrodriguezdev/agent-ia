"""Prueba real del navegador por CDP, dentro del contenedor Linux (REQ-069).

No usa internet: sirve una página local desde el propio contenedor, así la prueba no
depende de la red y es repetible.
"""
import http.server
import os
import socketserver
import sys
import threading

sys.path.insert(0, "/app")

PAGINA = b"""<!doctype html><html><head><meta charset="utf-8"><title>Pagina de prueba</title></head>
<body>
  <h1>Informe trimestral</h1>
  <p>La produccion subio 12,5 % frente al trimestre anterior.</p>
  <a href="#seccion">Ver el detalle</a>
  <button id="b">Aceptar</button>
  <input type="text" placeholder="Buscar" />
  <div id="resultado">nada todavia</div>
  <script>
    document.getElementById('b').addEventListener('click', () => {
      document.getElementById('resultado').textContent = 'boton pulsado';
    });
  </script>
</body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGINA)))
        self.end_headers()
        self.wfile.write(PAGINA)

    def log_message(self, *a):
        pass


servidor = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
puerto = servidor.server_address[1]
threading.Thread(target=servidor.serve_forever, daemon=True).start()

from os_integration import navegador, navegador_cdp

print("1. La fachada delega fuera de Windows")
print("   _ES_WINDOWS =", navegador._ES_WINDOWS, "→ debe ser False")

print("2. ¿Hay con qué manejar un navegador?")
print("   disponible:", navegador_cdp.disponible(), "|", navegador_cdp._ejecutable())

try:
    print("3. Abrir una página (por la fachada, como lo haría el agente)")
    print("  ", navegador.abrir(f"http://127.0.0.1:{puerto}/"))

    print("4. Listar las pestañas")
    print("  ", navegador.listar_pestanas().replace("\n", "\n   "))

    print("5. Leer el texto de la página")
    texto = navegador.texto_de_pagina()
    print("  ", repr(texto[:90]))
    assert "Informe trimestral" in texto, "no leyó el título"
    assert "12,5" in texto, "no leyó el cuerpo"

    print("6. Qué se puede usar en la página")
    resumen = navegador.resumen_de_pagina()
    print("  ", resumen.replace("\n", "\n   "))
    assert "Aceptar" in resumen and "Ver el detalle" in resumen

    print("7. Pulsar el botón por su texto")
    print("  ", navegador.accionar("aceptar"))
    despues = navegador.texto_de_pagina()
    assert "boton pulsado" in despues, "el clic no tuvo efecto en la página"
    print("   la página reaccionó: 'boton pulsado' aparece en el texto")

    print("8. Escribir en el campo de búsqueda")
    print("  ", navegador.accionar("buscar", "palma de aceite"))

    print("9. Pedir algo que no existe")
    print("  ", navegador.accionar("un boton que no existe")[:80])

    print("10. Cerrar la pestaña")
    print("  ", navegador.cerrar_pestana("prueba"))

    print("\nTODO BIEN: el ciclo completo funciona contra un Chromium real.")
finally:
    navegador_cdp.cerrar_navegador()
    servidor.shutdown()
