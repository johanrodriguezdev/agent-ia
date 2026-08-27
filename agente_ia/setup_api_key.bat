@echo off
setlocal enabledelayedexpansion

echo ======================================================
echo     O.R.I.O.N — CONFIGURAR ANTHROPIC API KEY
echo ======================================================
echo.
echo Este script configura tu clave de API de Anthropic
echo como variable de entorno permanente en Windows.
echo.
echo Puedes obtener tu API key en:
echo   https://console.anthropic.com/
echo.
echo ======================================================

set /p API_KEY="Pega tu API key aqui (sk-ant-...): "

if "!API_KEY!"=="" (
    echo.
    echo [ERROR] No ingresaste ninguna clave. Cancelando.
    pause
    exit /b
)

:: Verificar que empiece con sk-ant-
echo !API_KEY! | findstr /r "^sk-ant-" >nul
if %errorlevel% neq 0 (
    echo.
    echo [ADVERTENCIA] La clave no parece tener el formato correcto.
    echo Las claves de Anthropic empiezan con "sk-ant-..."
    echo.
    set /p CONFIRM="Deseas continuar de todas formas? (s/n): "
    if /i "!CONFIRM!" neq "s" (
        echo Cancelado.
        pause
        exit /b
    )
)

:: Guardar como variable de entorno del USUARIO (permanente, no necesita admin)
setx ANTHROPIC_API_KEY "!API_KEY!"

echo.
echo ======================================================
echo   [OK] API key configurada correctamente.
echo.
echo   IMPORTANTE: Debes CERRAR y REABRIR la terminal
echo   (o reiniciar VS Code) para que O.R.I.O.N la detecte.
echo ======================================================
echo.

:: Verificar instalación de anthropic
python -c "import anthropic" >nul 2>&1
if %errorlevel% neq 0 (
    echo [1/1] Instalando libreria anthropic...
    pip install anthropic
    echo.
    echo [OK] Libreria instalada.
) else (
    echo [OK] Libreria anthropic ya esta instalada.
)

echo.
echo ======================================================
echo   O.R.I.O.N ya puede usar Claude como cerebro.
echo   Prueba preguntarle algo que no sea un comando,
echo   como: "O.R.I.O.N, que es la inteligencia artificial?"
echo ======================================================
echo.
pause
