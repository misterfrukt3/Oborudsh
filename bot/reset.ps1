# Оборудыш — ЧИСТЫЙ СТАРТ (Windows). Бэкап и снос базы/загрузок перед прод-релизом.
# ВНИМАНИЕ: стирает ВСЕ заявки, брони 626, сообщения и пользователей.
# Запуск:  powershell -ExecutionPolicy Bypass -File reset.ps1
$ErrorActionPreference = "Stop"
$here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$db      = Join-Path $here "oborudka.db"
$uploads = Join-Path $here "uploads"
$stamp   = Get-Date -Format "yyyyMMdd-HHmmss"
$backup  = Join-Path $here "backup\$stamp"

Write-Host "1) Останавливаю бот (python main.py)…"
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 1

Write-Host "2) Бэкап в $backup"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
if (Test-Path $db)      { Copy-Item $db      (Join-Path $backup "oborudka.db") }
if (Test-Path $uploads) { Copy-Item $uploads (Join-Path $backup "uploads") -Recurse }

Write-Host "3) Удаляю базу и uploads"
Remove-Item -Force $db -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $uploads -ErrorAction SilentlyContinue

Write-Host "Готово. Запустите бот заново — схема создастся с нуля, заявок ни у кого нет."
