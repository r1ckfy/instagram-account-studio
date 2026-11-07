@echo off
setlocal
cd /d "%~dp0"
set "VPY=.venv\Scripts\python.exe"

if not exist "%VPY%" (
    echo [INFO] Criando ambiente virtual .venv ...
    where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
    if not exist "%VPY%" (
        echo [ERRO] Python nao encontrado. Instale o Python 3.12+ em https://www.python.org/downloads/
        echo        e marque "Add python.exe to PATH" durante a instalacao.
        pause
        exit /b 1
    )
)

"%VPY%" -c "import sys; sys.exit(sys.version_info < (3, 10))" || (
    echo [ERRO] E necessario Python 3.10 ou superior. Recomendado: 3.12+.
    pause
    exit /b 1
)

"%VPY%" -c "import PySide6, selenium" >nul 2>nul || (
    echo [INFO] Instalando dependencias - pode levar alguns minutos na primeira vez...
    "%VPY%" -m pip install --upgrade pip -q
    "%VPY%" -m pip install -r requirements.txt || (
        echo [ERRO] Falha ao instalar dependencias. Verifique sua conexao com a internet.
        pause
        exit /b 1
    )
)

echo [INFO] Abrindo Instagram Account Studio...
start "" ".venv\Scripts\pythonw.exe" main.py
endlocal
