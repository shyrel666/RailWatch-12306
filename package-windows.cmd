@echo off
setlocal EnableExtensions

cd /d "%~dp0"

echo.
echo === RailWatch 12306 Windows Packaging ===
echo.

where node >nul 2>nul || goto missing_node
where npm >nul 2>nul || goto missing_npm
rem The runtime is frozen with the Python pinned in .python-version. Stop here,
rem before anything is changed, when that interpreter is not installed.
node scripts/build-runtime.mjs --check || goto missing_python

set "PACKAGE_VERSION=%~1"
set "INSTALL_DEPS=%~2"
if "%PACKAGE_VERSION%"=="" (
  set /p PACKAGE_VERSION=Enter package version, for example 0.2.0: 
)

if "%PACKAGE_VERSION%"=="" goto missing_version

node -e "const v=process.argv[1]; if(!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(v)){console.error('Invalid version: '+v); process.exit(1)}" "%PACKAGE_VERSION%" || goto failed

echo.
echo [1/5] Setting package version to %PACKAGE_VERSION%
call npm version "%PACKAGE_VERSION%" --no-git-tag-version --allow-same-version || goto failed

echo.
echo [2/5] Checking Node dependencies
if /i "%INSTALL_DEPS%"=="--install-deps" goto install_node_deps
if exist "node_modules\.package-lock.json" (
  echo Skipping Node dependencies. Use "%~nx0 %PACKAGE_VERSION% --install-deps" to reinstall.
) else (
  goto install_node_deps
)
goto after_node_deps

:install_node_deps
echo Installing Node dependencies
call npm ci || goto failed

:after_node_deps

echo.
echo [3/5] Checking Python packaging environment
if /i not "%INSTALL_DEPS%"=="--install-deps" goto keep_python_env
if exist "build\python-venv" rmdir /s /q "build\python-venv" || goto failed
echo Removed build\python-venv. The runtime build recreates it from requirements.lock.
goto after_python_env

:keep_python_env
echo The runtime build keeps build\python-venv in step with requirements.lock.
echo Use "%~nx0 %PACKAGE_VERSION% --install-deps" to recreate it.

:after_python_env

echo.
echo Cleaning previous release output
if exist "release" rmdir /s /q "release" || goto failed

echo.
echo [4/5] Building Windows installer
call npm run package || goto failed

echo.
echo Validating updater metadata assets
node -e "const fs=require('fs'), path=require('path'); const latest=fs.readFileSync('release/latest.yml','utf8'); const names=[...latest.matchAll(/^\s*(?:path|url):\s*['\"]?(.+?)['\"]?\s*$/gm)].map(m=>m[1]); for (const name of new Set(names)) { if (!fs.existsSync(path.join('release', name))) { console.error('release/latest.yml references missing asset: '+name); process.exit(1); } }" || goto failed

echo.
echo [5/5] Packaging complete
echo Installer:
dir /b "release\*.exe" 2>nul
echo.
echo Updater metadata:
if exist "release\latest.yml" (
  echo release\latest.yml
) else (
  echo WARNING: release\latest.yml was not found.
)
echo.
echo Release assets to upload:
echo   release\*.exe
echo   release\*.blockmap
echo   release\latest.yml
echo.
pause
exit /b 0

:missing_node
echo ERROR: Node.js was not found in PATH.
pause
exit /b 1

:missing_npm
echo ERROR: npm was not found in PATH.
pause
exit /b 1

:missing_python
echo ERROR: The Python version pinned in .python-version is not installed. See the message above.
pause
exit /b 1

:missing_version
echo ERROR: package version is required.
pause
exit /b 1

:failed
echo.
echo ERROR: Packaging failed.
pause
exit /b 1
