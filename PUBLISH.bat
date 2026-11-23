@echo off
chcp 65001 >nul
cd /d "C:\Users\minko\GameBacklog"
echo.
echo  Browser will open GitHub token page.
echo  Click "Generate new token (classic)" - tick "repo" - Generate - copy token.
echo  Then paste it here and press Enter.
echo.
start https://github.com/settings/tokens
set /p GH_TOKEN=Paste GitHub token: 
if "%GH_TOKEN%"=="" goto fail
(
echo protocol=https
echo host=github.com
echo username=DuckDuckHQ
echo password=%GH_TOKEN%
echo.
) | git credential approve >nul 2>&1
git push -u origin main
if errorlevel 1 goto fail
echo.
echo DONE - GameBacklog is published on GitHub.
echo.
pause
exit /b 0
:fail
echo.
echo PUSH FAILED. Check the token and try again.
pause
