from .endpoints import app
import subprocess
import warnings

if __name__ == '__main__':
    if 'SERVE_HTTPS' in app.config and app.config['SERVE_HTTPS']:
        if 'PORT' not in app.config:
            warnings.warn("No port defined in current config ({}). Serving under 443 (HTTPS enabled)".format(app.config['STARPHISH_ENV']))
            port = 443
        else:
            port = app.config['PORT']
        app.run(host='0.0.0.0', port=port, ssl_context=(app.config["SSL_CERTIFICATE"], app.config["SSL_KEY"]))
    else:
        if 'PORT' not in app.config:
            if app.config['STARPHISH_ENV'] != 'DEFAULT':
                warnings.warn("No port defined in current config ({}). Serving under 443 (HTTPS enabled)".format(app.config['STARPHISH_ENV']))
            port = 8080
        else:
            port = app.config['PORT']
        app.run(host='0.0.0.0', port=port)
