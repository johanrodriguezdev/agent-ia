"""Prueba si web_read puede leer un servicio de la red interna (SSRF)."""
import http.server
import socket
import sys
import threading

sys.path.insert(0, r"C:/Users/WHOAMI/Documents/Apps/agent-ia/agente_ia")

CONTENIDO = b"<html><body><h1>PANEL INTERNO</h1><p>SECRETO_DE_LA_RED_INTERNA</p></body></html>"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(CONTENIDO)))
        self.end_headers()
        self.wfile.write(CONTENIDO)

    def log_message(self, *a):
        pass


servidor = http.server.HTTPServer(("127.0.0.1", 0), Handler)
puerto = servidor.server_address[1]
threading.Thread(target=servidor.serve_forever, daemon=True).start()
print(f"servicio interno simulado en http://127.0.0.1:{puerto}")

from os_integration.web_search import leer_pagina

for etiqueta, url in (
    ("localhost", f"http://127.0.0.1:{puerto}/"),
    ("nombre localhost", f"http://localhost:{puerto}/"),
):
    texto = leer_pagina(url)
    alcanzado = "SECRETO_DE_LA_RED_INTERNA" in texto
    print(f"  {'!!! ALCANZADO' if alcanzado else 'OK  bloqueado'} | {etiqueta}: {texto[:70]!r}")

# El endpoint de metadatos de la nube: no responde en un equipo de escritorio, pero lo que
# importa es si la funcion lo RECHAZA por politica o si intenta conectarse igual.
texto = leer_pagina("http://169.254.169.254/latest/meta-data/")
print(f"\n  metadatos de nube -> {texto[:90]!r}")
print("  (si dice 'No pude abrir esa pagina: ConnectionError' es que INTENTO conectarse,")
print("   no que lo haya rechazado por politica)")

servidor.shutdown()
