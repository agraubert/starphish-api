from flask import current_app, request
from functools import wraps
import traceback
from threading import Lock
import pandas as pd
import sqlalchemy as sqla
from time import monotonic
from datetime import datetime, timedelta
from urllib.parse import urlparse

def error(message, *, data=None, context=None, code=400):
    # Maybe log

    err = {'message': message, 'code': code}
    if data is not None:
        err['data'] = data

    if context is not None:
        err['context'] = data

    return err, code

def enforce_content_length(func):

    @wraps(func)
    def wrapper(*args, **kwargs):
        if 'Content-Length' not in request.headers or int(request.headers['Content-Length']) > current_app.config['MAX_CONTENT_LENGTH']:
            return error("Request payload too large", data={'max-content-length': current_app.config['MAX_CONTENT_LENGTH']}, code=413)
        return func(*args, **kwargs)

    return wrapper

def rate_limit(limit):

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            # if 'CUSTOM_LIMITS' in current_app.config and request.remote_addr in current_app.config['CUSTOM_LIMITS']:
            #     limit = current_app.config['CUSTOM_LIMITS'][request.remote_addr]
            with Database.get_db(current_app.config) as db:
                table = db['ratelimit']
                quota = db.query(
                    table.select.where(
                        table.c.ip == sqla.text("'{}'".format(request.remote_addr))
                    ).where(
                        table.c.endpoint == sqla.text("'{}'".format(func.__name__))
                    )
                )
                if len(quota):
                    if quota['expires'][0] > datetime.now():
                        if quota['count'][0] >= limit:
                            return error("Too many requests", data={
                                "quota_resets": quota['expires'][0],
                            }, code=429)
                        db.execute(table.update.where(table.c.ip == sqla.text("'{}'".format(request.remote_addr))).where(
                            table.c.endpoint == sqla.text("'{}'".format(func.__name__))
                        ).values(
                            count=int(quota['count'][0]) + 1
                        ))
                    else:
                        db.execute(table.update.where(table.c.ip == sqla.text("'{}'".format(request.remote_addr))).where(
                            table.c.endpoint == sqla.text("'{}'".format(func.__name__))
                        ).values(
                            expires=datetime.now() + timedelta(minutes=1),
                            count=1,
                        ))
                else:
                    # db.insert('requests', ip=request.remote_addr, expires=datetime.now()+timedelta(minutes=1), lim=limit-1)
                    db.execute(table.insert.values(
                        ip=request.remote_addr,
                        endpoint=func.__name__,
                        expires=datetime.now() + timedelta(minutes=1),
                        count=1,
                        max=limit
                    ))
            return func(*args, **kwargs)

        return wrapper

    return decorator

def log_request(func):

    @wraps(func)
    def wrapper(*args, **kwargs):
        t0 = monotonic()
        try:
            result = func(*args, **kwargs)
            with Database.get_db(current_app.config) as db:
                db.insert(
                    'requests',
                    time=datetime.now(),
                    host=request.headers['Host'][:512] if 'Host' in request.headers else None,
                    agent=request.headers['User-Agent'] if 'User-Agent' in request.headers else None,
                    length=int(request.headers['Content-Length']) if 'Content-Length' in request.headers else None,
                    ip=request.remote_addr,
                    endpoint='{} ({})'.format(request.path, func.__name__)[:256],
                    response_code=result[-1] if isinstance(result, tuple) else 200,
                    response_time=int(monotonic()-t0)
                )
            return result
        except:
            traceback.print_exc()
            with Database.get_db(current_app.config) as db:
                db.insert(
                    'requests',
                    time=datetime.now(),
                    host=request.headers['Host'][:512] if 'Host' in request.headers else None,
                    agent=request.headers['User-Agent'] if 'User-Agent' in request.headers else None,
                    length=int(request.headers['Content-Length']) if 'Content-Length' in request.headers else None,
                    ip=request.remote_addr,
                    endpoint='{} ({})'.format(request.path, func.__name__)[:256],
                    response_code=None,
                    response_time=int(monotonic()-t0)
                )

    wrapper.not_logged = lambda *args, **kwargs: func(*args, **kwargs)

    return wrapper

def ensure_scheme(url):
    result = urlparse(url)
    return "http://{}".format(url) if not (result.scheme and url.startswith('{}://'.format(result.scheme))) else url

def standardize_urls(urls):
    """
    Standardizes query urls to maximize probability of a match
    1) Checks the given url (lowercased if no resource path is present)
    2) If a resource path is given, checks the url with just scheme and base location (lowercased)
    3) If no scheme is present, checks the url using http and lowercased location
    """
    for url in urls:
        result = urlparse(url.lower())
        yield ensure_scheme(url if result.path else url.lower())
        result = urlparse(ensure_scheme(url.lower()))
        if result.path and result.netloc:
            yield ensure_scheme(result.netloc.lower())

DATABASE = None
DBL = Lock()

class TableHandle(object):
    def __init__(self, table):
        self.table = table
        self.c = table.c

    @property
    def select(self):
        return sqla.select(self.table)

    @property
    def update(self):
        return sqla.update(self.table)

    @property
    def insert(self):
        return sqla.insert(self.table)

    @property
    def delete(self):
        return sqla.delete(self.table)

