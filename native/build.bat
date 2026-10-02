@echo off
REM Build ustx_yuv.dll (one-shot tool; the compiled DLL is committed to the repo).
REM Requires MSYS2 mingw-w64 UCRT64 gcc. Adjust GCC if installed elsewhere.

setlocal
set GCC=D:\msys64\ucrt64\bin\gcc.exe
if not exist "%GCC%" set GCC=gcc

"%GCC%" -shared -O2 -s -o "%~dp0ustx_yuv.dll" "%~dp0ustx_yuv.c"
if errorlevel 1 (
    echo BUILD FAILED
    pause
    exit /b 1
)
echo Built: %~dp0ustx_yuv.dll