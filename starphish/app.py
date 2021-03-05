from flask import Flask, redirect
from flask_cors import CORS
import os
from . import defaults

# Secret Instance Config
import importlib
if 'STARPHISH_ENV' in os.environ:
    conf = importlib.import_module('.instance.{}'.format(os.environ['STARPHISH_ENV']), package='starphish')
else:
    conf = importlib.import_module('.instance.conf', package='starphish')

app = Flask('starphish', instance_relative_config=True)
CORS(app, origins=["https://8a089e7d-4d07-42df-8dfa-85d3c9162dd6.dev.wix-code.com", "https://starphish.wixsite.com"])
app.config.from_object(defaults)
app.config.from_object(conf)

app.config['STARPHISH_ENV'] = os.environ['STARPHISH_ENV'] if 'STARPHISH_ENV' in os.environ else 'DEFAULT'
