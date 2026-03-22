@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

echo.
echo ======================================================
echo   GLASS — Configurar Bots de Comunicación
echo ======================================================
echo.

:: Instalar dependencias
echo [1/3] Instalando dependencias de bots...
pip install python-telegram-bot==20.7 discord.py openai-whisper -q
echo     OK — dependencias instaladas.
echo.

:: Leer config actual
set CONFIG_FILE=%~dp0config.json
if not exist "%CONFIG_FILE%" (
    echo {"agent_name": "glass"} > "%CONFIG_FILE%"
)

:: Token de Telegram
echo [2/3] Configurar Bot de Telegram
echo.
echo     Para crear tu bot:
echo     1. Abre Telegram y busca @BotFather
echo     2. Escribe /newbot
echo     3. Dale un nombre y un username (ej: GlassAssistantBot)
echo     4. Copia el token que te da
echo.
set /p TELEGRAM_TOKEN="Pega tu token de Telegram (o ENTER para omitir): "

if not "!TELEGRAM_TOKEN!"=="" (
    setx TELEGRAM_BOT_TOKEN "!TELEGRAM_TOKEN!" >nul
    echo     OK — Token de Telegram guardado.
) else (
    echo     Omitido.
)
echo.

:: Token de Discord
echo [3/3] Configurar Bot de Discord
echo.
echo     Para crear tu bot:
echo     1. Ve a https://discord.com/developers/applications
echo     2. New Application → Bot → Reset Token → copia el token
echo     3. En "Privileged Gateway Intents" activa "Message Content Intent"
echo     4. En OAuth2 → URL Generator selecciona: bot + applications.commands
echo        Permisos: Send Messages, Read Messages, Use Slash Commands
echo     5. Usa la URL generada para invitar el bot a tu servidor
echo.
set /p DISCORD_TOKEN="Pega tu token de Discord (o ENTER para omitir): "

if not "!DISCORD_TOKEN!"=="" (
    setx DISCORD_BOT_TOKEN "!DISCORD_TOKEN!" >nul
    echo     OK — Token de Discord guardado.
) else (
    echo     Omitido.
)

echo.
echo ======================================================
echo   Configuración completada.
echo.
echo   Para iniciar los bots ejecuta:
echo     python start_bots.py
echo.
echo   IMPORTANTE: Cierra y reabre la terminal para que
echo   Windows cargue las variables de entorno.
echo ======================================================
echo.
pause