class Database(object):

    @staticmethod
    def init_with_url(url, **kwargs):
        db = Database(url, **kwargs)
        table_defs(db)
        return db

    @staticmethod
    def get_db(config):
        global DATABASE
        with DBL:
            if DATABASE is None:
                DATABASE = Database(
                    config['DB_URL'],
                    echo=('DB_ECHO' in config and config['DB_ECHO'])
                )
                table_defs(DATABASE)
            return DATABASE

    def __init__(self, url, *, future=True, **kwargs):
        self.url = url
        self.engine = sqla.create_engine(url, future=future, **kwargs)
        self.meta = sqla.MetaData(self.engine)
        self._conn = None
        self._lock = Lock()
        self._tables = {}

    def __getitem__(self, table):
        """
        Gets requested table name
        """
        self._check_conn()
        if table not in self._tables:
            raise NameError("No such table '{}'".format(table))
        return TableHandle(self._tables[table])

    def lock(self):
        """
        Acquires any necessary locks
        """
        self._lock.acquire()

    def unlock(self):
        """
        Releases any necessary locks
        """
        self._lock.release()

    def connect(self):
        """
        Connects to the database
        """
        self._conn = self.engine.connect().__enter__()

    def disconnect(self):
        """
        Disconnects from the database
        """
        self._conn.__exit__(None, None, None)
        self._conn = None

    def commit(self):
        """
        Commits Changes
        """
        self._conn.commit()

    def connected(self):
        """
        Return the current connection state
        """
        return self._conn is not None

    def query(self, query, **kwargs):
        """
        Execute the given query
        """
        self._check_conn()
        if isinstance(query, str):
            query = sqla.text(query)
        return pd.read_sql(query, self._conn, params=kwargs if len(kwargs) else None)

    def insert(self, table, **values):
        self._check_conn()
        # return self._conn.execute(sqla.insert(self._tables[table]).values(values))
        return self._conn.execute(self[table].insert, values)

    def multi_insert(self, table, values):
        self._check_conn()
        if not len(values):
            return
        return self._conn.execute(self[table].insert, values)

    def execute(self, statement):
        self._check_conn()
        return self._conn.execute(statement)

    def __enter__(self):
        """
        Opens the connection and acquires locks
        """
        self.lock()
        self.connect()
        return self

    def create_table(self, table_name, *args, **kwargs):
        self._check_conn()
        table = sqla.Table(
            table_name,
            *args,
            **kwargs
        )
        self.meta.create_all()
        self._tables[table_name] = table
        return table

    def __exit__(self, exc_type, exc_val, tb):
        try:
            if (exc_type is not None or exc_val is not None or tb is not None):
                traceback.print_exc()
                # self.abort()
            else:
                self.commit()
        finally:
            self.disconnect()
            self.unlock()

    def _check_conn(self):
        if not self.connected():
            raise RuntimeError("The database is not currently connected")

    def read_table(self, table_name):
        """
        Return the requested table in full
        """
        return self.query("select * from {}".format(table_name))

def table_defs(db):
    # Init mysql cursor
    # try:
    # run request
    # insert request: raw request headers, ip, endpoint (function name), response code, response time
    # except
    # insert request raw request headers, ip, endpoint (function name), <no response code>, response time
    with db:
        db.create_table(
            'requests',
            db.meta,
            sqla.Column('id', sqla.Integer, primary_key=True, autoincrement=True),
            sqla.Column('time', sqla.DateTime),
            sqla.Column('host', sqla.String(512)),
            sqla.Column('agent', sqla.Text),
            sqla.Column('length', sqla.Integer),
            sqla.Column('ip', sqla.String(40)),
            sqla.Column('endpoint', sqla.String(256)),
            sqla.Column('response_code', sqla.Integer),
            sqla.Column('response_time', sqla.Integer),
            extend_existing=True,
            sqlite_autoincrement=True
        )
        db.create_table(
            'safebrowse_cache',
            db.meta,
            sqla.Column('url_hash', sqla.String(64), primary_key=True),
            sqla.Column('url', sqla.Text, nullable=False),
            sqla.Column('expires', sqla.DateTime, primary_key=True),
            sqla.Column('safe', sqla.Boolean, nullable=False),
            sqla.Column('type', sqla.String(64)),
            extend_existing=True
        )
        db.create_table(
            'ratelimit',
            db.meta,
            sqla.Column('ip', sqla.String(40), primary_key=True),
            sqla.Column('count', sqla.Integer),
            sqla.Column('max', sqla.Integer),
            sqla.Column('endpoint', sqla.String(64), primary_key=True),
            sqla.Column('expires', sqla.DateTime),
            extend_existing=True
        )
        db.create_table(
            'blacklist',
            db.meta,
            sqla.Column('ip', sqla.String(40), primary_key=True),
            sqla.Column('endpoint', sqla.String(256)),
            sqla.Column('timestamp', sqla.DateTime, primary_key=True),
            extend_existing=True
        )
        db.create_table(
            'phishing',
            db.meta,
            sqla.Column('url_hash', sqla.String(64), primary_key=True),
            sqla.Column('source', sqla.String(16)),
            sqla.Column('url', sqla.Text, nullable=False),
            sqla.Column('added', sqla.DateTime, primary_key=True),
            extend_existing=True
        )
        db.create_table(
            'phishtank_log',
            db.meta,
            sqla.Column('time', sqla.DateTime, primary_key=True),
            sqla.Column('length', sqla.Integer),
            sqla.Column('hash', sqla.String(64), nullable=False),
            extend_existing=True
        )


def export_blacklist_ips(url, delete=False):
    with Database.init_with_url(url) as db:
        df = db.query(sqla.select(sqla.distinct(db['blacklist'].c.ip)))
        if delete:
            db.execute(db['blacklist'].delete)
        return df
