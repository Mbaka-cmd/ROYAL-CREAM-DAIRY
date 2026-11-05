# Royal Cream Dairy

Pure Goodness, Every Day.

Django 5.2 modular monolith: storefront, inventory, orders, WhatsApp notifications, owner dashboard.

## Local setup (Windows PowerShell)

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    copy .env.example .env   # then fill in values
    .\.venv\Scripts\python.exe manage.py migrate
    .\.venv\Scripts\python.exe manage.py runserver
## First-time setup checklist

After `migrate`, run these once:

1. `.\.venv\Scripts\python.exe manage.py createsuperuser`
2. `.\.venv\Scripts\python.exe manage.py collectstatic --noinput`
3. Open `/django-admin/` > Delivery zones and add your delivery areas with fee and minimum order. Checkout needs at least one.
4. Open `/owner/products/` and upload a photo for each product. Photos are stored in `media/` and are not in git.
5. Clear any "DEMO DATA" product descriptions before launch.
