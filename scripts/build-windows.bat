@echo off
REM scripts/build-windows.bat
REM Baut eine portable BTCRechnung.exe mit PyInstaller auf Windows
REM
REM Nutzung:
REM   scripts\build-windows.bat [version]
REM   Beispiel: scripts\build-windows.bat 1.0.0

cd /d "%~dp0\.."

set VERSION=%1
if "%VERSION%"=="" set VERSION=1.0.0

echo === BTCRechnung PyInstaller Build v%VERSION% ===
echo.

REM Python finden
where python >nul 2>nul
if %errorlevel% neq 0 (
    where py >nul 2>nul
    if %errorlevel% neq 0 (
        echo FEHLER: Python nicht gefunden!
        echo Bitte Python 3.11+ installieren.
        pause
        exit /b 1
    )
    set PYTHON=py
) else (
    set PYTHON=python
)

REM Virtuelle Umgebung erstellen falls nicht vorhanden
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

REM Abhängigkeiten installieren
echo Installiere Abhaengigkeiten...
pip install --upgrade pip -q
pip install -r requirements.txt -q
pip install pyinstaller -q

if %errorlevel% neq 0 (
    echo FEHLER: Abhaengigkeiten konnten nicht installiert werden.
    pause
    exit /b 1
)

REM Alte Builds entfernen
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

REM PyInstaller bauen
echo Starte PyInstaller...
python -m PyInstaller BTCRechnung.spec --clean --noconfirm
if %errorlevel% neq 0 (
    echo FEHLER: PyInstaller Build fehlgeschlagen.
    pause
    exit /b 1
)

REM data-Ordner erstellen
mkdir dist\BTCRechnung\data 2>nul
echo. > dist\BTCRechnung\data\.gitkeep

echo.
echo === Fertig ===
echo Ordner: dist\BTCRechnung\
echo Datei:  dist\BTCRechnung\BTCRechnung.exe
echo.
echo Zum Testen:
echo   cd dist\BTCRechnung
echo   BTCRechnung.exe
echo.
pause
