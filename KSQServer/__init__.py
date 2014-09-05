# -*- coding: utf-8 -*-

import os, os.path

from flask import Flask
from flask.ext.sqlalchemy import SQLAlchemy

app = Flask(__name__, static_folder='files')
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://root:root@127.0.0.1:8889/keshaq'
db = SQLAlchemy(app)

# Create dummy secrey key so we can use flash
app.config['SECRET_KEY'] = '123456790'

db.app = app
db.init_app(app)

# Create directory for file fields to use
file_path = os.path.join(os.path.dirname(__file__), 'files')
try:
    os.mkdir(file_path)
except OSError:
    pass

import KSQServer.views
import KSQServer.models

