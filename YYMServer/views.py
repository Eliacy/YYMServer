# -*- coding: utf-8 -*-

import time

from flask import jsonify, render_template, request

from YYMServer import app, db, cache

import YYMServer.admin
import YYMServer.rpc

# 主页，负责提供后台管理界面的链接
@app.route('/')
def index():
    return render_template('index.html')


