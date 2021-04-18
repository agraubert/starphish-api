# starphish-api
Backend API code for starphish.org

## Setup

Run `pip install -r requirements.txt` to install the required modules

## Configuring

Place config files in the `starphish/instance/` directory. By default, Starphish
will read from `starphish/instance/conf.py`, but you can set multiple configs and
switch between them by setting the environment variable `STARPHISH_ENV`. If set,
Starphish will read from `starphish/instance/${STARPHISH_ENV}.py`.

Config files should simply define root-level variables which will be read by the app.

```python
PORT=80 # Port to serve the app from
SAFEBROWSING_API_KEY="API key" # API key for Google Safebrowsing
DB_URL="{Sql alchemy url}" # For configuring SQL Alchemy
```

### Sqlalchemy with SQLite

I don't recommend running SQLite in a production environment, but it's decent for
your dev or test environment. All you need to do is run `sqlite3 {file}.db` to
create a new database file (type `.quit` in the prompt to exit).

Then you can set starphish to use that file by setting `DB_URL="sqlite+pysqlite:///{file}.db"`.
You can check SQLAlchemy's docs for instructions on configuring for different databases.

## Running

From the root of the repository, run `python -m starphish`

## Scripts

### Database Imports

* `scripts/phishtank_init.py`: This script loads the current state of the [Phishtank](https://github.com/mitchellkrogza/Phishing.Database)
database into starphish's local database.
* `scripts/cron/phishtank.py`: This script loads periodic updates to Phishtank into
the local database. Phishtank updates every few hours so it's best to schedule a
cron job to run this hourly
* `scripts/aa419.py`: This script loads the [aa419](https://db.aa419.org/fakebankslist.php)
database into starphish. Since aa419 does not have an API, this is a web scraper
which takes about 15 hours to download the full dataset.

### Migrations

For new users, you won't have to use migrations. However, existing starphish instances
need to run new migration scripts when they are released to keep their databases
consistent.
