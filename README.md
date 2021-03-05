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
```

## Running

From the root of the repository, run `python -m starphish`
