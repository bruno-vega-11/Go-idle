@echo off
REM Lanzador del IDE del compilador (Windows).
REM Usa el Python del sistema (que incluye tkinter). Si tienes varios Python,
REM puedes cambiar "python" por la ruta completa a python.exe.
cd /d "%~dp0"
python ide.py
if errorlevel 1 (
    echo.
    echo El IDE termino con un error. Revisa el mensaje de arriba.
    pause
)
