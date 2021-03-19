from flask import current_app, request
from functools import wraps
import traceback
from threading import Lock
import pandas as pd
import sqlalchemy as sqla
from time import monotonic
from datetime import datetime

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


DATABASE = None
DBL = Lock()

class Database(object):
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
        self.engine = sqla.create_engine(url, future=future, **kwargs)
        self.meta = sqla.MetaData(self.engine)
        self._conn = None
        self._lock = Lock()
        self._tables = {}

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

    def query(self, query, args=None):
        """
        Execute the given query
        """
        self._check_conn()
        if isinstance(query, str):
            query = sqla.text(query)
        return pd.read_sql(query, self._conn, params=args)

    def insert(self, table, **values):
        self._check_conn()
        return self._conn.execute(sqla.insert(self._tables[table]).values(**values))

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
            keep_existing=True,
            sqlite_autoincrement=True
        )
        db.meta.create_all()
