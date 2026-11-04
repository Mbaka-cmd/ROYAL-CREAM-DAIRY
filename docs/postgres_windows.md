# PostgreSQL on your Windows PC (for testing the real stock locking)

1. Install PostgreSQL 16 or newer from https://www.postgresql.org/download/windows/ . Remember the
   password you set for the `postgres` superuser. Default port: 5432.
2. Open "SQL Shell (psql)" from the Start menu (press Enter for the defaults, then the postgres password) and run:

       CREATE USER royal WITH PASSWORD 'choose-a-password' CREATEDB;
       CREATE DATABASE royalcream OWNER royal;

   CREATEDB lets Django create its temporary test database.
3. Run the full test suite on PostgreSQL (asks for the password, keeps it out of files):

       powershell -ExecutionPolicy Bypass -File .\scripts\run_tests_postgres.ps1

   The stock-race test (two customers, one last bottle) only runs on PostgreSQL.
4. To use PostgreSQL for everyday development, put these in your local .env:

       DB_ENGINE=postgresql
       DB_NAME=royalcream
       DB_USER=royal
       DB_PASSWORD=choose-a-password
       DB_HOST=localhost
       DB_PORT=5432

   then run `.\.venv\Scripts\python.exe manage.py migrate`.