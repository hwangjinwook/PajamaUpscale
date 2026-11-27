@echo off
chcp 65001 >nul
rem 파자마업스케일.exe 만들기(PyInstaller, exe 한 개 + engine 폴더).
rem   결과: dist\파자마업스케일\ 폴더 — 이 폴더를 통째로 옮기면 다른 컴퓨터에서도 돼요(파이썬 필요 없음)
rem     파자마업스케일.exe   화면 프로그램(아이콘·끌어 놓기 포함)
rem     engine\             AI 엔진(Real-ESRGAN ncnn-vulkan, 그래픽카드로 동작)과 모델
setlocal
cd /d "%~dp0"
set "OUT=%~dp0dist\파자마업스케일"
set "EXE_NAME=파자마업스케일.exe"
rem 중간 작업물은 OneDrive 밖에 둔다(OneDrive 가 동기화하느라 붙잡으면 「액세스 거부」로 실패해서)
set "WORK=%TEMP%\PajamaUpscale-build"

where python >nul 2>&1
if errorlevel 1 (
    echo 파이썬을 찾지 못했어요. exe 를 만들 때만 파이썬 3.9 이상이 필요해요.
    exit /b 1
)
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller 가 없어서 설치해요...
    python -m pip install --disable-pip-version-check pyinstaller
    if errorlevel 1 exit /b 1
)
python -c "import tkinterdnd2" >nul 2>&1
if errorlevel 1 (
    echo 끌어 놓기 라이브러리^(tkinterdnd2^)를 설치해요...
    python -m pip install --disable-pip-version-check tkinterdnd2
)
if not exist "%~dp0engine\realesrgan-ncnn-vulkan.exe" (
    echo engine 폴더에 AI 엔진이 없어요. README 의 「AI 엔진 넣기」를 보고 넣어 주세요.
    exit /b 1
)

echo [1/2] exe 만드는 중... 1~2분 걸려요.
python -m PyInstaller --noconfirm --clean --log-level WARN --onefile --windowed ^
    --name PajamaUpscale --icon "%~dp0icon.ico" --add-data "%~dp0icon.ico;." ^
    --collect-all tkinterdnd2 ^
    --distpath "%WORK%\dist" --workpath "%WORK%\work" --specpath "%WORK%" ^
    "%~dp0PajamaUpscale.pyw"
if errorlevel 1 (
    echo exe 만들기에 실패했어요. 위의 오류를 확인해 주세요.
    exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
copy /y "%WORK%\dist\PajamaUpscale.exe" "%OUT%\%EXE_NAME%" >nul
if errorlevel 1 (
    echo %EXE_NAME% 를 덮어쓰지 못했어요. 켜져 있는 파자마업스케일 창을 닫고 다시 해 주세요.
    exit /b 1
)

echo [2/2] AI 엔진 복사 중...
robocopy "%~dp0engine" "%OUT%\engine" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
    echo engine 폴더를 복사하지 못했어요.
    exit /b 1
)

echo.
echo 완료: %OUT%\%EXE_NAME%
exit /b 0
