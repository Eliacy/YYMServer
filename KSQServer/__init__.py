# -*- coding: utf-8 -*-

from flask import Flask
from flask.ext.sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://root:root@127.0.0.1:8889/keshaq'
db = SQLAlchemy(app)

db.app = app
db.init_app(app)

import KSQServer.views
import KSQServer.models

