@echo off
cd /d "%~dp0"
where python >nul 2>&1
if %errorlevel%==0 (
    python "%~dp0app.py"
) else (
    py "%~dp0app.py"
)
if %errorlevel% neq 0 (
    echo.
    echo Erro ao iniciar o Conversor de Videos. Verifique se o Python esta instalado.
    pause
)
