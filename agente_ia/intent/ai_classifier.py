import os
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC
from sklearn.pipeline import Pipeline
from intent.intentions import Intent
from nlp.parser import clean_text

class IntentClassifierSystem:
    def __init__(self):
        self.model_path = os.path.join(os.path.dirname(__file__), 'saved_model.pkl')
        self.pipeline = None
        self._load_or_train()
        
    def _get_training_data(self):
        """
        Dataset extendido con +350 ejemplos para cubrir todas las intenciones
        incluyendo las nuevas de system_actions, CALCULATE, CHAT, etc.
        """
        data = [
            # ── OPEN_APP ─────────────────────────────────────────────────────
            ("abre chrome", Intent.OPEN_APP.value),
            ("abre google chrome", Intent.OPEN_APP.value),
            ("inicia el bloc de notas", Intent.OPEN_APP.value),
            ("ejecuta la calculadora", Intent.OPEN_APP.value),
            ("abre la aplicacion de word", Intent.OPEN_APP.value),
            ("arranca spotify", Intent.OPEN_APP.value),
            ("abre spotify", Intent.OPEN_APP.value),
            ("abre mi navegador", Intent.OPEN_APP.value),
            ("abre firefox", Intent.OPEN_APP.value),
            ("lanza el explorador de archivos", Intent.OPEN_APP.value),
            ("inicia visual studio code", Intent.OPEN_APP.value),
            ("abre el paint", Intent.OPEN_APP.value),
            ("ejecuta el administrador de tareas", Intent.OPEN_APP.value),
            ("abre excel", Intent.OPEN_APP.value),
            ("abre powerpoint", Intent.OPEN_APP.value),
            ("arranca la terminal", Intent.OPEN_APP.value),
            ("abre el cmd", Intent.OPEN_APP.value),
            ("inicia discord", Intent.OPEN_APP.value),
            ("abre zoom", Intent.OPEN_APP.value),
            ("lanza teams", Intent.OPEN_APP.value),
            ("abre vlc", Intent.OPEN_APP.value),
            ("inicia notepad", Intent.OPEN_APP.value),
            ("ejecuta whatsapp", Intent.OPEN_APP.value),
            ("abre telegram", Intent.OPEN_APP.value),
            ("inicia el panel de control", Intent.OPEN_APP.value),

            # ── CLOSE_APP ────────────────────────────────────────────────────
            ("cierra chrome", Intent.CLOSE_APP.value),
            ("cierra google chrome", Intent.CLOSE_APP.value),
            ("cierra el navegador", Intent.CLOSE_APP.value),
            ("cierra firefox", Intent.CLOSE_APP.value),
            ("cierra spotify", Intent.CLOSE_APP.value),
            ("cierra discord", Intent.CLOSE_APP.value),
            ("cierra word", Intent.CLOSE_APP.value),
            ("cierra excel", Intent.CLOSE_APP.value),
            ("cierra el bloc de notas", Intent.CLOSE_APP.value),
            ("cierra la aplicacion", Intent.CLOSE_APP.value),
            ("mata el proceso de chrome", Intent.CLOSE_APP.value),
            ("termina el programa", Intent.CLOSE_APP.value),
            ("cierra el programa", Intent.CLOSE_APP.value),
            ("cierra teams", Intent.CLOSE_APP.value),
            ("cierra edge", Intent.CLOSE_APP.value),
            ("cierra vlc", Intent.CLOSE_APP.value),
            ("cierra zoom", Intent.CLOSE_APP.value),
            ("cierra steam", Intent.CLOSE_APP.value),
            ("mata spotify", Intent.CLOSE_APP.value),
            ("termina chrome", Intent.CLOSE_APP.value),
            ("finaliza el programa de discord", Intent.CLOSE_APP.value),
            ("cierra el explorador", Intent.CLOSE_APP.value),
            ("cierra visual studio code", Intent.CLOSE_APP.value),
            ("cierra obs", Intent.CLOSE_APP.value),
            ("cierra brave", Intent.CLOSE_APP.value),

            # ── SEARCH_WEB ───────────────────────────────────────────────────
            ("busca inteligencia artificial en google", Intent.SEARCH_WEB.value),
            ("busca en internet gatos", Intent.SEARCH_WEB.value),
            ("quien es el presidente de Francia", Intent.SEARCH_WEB.value),
            ("busca que es la fotosintesis", Intent.SEARCH_WEB.value),
            ("googleame sobre los agujeros negros", Intent.SEARCH_WEB.value),
            ("busca fotos de perritos", Intent.SEARCH_WEB.value),
            ("busca en google recetas de cocina", Intent.SEARCH_WEB.value),
            ("busca informacion de la luna", Intent.SEARCH_WEB.value),
            ("busca noticias de hoy", Intent.SEARCH_WEB.value),
            ("busca como hacer pizza", Intent.SEARCH_WEB.value),
            ("busca en google python tutorial", Intent.SEARCH_WEB.value),
            ("busca precio del bitcoin", Intent.SEARCH_WEB.value),
            ("busca el partido de hoy", Intent.SEARCH_WEB.value),
            ("googleame recetas faciles", Intent.SEARCH_WEB.value),
            ("busca en internet como aprender a tocar guitarra", Intent.SEARCH_WEB.value),

            # ── OPEN_FOLDER ──────────────────────────────────────────────────
            ("abre la carpeta de descargas", Intent.OPEN_FOLDER.value),
            ("abre mis documentos", Intent.OPEN_FOLDER.value),
            ("muestra el directorio de musica", Intent.OPEN_FOLDER.value),
            ("abrir la carpeta de fotos", Intent.OPEN_FOLDER.value),
            ("ve a mi escritorio", Intent.OPEN_FOLDER.value),
            ("abre la carpeta videos", Intent.OPEN_FOLDER.value),
            ("muestra mis imagenes", Intent.OPEN_FOLDER.value),
            ("abrir la carpeta de programas", Intent.OPEN_FOLDER.value),
            ("ir a mis documentos", Intent.OPEN_FOLDER.value),
            ("navega a mis descargas", Intent.OPEN_FOLDER.value),

            # ── LIST_FILES ───────────────────────────────────────────────────
            ("que archivos hay en mi escritorio", Intent.LIST_FILES.value),
            ("lista los archivos de la carpeta", Intent.LIST_FILES.value),
            ("muestrame que hay aqui", Intent.LIST_FILES.value),
            ("ver archivos", Intent.LIST_FILES.value),
            ("lista mis descargas", Intent.LIST_FILES.value),
            ("que hay en mis documentos", Intent.LIST_FILES.value),
            ("que archivos tengo en descargas", Intent.LIST_FILES.value),
            ("muestra los archivos de mi escritorio", Intent.LIST_FILES.value),
            ("ver contenido de la carpeta", Intent.LIST_FILES.value),

            # ── CREATE_FILE ──────────────────────────────────────────────────
            ("crea un archivo llamado notas", Intent.CREATE_FILE.value),
            ("haz un archivo de texto", Intent.CREATE_FILE.value),
            ("crea el archivo prueba", Intent.CREATE_FILE.value),
            ("nuevo archivo", Intent.CREATE_FILE.value),
            ("creame un archivo", Intent.CREATE_FILE.value),
            ("crea un documento llamado informe", Intent.CREATE_FILE.value),
            ("hacer archivo de texto vacio", Intent.CREATE_FILE.value),

            # ── GET_TIME ─────────────────────────────────────────────────────
            ("que hora es", Intent.GET_TIME.value),
            ("dime la hora", Intent.GET_TIME.value),
            ("me puedes decir la hora", Intent.GET_TIME.value),
            ("dame la hora actual", Intent.GET_TIME.value),
            ("que hora tenemos", Intent.GET_TIME.value),
            ("cual es la hora ahora", Intent.GET_TIME.value),
            ("a que hora estamos", Intent.GET_TIME.value),

            # ── WIKIPEDIA_SUMMARY ────────────────────────────────────────────
            ("que es el sistema solar", Intent.WIKIPEDIA_SUMMARY.value),
            ("quien fue albert einstein", Intent.WIKIPEDIA_SUMMARY.value),
            ("resumen de leonardo da vinci", Intent.WIKIPEDIA_SUMMARY.value),
            ("explicame sobre el imperio romano", Intent.WIKIPEDIA_SUMMARY.value),
            ("wikipedia que es la gravedad", Intent.WIKIPEDIA_SUMMARY.value),
            ("dime quien es nicola tesla", Intent.WIKIPEDIA_SUMMARY.value),
            ("que es la inteligencia artificial", Intent.WIKIPEDIA_SUMMARY.value),
            ("quien fue napoleon bonaparte", Intent.WIKIPEDIA_SUMMARY.value),
            ("que es la fotosintesis", Intent.WIKIPEDIA_SUMMARY.value),
            ("explicame que es el adn", Intent.WIKIPEDIA_SUMMARY.value),
            ("informacion sobre youtube", Intent.WIKIPEDIA_SUMMARY.value),
            ("que es python el lenguaje", Intent.WIKIPEDIA_SUMMARY.value),
            ("hablame de la segunda guerra mundial", Intent.WIKIPEDIA_SUMMARY.value),
            ("quien invento el telefono", Intent.WIKIPEDIA_SUMMARY.value),
            ("que es el universo", Intent.WIKIPEDIA_SUMMARY.value),
            ("como funciona la memoria ram", Intent.WIKIPEDIA_SUMMARY.value),
            ("que es bitcoin", Intent.WIKIPEDIA_SUMMARY.value),

            # ── TAKE_SCREENSHOT ──────────────────────────────────────────────
            ("toma una captura", Intent.TAKE_SCREENSHOT.value),
            ("haz una captura de pantalla", Intent.TAKE_SCREENSHOT.value),
            ("toma un screenshot", Intent.TAKE_SCREENSHOT.value),
            ("pantallazo", Intent.TAKE_SCREENSHOT.value),
            ("captura de pantalla ahora", Intent.TAKE_SCREENSHOT.value),
            ("toma foto de la pantalla", Intent.TAKE_SCREENSHOT.value),
            ("screenshot ya", Intent.TAKE_SCREENSHOT.value),

            # ── SYSTEM_CONTROL ───────────────────────────────────────────────
            ("sube el volumen", Intent.SYS_VOL_UP.value),
            ("ponlo mas fuerte", Intent.SYS_VOL_UP.value),
            ("volumen mas alto", Intent.SYS_VOL_UP.value),
            ("aumenta el volumen", Intent.SYS_VOL_UP.value),
            ("mas volumen por favor", Intent.SYS_VOL_UP.value),
            ("baja el volumen", Intent.SYS_VOL_DOWN.value),
            ("mas bajo", Intent.SYS_VOL_DOWN.value),
            ("baja la musica", Intent.SYS_VOL_DOWN.value),
            ("reduce el volumen", Intent.SYS_VOL_DOWN.value),
            ("silencia el equipo", Intent.SYS_MUTE.value),
            ("ponlo en mute", Intent.SYS_MUTE.value),
            ("quita el sonido", Intent.SYS_MUTE.value),
            ("silencio total", Intent.SYS_MUTE.value),
            ("apaga el ordenador", Intent.SYS_POWER_OFF.value),
            ("apaga la pc", Intent.SYS_POWER_OFF.value),
            ("apagar equipo", Intent.SYS_POWER_OFF.value),
            ("apagate y descansa", Intent.SYS_POWER_OFF.value),
            ("apaga la computadora", Intent.SYS_POWER_OFF.value),
            ("apagar windows", Intent.SYS_POWER_OFF.value),

            # ── RECALL_MEMORY ────────────────────────────────────────────────
            ("te acuerdas de", Intent.RECALL_MEMORY.value),
            ("que dije sobre", Intent.RECALL_MEMORY.value),
            ("que respondiste acerca de", Intent.RECALL_MEMORY.value),
            ("recuerdas lo que", Intent.RECALL_MEMORY.value),
            ("busca en tu memoria", Intent.RECALL_MEMORY.value),
            ("que hablamos de", Intent.RECALL_MEMORY.value),
            ("cual fue mi ultima orden", Intent.RECALL_MEMORY.value),
            ("que me dijiste antes", Intent.RECALL_MEMORY.value),
            ("recuerda lo que te dije", Intent.RECALL_MEMORY.value),
            ("que dijiste sobre", Intent.RECALL_MEMORY.value),
            ("busca en tus registros", Intent.RECALL_MEMORY.value),
            ("en que hablamos", Intent.RECALL_MEMORY.value),

            # ── TEACH_COMMAND ────────────────────────────────────────────────
            ("aprende comando", Intent.TEACH_COMMAND.value),
            ("aprende un nuevo comando", Intent.TEACH_COMMAND.value),
            ("orion aprende comando", Intent.TEACH_COMMAND.value),
            ("quiero enseñarte un comando", Intent.TEACH_COMMAND.value),
            ("enseñar comando", Intent.TEACH_COMMAND.value),
            ("aprende una nueva rutina", Intent.TEACH_COMMAND.value),
            ("graba una rutina", Intent.TEACH_COMMAND.value),
            ("aprende esto", Intent.TEACH_COMMAND.value),
            ("guarda esta rutina", Intent.TEACH_COMMAND.value),

            # ── PC_CLICK ─────────────────────────────────────────────────────
            ("haz clic en las coordenadas", Intent.PC_CLICK.value),
            ("clickea en", Intent.PC_CLICK.value),
            ("pulsa en la posicion", Intent.PC_CLICK.value),
            ("presiona el raton en", Intent.PC_CLICK.value),
            ("clic en posicion", Intent.PC_CLICK.value),
            ("haz click en", Intent.PC_CLICK.value),

            # ── PC_TYPE ──────────────────────────────────────────────────────
            ("escribe en el teclado", Intent.PC_TYPE.value),
            ("tipea", Intent.PC_TYPE.value),
            ("escribe la frase", Intent.PC_TYPE.value),
            ("introduce el texto", Intent.PC_TYPE.value),
            ("teclea el texto", Intent.PC_TYPE.value),

            # ── PC_SCROLL ────────────────────────────────────────────────────
            ("haz scroll hacia", Intent.PC_SCROLL.value),
            ("desplaza la pantalla hacia", Intent.PC_SCROLL.value),
            ("mueve la pagina para", Intent.PC_SCROLL.value),
            ("baja la pantalla", Intent.PC_SCROLL.value),
            ("sube la pantalla", Intent.PC_SCROLL.value),
            ("scroll", Intent.PC_SCROLL.value),
            ("desplazate hacia abajo", Intent.PC_SCROLL.value),

            # ── CALCULATE (NUEVO) ─────────────────────────────────────────────
            ("multiplica 40 por 60", Intent.CALCULATE.value),
            ("cuanto es 5 por 8", Intent.CALCULATE.value),
            ("cuanto es 100 dividido entre 4", Intent.CALCULATE.value),
            ("suma 15 mas 27", Intent.CALCULATE.value),
            ("resta 50 menos 13", Intent.CALCULATE.value),
            ("calcula 20 por 5", Intent.CALCULATE.value),
            ("cuanto es 7 al cuadrado", Intent.CALCULATE.value),
            ("cuanto es la raiz cuadrada de 81", Intent.CALCULATE.value),
            ("haz la operacion 45 mas 55", Intent.CALCULATE.value),
            ("divide 200 entre 8", Intent.CALCULATE.value),
            ("multiplica 12 por 12", Intent.CALCULATE.value),
            ("cuanto es 3 por 9", Intent.CALCULATE.value),
            ("calcula 1000 menos 250", Intent.CALCULATE.value),
            ("operacion matematica 6 por 7", Intent.CALCULATE.value),
            ("cuanto es 2 elevado a 10", Intent.CALCULATE.value),
            ("calcula el porcentaje de 200 el 15", Intent.CALCULATE.value),
            ("cual es el resultado de multiplicar 8 por 9", Intent.CALCULATE.value),
            ("cuanto es 500 dividido 25", Intent.CALCULATE.value),
            ("suma estos numeros 33 y 67", Intent.CALCULATE.value),
            ("cuantos es cien entre cuatro", Intent.CALCULATE.value),

            # ── SEARCH_FILES (NUEVO) ──────────────────────────────────────────
            ("busca el archivo reporte", Intent.SEARCH_FILES.value),
            ("busca archivos llamados notas", Intent.SEARCH_FILES.value),
            ("encuentra el archivo main py", Intent.SEARCH_FILES.value),
            ("busca mis archivos de excel", Intent.SEARCH_FILES.value),
            ("donde esta el archivo factura", Intent.SEARCH_FILES.value),
            ("busca un archivo llamado datos", Intent.SEARCH_FILES.value),
            ("encontrar archivos con nombre proyecto", Intent.SEARCH_FILES.value),

            # ── FOLDER_SIZE (NUEVO) ───────────────────────────────────────────
            ("cuanto pesa la carpeta documentos", Intent.FOLDER_SIZE.value),
            ("cuanto espacio ocupa descargas", Intent.FOLDER_SIZE.value),
            ("tamaño de la carpeta videos", Intent.FOLDER_SIZE.value),
            ("cuantos megas tiene la carpeta escritorio", Intent.FOLDER_SIZE.value),
            ("peso de la carpeta musica", Intent.FOLDER_SIZE.value),
            ("cuanto ocupa mi carpeta de proyectos", Intent.FOLDER_SIZE.value),

            # ── FIND_LARGEST (NUEVO) ──────────────────────────────────────────
            ("cual es la carpeta mas grande", Intent.FIND_LARGEST.value),
            ("que carpeta ocupa mas espacio", Intent.FIND_LARGEST.value),
            ("muestra las carpetas mas pesadas", Intent.FIND_LARGEST.value),
            ("cuales son las carpetas mas grandes de mi pc", Intent.FIND_LARGEST.value),
            ("analiza que esta ocupando mas espacio", Intent.FIND_LARGEST.value),
            ("ranking de carpetas por tamaño", Intent.FIND_LARGEST.value),

            # ── SYSTEM_INFO (NUEVO) ───────────────────────────────────────────
            ("informacion del sistema", Intent.SYSTEM_INFO.value),
            ("que sistema operativo tengo", Intent.SYSTEM_INFO.value),
            ("dime info de mi pc", Intent.SYSTEM_INFO.value),
            ("cuales son las especificaciones de mi computadora", Intent.SYSTEM_INFO.value),
            ("estado del sistema", Intent.SYSTEM_INFO.value),
            ("specs de mi pc", Intent.SYSTEM_INFO.value),
            ("como esta mi computadora", Intent.SYSTEM_INFO.value),

            # ── CPU_INFO (NUEVO) ──────────────────────────────────────────────
            ("cuanto cpu estoy usando", Intent.CPU_INFO.value),
            ("uso del procesador", Intent.CPU_INFO.value),
            ("como esta mi cpu", Intent.CPU_INFO.value),
            ("uso de procesador ahora", Intent.CPU_INFO.value),
            ("cuantos nucleos tiene mi procesador", Intent.CPU_INFO.value),
            ("info del cpu", Intent.CPU_INFO.value),
            ("estado del procesador", Intent.CPU_INFO.value),
            ("cuanto porcentaje de cpu uso", Intent.CPU_INFO.value),

            # ── RAM_INFO (NUEVO) ──────────────────────────────────────────────
            ("cuanta ram tengo", Intent.RAM_INFO.value),
            ("uso de memoria ram", Intent.RAM_INFO.value),
            ("como esta la ram", Intent.RAM_INFO.value),
            ("cuanta memoria disponible tengo", Intent.RAM_INFO.value),
            ("info de la memoria", Intent.RAM_INFO.value),
            ("estado de la ram", Intent.RAM_INFO.value),
            ("memoria disponible", Intent.RAM_INFO.value),
            ("cuanto ram esta libre", Intent.RAM_INFO.value),

            # ── UNKNOWN (fallback) ────────────────────────────────────────────
            ("hola como estas", Intent.UNKNOWN.value),
            ("no entiendo", Intent.UNKNOWN.value),
            ("bla bla bla", Intent.UNKNOWN.value),
        ]
        
        texts  = [clean_text(item[0]) for item in data]
        labels = [item[1] for item in data]
        
        # Integración Modular: Añadir datos de skills
        try:
            from skills.skill_manager import skill_manager
            skill_data = skill_manager.get_all_training_data()
            for text, intent in skill_data:
                texts.append(clean_text(text))
                labels.append(intent)
        except Exception as e:
            print(f"[Aviso] No se pudieron cargar datos modulares: {e}")
            
        return texts, labels

    def _load_or_train(self):
        """Carga el modelo pre-entrenado o lo entrena si no existe."""
        if os.path.exists(self.model_path):
            self.pipeline = joblib.load(self.model_path)
        else:
            self._train()

    def _train(self):
        """
        Entrena el pipeline de Machine Learning (TF-IDF + SVM).
        Usa n-gramas (1,3) para capturar frases más ricas.
        """
        texts, labels = self._get_training_data()
        
        self.pipeline = Pipeline([
            ('tfidf', TfidfVectorizer(ngram_range=(1, 3), analyzer='word', min_df=1)),
            ('clf',   LinearSVC(random_state=42, C=1.5, max_iter=3000))
        ])
        
        self.pipeline.fit(texts, labels)
        joblib.dump(self.pipeline, self.model_path)
        print("[IA] Modelo SVM re-entrenado y guardado correctamente.")
        
    def force_retrain(self):
        """Pública: forza el re-entrenamiento aunque exista un modelo previo."""
        if os.path.exists(self.model_path):
            os.remove(self.model_path)
        self._train()

    def predict(self, text: str) -> str:
        """Infiere la intención del texto crudo (Maneja Enum y Strings dinámicos)."""
        clean = clean_text(text)
        prediction = self.pipeline.predict([clean])[0]
        return str(prediction)
