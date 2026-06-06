@echo off
chcp 65001 >nul
echo [*] Installing dependencies...
pip install -r requirements.txt pyinstaller

echo [*] Cleaning up old build files...
if exist build rd /s /q build
if exist dist rd /s /q dist

if not exist chromedriver.exe (
    echo [!] chromedriver.exe not found in project root.
    echo [!] The package will still build; users must provide ChromeDriver separately or keep it on PATH.
)

echo [*] Starting RailWatch 12306 packaging process (Directory Mode - More Stable)...
pyinstaller --noconfirm RailWatch_12306.spec

echo.
echo [OK] Packaging complete!
echo [OK] Please send the WHOLE "dist\RailWatch 12306" folder to other users.
echo [OK] The executable is in: dist\RailWatch 12306\RailWatch 12306.exe
pause
