@echo off
chcp 65001 >nul
REM ============================================================
REM ustxPlayer Nuitka build script
REM
REM Usage:
REM   1. Run: build.bat
REM      (Nuitka and C compiler will be auto-resolved)
REM
REM Output: dist\ustxPlayer.dist\ustxPlayer.exe
REM ============================================================

setlocal

REM Auto-detect Python - try py launcher first, fall back to PATH
where py >nul 2>&1
if not errorlevel 1 (
    set PYTHON=py -3.12
) else (
    set PYTHON=python
)

REM Change to script directory
cd /d "%~dp0"

echo ============================================================
echo  ustxPlayer Nuitka build
echo ============================================================
echo.

echo [1/3] Checking Nuitka...
%PYTHON% -m pip show Nuitka >nul 2>&1
if errorlevel 1 (
    echo Nuitka not found, installing...
    %PYTHON% -m pip install -U "Nuitka[all]"
)
echo Nuitka ready
echo.

echo [2/3] Locating PySide6 multimedia plugins...
for /f "delims=" %%i in ('%PYTHON% -c "import PySide6,os;print(os.path.dirname(PySide6.__file__))"') do set PYSIDE6_DIR=%%i
set MM_PLUGINS=%PYSIDE6_DIR%\plugins\multimedia

if not exist "%MM_PLUGINS%\ffmpegmediaplugin.dll" (
    echo ERROR: PySide6 multimedia plugins not found!
    echo   Looked for: %MM_PLUGINS%\ffmpegmediaplugin.dll
    echo   Audio playback will NOT work without these plugins.
    echo   Make sure PySide6 is installed: pip install PySide6
    pause
    exit /b 1
)
echo   Plugins:  %MM_PLUGINS%
echo   PySide6:  %PYSIDE6_DIR%
echo.

echo [3/3] Starting compilation (first run may take 10-20 mins)...
echo.

