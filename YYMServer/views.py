# -*- coding: utf-8 -*-

from flask import jsonify, render_template, request

from YYMServer import app, db, cache
import YYMServer.admin

# Flask views
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/_add_numbers')
def add_numbers():
    a = request.args.get('a', 0, type=int)
    b = request.args.get('b', 0, type=int)
    key = '%d_%d' % (a,b)
    result = cache.get(key)
    if result is None:
        result = a + b
        cache.set(key, result, timeout=5 * 60)
    else:
        print '{{{Cache hit!}}}'
    return jsonify(result=result)


