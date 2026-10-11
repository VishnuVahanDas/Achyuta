# Achyuta

A mobile-first personal ledger: where is my money, and who owes whom. Design in `Docs/DESIGN.md`, project rules in `CLAUDE.md`.

## Run it locally

Needs Python 3.12+ and PostgreSQL.

```bash
# 1. Database (once)
sudo -u postgres psql -c "CREATE ROLE paisa LOGIN CREATEDB PASSWORD 'choose-one'" -c "CREATE DATABASE paisa OWNER paisa"

# 2. Config (once)
cp .env.example .env   # set DJANGO_SECRET_KEY and the DATABASE_URL password

# 3. Install, migrate, create your login
make setup
make migrate
make superuser

# 4. Run
make run               # http://127.0.0.1:8000
```

`make css-watch` in a second terminal rebuilds the stylesheet as templates change. `make test` and `make lint` run the checks.
