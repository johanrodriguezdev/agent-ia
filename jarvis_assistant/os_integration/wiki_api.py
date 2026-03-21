import wikipedia

# La API de Wikipedia actualmente bloquea a los bots genéricos causando un fallo JSONDecodeError. 
# Requerimos un User-Agent único.
wikipedia.set_user_agent("JarvisAssistant/1.0 (johan@correo.com)")

# Fijamos el idioma de Wikipedia a Español
wikipedia.set_lang('es')

def get_wikipedia_summary(query: str) -> str:
    """
    Busca una consulta en wikipedia, si el tema es ambiguo o no existe, 
    devuelve un reporte de error elegante.
    Retorna comúnmente hasta 2 oraciones para no alargar la pantalla demasiado.
    """
    try:
        # intentamos buscar la página
        summary = wikipedia.summary(query, sentences=3)
        return f"Según mis bases de datos en Wikipedia:\n\n{summary}"
        
    except wikipedia.exceptions.DisambiguationError as e:
        opciones = ", ".join(e.options[:4]) # Máximo sugerimos 4
        return f"La búsqueda '{query}' es ambigua. Podría referirse a: {opciones}..."
    except wikipedia.exceptions.PageError:
        return f"No he encontrado información sobre '{query}' en mi base de datos enciclopédica."
    except Exception as e:
        return f"Hubo un fallo en la conexión de conocimiento externo: {e}"
