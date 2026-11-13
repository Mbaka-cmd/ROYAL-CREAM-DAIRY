Set-Location $PSScriptRoot
$env:DEMO_OPEN_LOGIN = "1"
$env:DJANGO_SETTINGS_MODULE = "config.settings.development"
Start-Process "http://127.0.0.1:8000/owner/login/"
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --insecure --noreload
