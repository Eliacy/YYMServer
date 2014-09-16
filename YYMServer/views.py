# -*- coding: utf-8 -*-

from flask import jsonify, render_template, request

from YYMServer import app, db
import YYMServer.admin

# Flask views
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/_add_numbers')
def add_numbers():
    a = request.args.get('a', 0, type=int)
    b = request.args.get('b', 0, type=int)
    return jsonify(result=a + b)


