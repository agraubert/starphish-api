from flask import current_app, request
from functools import wraps

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
        if 'Content-Length' not in request.headers or request.headers['Content-Length'] > current_app.config['MAX_CONTENT_LENGTH']:
            return error("Request payload too large", data={'max-content-length': current_app.config['MAX_CONTENT_LENGTH']}, code=413)
        return func(*args, **kwargs)

    return wrapper
