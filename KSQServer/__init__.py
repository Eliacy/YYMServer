# -*- coding: utf-8 -*-

import os, os.path

from flask import Flask
from flask.ext.sqlalchemy import SQLAlchemy


app = Flask(__name__)
app.config.from_object('KSQServer.default_settings')
try:
    app.config.from_envvar('KSQSERVER_SETTINGS')
except Exception:
    pass
static_folder = app.config['STATIC_FOLDER']

app = Flask(__name__, static_folder=static_folder)
app.config.from_object('KSQServer.default_settings')
try:
    app.config.from_envvar('KSQSERVER_SETTINGS')
except Exception:
    pass

db = SQLAlchemy(app)

db.app = app
db.init_app(app)

# Create directory for file fields to use
file_path = os.path.join(os.path.dirname(__file__), static_folder) if not static_folder.startswith('/') else static_folder
try:
    os.mkdir(file_path)
except OSError:
    pass

import KSQServer.views
import KSQServer.models

