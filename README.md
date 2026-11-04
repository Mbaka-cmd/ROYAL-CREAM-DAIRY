# Royal Cream Dairy

Pure Goodness, Every Day.

Django 5.2 modular monolith: storefront, inventory, orders, WhatsApp notifications, owner dashboard.

## Local setup (Windows PowerShell)

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    copy .env.example .env   # then fill in values
    .\.venv\Scripts\python.exe manage.py migrate
    .\.venv\Scripts\python.exe manage.py runserver