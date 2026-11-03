@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Nie znaleziono programu uruchamiającego Python (Python Launcher).
    echo Zainstaluj 64-bitową wersję Pythona 3 i zaznacz opcję dodania programu uruchamiającego.
    pause
    exit /b 1
)

if not exist ".venv-app\Scripts\python.exe" (
    echo Przygotowywanie środowiska aplikacji...
    py -3-64 -m venv ".venv-app"
    if errorlevel 1 (
        echo Nie udało się utworzyć 64-bitowego środowiska Pythona.
        pause
        exit /b 1
    )
)

echo Sprawdzanie architektury Pythona...
".venv-app\Scripts\python.exe" -c "import struct,sys; sys.exit(struct.calcsize('P') != 8)"
if errorlevel 1 (
    echo Środowisko .venv-app nie jest 64-bitowe albo Python nie uruchamia się poprawnie.
    echo Zamknij launcher, usuń folder .venv-app i uruchom ten plik ponownie.
    pause
    exit /b 1
)

echo Instalowanie lub sprawdzanie zależności...
".venv-app\Scripts\python.exe" -m pip install -r requirements-server.txt
if errorlevel 1 (
    echo Instalacja zależności nie powiodła się. Sprawdź połączenie z internetem i README.md.
    pause
    exit /b 1
)

if not exist ".venv-app\Scripts\pythonw.exe" (
    echo Nie znaleziono pythonw.exe w nowym środowisku.
    pause
    exit /b 1
)

start "" ".venv-app\Scripts\pythonw.exe" "server_manager.pyw"
exit /b 0
