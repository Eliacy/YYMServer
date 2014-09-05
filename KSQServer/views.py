# -*- coding: utf-8 -*-

from flask import render_template

from KSQServer import app, db
import KSQServer.admin

# Flask views
@app.route('/')
def index():
    return render_template('index.html')



