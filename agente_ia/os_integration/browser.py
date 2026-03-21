import webbrowser
import urllib.parse

def search_google(query: str) -> str:
    search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
    webbrowser.open(search_url)
    return f"Búsqueda lanzada en Google para: '{query}'"
