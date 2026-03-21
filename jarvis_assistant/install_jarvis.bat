@echo off
setlocal enabledelayedexpansion

echo ======================================================
echo           JARVIS ASSISTANT - INSTALLER
echo ======================================================
echo.

:: 1. Comprobar Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no esta instalado. Por favor instale Python 3.10+ para continuar.
    pause
    exit /b
)

echo [OK] Python detectado.

:: 2. Instalar dependencias
echo.
echo [1/3] Instalando dependencias necesarias...
python -m pip install --upgrade pip
pip install -r requirements.txt

:: 3. Instalar psutil específicamente para info de sistema
pip install psutil

:: 4. Comprobar FFmpeg (necesario para voz)
echo.
echo [2/3] Verificando soporte multimedia...
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ADVERTENCIA] FFmpeg no detectado en el PATH.
    echo El reconocimiento de voz y TTS podrian fallar.
    echo Descargue ffmpeg y agreguelo al PATH si tiene problemas.
) else (
    echo [OK] FFmpeg detectado.
)

:: 5. Crear acceso directo para modo Manos Libres
echo.
echo [3/3] Creando lanzador de Jarvis (Modo Manos Libres)...
(
echo @echo off
echo echo Iniciando JARVIS en modo manos libres...
echo python -c "from main import main; main(boot_mode='3')"
echo pause
) > Iniciar_Jarvis_Manos_Libres.bat

echo.
echo ======================================================
echo   INSTALACION COMPLETADA, SEOR.
echo   Use 'Iniciar_Jarvis_Manos_Libres.bat' para empezar.
echo ======================================================
pause