REM Build command
REM Exclude large unused deps pulled in transitively by qfluentwidgets[full]:
REM   scipy / pandas / matplotlib / sklearn / PIL / numpy / pytest / PyInstaller
%PYTHON% -m nuitka ^
    --standalone ^
    --enable-plugin=pyside6 ^
    --include-package=qfluentwidgets ^
    --include-package-data=qfluentwidgets ^
    --include-package=qframelesswindow ^
    --include-package-data=qframelesswindow ^
    --include-package=yaml ^
    --include-package=win32api ^
    --include-package=win32gui ^
    --include-package=win32print ^
    --include-data-files="icon.ico=icon.ico" ^
    --include-data-files="Terms.txt=Terms.txt" ^
    --include-data-files="%MM_PLUGINS%\ffmpegmediaplugin.dll=PySide6/qt-plugins/multimedia/ffmpegmediaplugin.dll" ^
    --include-data-files="%MM_PLUGINS%\windowsmediaplugin.dll=PySide6/qt-plugins/multimedia/windowsmediaplugin.dll" ^
    --include-data-files="%PYSIDE6_DIR%\avcodec-61.dll=avcodec-61.dll" ^
    --include-data-files="%PYSIDE6_DIR%\avformat-61.dll=avformat-61.dll" ^
    --include-data-files="%PYSIDE6_DIR%\avutil-59.dll=avutil-59.dll" ^
    --include-data-files="%PYSIDE6_DIR%\swresample-5.dll=swresample-5.dll" ^
    --include-data-files="%PYSIDE6_DIR%\swscale-8.dll=swscale-8.dll" ^
    --nofollow-import-to=PySide6.QtWebEngineCore ^
    --nofollow-import-to=PySide6.QtWebEngineWidgets ^
    --nofollow-import-to=PySide6.QtWebEngineQuick ^
    --nofollow-import-to=PySide6.QtWebChannel ^
    --nofollow-import-to=PySide6.QtPdf ^
    --nofollow-import-to=PySide6.QtPdfWidgets ^
    --nofollow-import-to=PySide6.QtQml ^
    --nofollow-import-to=PySide6.QtQuick ^
    --nofollow-import-to=PySide6.QtQuickWidgets ^
    --nofollow-import-to=PySide6.QtQuick3D ^
    --nofollow-import-to=PySide6.QtQuickControls2 ^
    --nofollow-import-to=PySide6.Qt3DCore ^
    --nofollow-import-to=PySide6.Qt3DRender ^
    --nofollow-import-to=PySide6.Qt3DInput ^
    --nofollow-import-to=PySide6.Qt3DLogic ^
    --nofollow-import-to=PySide6.Qt3DAnimation ^
    --nofollow-import-to=PySide6.Qt3DExtras ^
    --nofollow-import-to=PySide6.QtCharts ^
    --nofollow-import-to=PySide6.QtDataVisualization ^
    --nofollow-import-to=PySide6.QtDataVisualizationQml ^
    --nofollow-import-to=PySide6.QtChartsQml ^
    --nofollow-import-to=PySide6.QtScxml ^
    --nofollow-import-to=PySide6.QtSpatialAudio ^
    --nofollow-import-to=PySide6.QtTextToSpeech ^
    --nofollow-import-to=PySide6.QtWebSockets ^
    --nofollow-import-to=PySide6.QtBluetooth ^
    --nofollow-import-to=PySide6.QtSerialBus ^
    --nofollow-import-to=PySide6.QtSerialPort ^
    --nofollow-import-to=PySide6.QtSensors ^
    --nofollow-import-to=PySide6.QtRemoteObjects ^
    --nofollow-import-to=PySide6.QtNetworkAuth ^
    --nofollow-import-to=PySide6.QtNfc ^
    --nofollow-import-to=PySide6.QtStateMachine ^
    --nofollow-import-to=PySide6.QtHelp ^
    --nofollow-import-to=PySide6.QtDesigner ^
    --nofollow-import-to=PySide6.QtQuick3DAssetImport ^
    --nofollow-import-to=PySide6.QtOpenGLWidgets ^
    --nofollow-import-to=PySide6.QtPrintSupport ^
    --nofollow-import-to=PySide6.QtMultimediaWidgets ^
    --nofollow-import-to=PySide6.QtTest ^
    --nofollow-import-to=PySide6.QtUiTools ^
    --nofollow-import-to=PySide6.QtSql ^
    --nofollow-import-to=PySide6.QtConcurrent ^
    --nofollow-import-to=scipy ^
    --nofollow-import-to=pandas ^
    --nofollow-import-to=matplotlib ^
    --nofollow-import-to=sklearn ^
    --nofollow-import-to=PIL ^
    --nofollow-import-to=numpy ^
    --nofollow-import-to=pytest ^
    --nofollow-import-to=PyInstaller ^
    --noinclude-data-files="PySide6/qt-plugins/imageformats/qpdf.dll=PySide6/qt-plugins/imageformats/qpdf.dll" ^
    --noinclude-data-files="PySide6/qt6pdf.dll=PySide6/qt6pdf.dll" ^
    --windows-icon-from-ico="icon.ico" ^
    --windows-console-mode=disable ^
    --output-dir=dist ^
    --company-name="lyrinXD" ^
    --product-name="ustxPlayer" ^
    --file-version=26.30.0 ^
    --product-version=26.30.0 ^
    --file-description="ustxPlayer - USTX project visualizer" ^
    --output-filename="ustxPlayer.exe" ^
    --remove-output ^
    main.py

if errorlevel 1 (
    echo.
    echo ============================================================
    echo  Build failed! Check errors above.
    echo ============================================================
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Build successful!
echo ============================================================
echo.

REM Rename dist directory from main.dist to ustxPlayer.dist
if exist "dist\main.dist" (
    if exist "dist\ustxPlayer.dist" (
        rmdir /s /q "dist\ustxPlayer.dist"
    )
    rename "dist\main.dist" ustxPlayer.dist
)

echo  Output: dist\ustxPlayer.dist\
echo  Binary: dist\ustxPlayer.dist\ustxPlayer.exe
echo.
pause
