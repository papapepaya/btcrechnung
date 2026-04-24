@echo off
cd /d "%~dp0"

REM Python-Befehl finden
where python >nul 2>nul
if %errorlevel% neq 0 (
    where py >nul 2>nul
    if %errorlevel% neq 0 (
        echo FEHLER: Python nicht gefunden!
        echo Bitte Python 3.11+ installieren und "Add to PATH" aktivieren.
        echo Download: https://www.python.org/downloads/
        pause
        exit /b 1
    )
    set PYTHON=py
) else (
    set PYTHON=python
)

if not exist .venv\Scripts\python.exe (
    echo Erstelle virtuelle Umgebung...
    %PYTHON% -m venv .venv
    if %errorlevel% neq 0 (
        echo FEHLER: Virtuelle Umgebung konnte nicht erstellt werden.
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

REM Pruefe ob uvicorn installiert ist, sonst Abhaengigkeiten (neu) installieren
python -c "import uvicorn" >nul 2>nul
if %errorlevel% neq 0 (
    echo Installiere Abhaengigkeiten...
    pip install --upgrade pip
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo.
        echo FEHLER: Abhaengigkeiten konnten nicht installiert werden.
        echo Loesche defekte virtuelle Umgebung...
        deactivate >nul 2>nul
        rmdir /s /q .venv
        echo Bitte starten Sie das Programm erneut.
        pause
        exit /b 1
    )
    REM Nach Installation nochmal pruefen
    python -c "import uvicorn" >nul 2>nul
    if %errorlevel% neq 0 (
        echo FEHLER: uvicorn konnte nicht installiert werden.
        deactivate >nul 2>nul
        rmdir /s /q .venv
        pause
        exit /b 1
    )
)

echo.
echo === BTCRechnung ===
echo Lokal:    http://127.0.0.1:8000
echo Netzwerk: http://%COMPUTERNAME%:8000
echo.
echo Strg+C zum Beenden
echo.

REM Browser nach 3 Sekunden oeffnen (Server-Start abwarten)
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:8000"

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

pause
