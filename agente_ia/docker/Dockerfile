# O.R.I.O.N. en Linux — imagen de escritorio (REQ-067)
#
# No es un servidor: adentro corre la aplicación completa, con su ventana PyQt6 +
# QtWebEngine, su voz y su terminal. El contenedor toma prestada la pantalla del equipo
# (el socket X11) y su audio; por eso el lanzador `orion.sh` existe y no se levanta con un
# `docker run` a secas.
#
# Va en dos etapas porque PyAudio se compila desde el código fuente —no publica rueda para
# Linux— y para eso hace falta un compilador entero. Compilarlo en una etapa aparte deja
# esos ~250 MB de herramientas fuera de la imagen final, que es la que se distribuye.

# ============================================================================ compilación
FROM python:3.12-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

# `build-essential` para compilar, `portaudio19-dev` para las cabeceras de PyAudio.
RUN apt-get update && apt-get install --no-install-recommends -y \
    build-essential portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

# Se instala en el Python del sistema, NO en un entorno virtual. Con un venv en /opt hay
# que meterlo en el PATH, y un shell de login (`bash -l`, que es lo que abre la terminal
# embebida del agente) vuelve a armar el PATH desde `/etc/profile` y se lo lleva por
# delante: adentro del contenedor, `python` pasaba a ser el del sistema y **ninguna**
# dependencia se encontraba. Se descubrió probando la imagen, no leyéndola.

# torch va antes y desde el índice de solo-CPU: la rueda normal arrastra CUDA y son varios
# gigabytes de GPU que en un escritorio sin tarjeta NVIDIA no se usan nunca.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt


# ================================================================================ imagen
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    QT_QPA_PLATFORM=xcb \
    # QtWebEngine dentro de un contenedor no puede usar su sandbox (necesita privilegios
    # que no le damos a propósito). El aislamiento acá lo pone el contenedor.
    QTWEBENGINE_DISABLE_SANDBOX=1

# Qué se instala y por qué, que en una imagen de escritorio no es obvio:
#   - Las bibliotecas de Qt y de Chromium no vienen con PyQt6: la rueda trae el binario de
#     Qt, pero enlaza contra las del sistema. Sin ellas la ventana no abre y el error que
#     imprime Qt («could not load the Qt platform plugin "xcb"») no dice cuál falta.
#   - ffmpeg trae `ffplay`, que es con lo que el agente reproduce lo que dice
#     (`ui/tts_engine.py`). Sin él, el agente responde pero no se escucha.
#   - LibreOffice ocupa el lugar que en Windows ocupa Office: convertir un .docx a un PDF
#     que se vea igual. Sin él el PDF se maqueta a mano y se nota (REQ-040/065).
#   - Tesseract reemplaza al OCR de Windows (`Windows.Media.Ocr`), que no existe acá.
RUN apt-get update && apt-get install --no-install-recommends -y \
    # --- Qt 6: plataforma xcb, teclado y OpenGL
    libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
    libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 \
    libxcb-xkb1 libxkbcommon0 libdbus-1-3 libfontconfig1 libfreetype6 \
    # --- QtWebEngine (Chromium embebido). `libxtst6` y `libxkbfile1` no son opcionales:
    #     sin ellos el import falla con «libXtst.so.6: cannot open shared object file»,
    #     que es el nombre del archivo y no el del paquete — se encontró con `ldd` sobre
    #     libQt6WebEngineCore, no adivinando.
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libxtst6 libxkbfile1 libxi6 \
    # --- Voz: ffplay reproduce el TTS; libportaudio2 es lo que PyAudio necesita en marcha
    ffmpeg libportaudio2 \
    # --- Documentos: el PDF fiel que en Windows hace Office
    libreoffice-writer libreoffice-calc libreoffice-impress \
    # --- OCR: el reemplazo de Windows.Media.Ocr
    tesseract-ocr tesseract-ocr-spa \
    # --- Control del escritorio (pyautogui necesita scrot) y abrir aplicaciones
    scrot xdg-utils \
    # --- Herramientas que el agente usa de verdad
    git curl ca-certificates \
    # --- Tipografías: sin esto los documentos y la interfaz salen con cuadraditos
    fonts-dejavu fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Las dependencias van al Python del sistema, no a un entorno virtual: así `python` las
# encuentra venga de donde venga el PATH (ver la nota de la etapa de compilación).
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# ---------------------------------------------------------------- el usuario
# Corre como un usuario normal, no como root: lo que el agente escriba en las carpetas
# montadas tiene que quedar tuyo y no de root. El UID se pasa en el build para que
# coincida con el del equipo (ver `orion.sh`).
ARG UID=1000
ARG GID=1000
RUN groupadd -g "${GID}" orion 2>/dev/null || true \
    && useradd -m -u "${UID}" -g "${GID}" -s /bin/bash orion \
    && mkdir -p /app /datos \
    && chown -R "${UID}:${GID}" /app /datos

WORKDIR /app
COPY --chown=${UID}:${GID} . /app
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER orion

# El estado (config, memoria, logs) vive en /datos, que se monta desde el equipo: una
# imagen nueva no puede llevarse por delante tus conversaciones. El código sigue leyendo
# `/app/config.json`; el entrypoint deja ese archivo apuntando a /datos.
ENV ORION_DATA_DIR=/datos \
    HOME=/home/orion

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "main.py"]
