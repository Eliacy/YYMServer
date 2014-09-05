# -*- coding: utf-8 -*-

from KSQServer import app, db

@app.route('/')
def index():
    return 'Hello World!'

