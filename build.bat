@echo off
setlocal
cd /d "%~dp0"
set "VPY=.venv\Scripts\python.exe"
set "APPNAME=InstagramAccountStudio"
set "EXE=dist\%APPNAME%\%APPNAME%.exe"

echo.
echo ==== [1/6] Verificando ambiente ====
if not exist "%VPY%" (
    where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
)
if not exist "%VPY%" (
    echo [ERRO] Python nao encontrado. Instale o Python 3.12+ e tente novamente.
    goto :fail
)
"%VPY%" -c "import sys; print('Python', sys.version.split()[0]); sys.exit(sys.version_info < (3, 10))" || goto :fail

echo.
echo ==== [2/6] Instalando dependencias ====
"%VPY%" -m pip install --upgrade pip -q || goto :fail
"%VPY%" -m pip install -r requirements.txt -q || goto :fail

echo.
echo ==== [3/6] Executando testes ====
"%VPY%" -m pytest -q -p no:cacheprovider || goto :fail

echo.
echo ==== [4/6] Empacotando com PyInstaller (distribuicao em pasta) ====
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --name %APPNAME% ^
    --add-data "demo;demo" --add-data "exemplos;exemplos" --collect-data selenium main.py || goto :fail

echo.
echo ==== [5/6] Verificando executavel ====
if not exist "%EXE%" (
    echo [ERRO] Executavel nao foi gerado: %EXE%
    goto :fail
)
if not exist "dist\%APPNAME%\_internal\exemplos\fichas_exemplo.txt" (
    echo [ERRO] Modelos de exemplo nao foram incluidos no pacote.
    goto :fail
)
if not exist "dist\%APPNAME%\_internal\demo\cadastro_demo.html" (
    echo [ERRO] Pagina demo nao foi incluida no pacote.
    goto :fail
)

echo.
echo ==== [6/6] Concluido ====
echo [OK] Testes aprovados
echo [OK] Executavel: %CD%\%EXE%
echo [OK] Distribua a pasta inteira: %CD%\dist\%APPNAME%
echo      Os dados do app ficam em dist\%APPNAME%\data (criada na primeira execucao).
echo.
pause
exit /b 0

:fail
echo.
echo [ERRO] Build interrompido. Veja a mensagem acima.
pause
exit /b 1
