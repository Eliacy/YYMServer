# -*- coding: utf-8 -*-

import os, os.path

from flask import Flask
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext import restful


app = Flask(__name__)
app.config.from_object('YYMServer.default_settings')
try:
    app.config.from_envvar('YYMSERVER_SETTINGS')
except Exception:
    pass
static_folder = app.config['STATIC_FOLDER']

app = Flask(__name__, static_folder=static_folder)
app.config.from_object('YYMServer.default_settings')
try:
    app.config.from_envvar('YYMSERVER_SETTINGS')
except Exception:
    pass

# 准备数据库
db = SQLAlchemy(app)

db.app = app
db.init_app(app)

# 准备文件上传存储路径
file_path = os.path.join(os.path.dirname(__file__), static_folder) if not static_folder.startswith('/') else static_folder
try:
    os.mkdir(file_path)
except OSError:
    pass

# 准备缓存
cache = None
try:
    if app.config['CACHE_TYPE'] == 'simple':
        from werkzeug.contrib.cache import SimpleCache
        cache = SimpleCache()
    elif app.config['CACHE_TYPE'] == 'redis':
        # ToDo: 应该将 Reids 的缓存访问改为 hset 和 hget ，以便利用 Redis 的 Hash 机制节约内存！
        host = 'localhost' if not app.config.has_key('CACHE_HOST') else app.config['CACHE_HOST']
        port = 6379 if not app.config.has_key('CACHE_PORT') else int(app.config['CACHE_PORT'])
        password = None if not app.config.has_key('CACHE_PASSWORD') else app.config['CACHE_PASSWORD']
        from werkzeug.contrib.cache import RedisCache
        cache = RedisCache(host, port, password)
except Exception, e:
    print e

# 准备 api 接口
api = restful.Api(app)

import YYMServer.views
import YYMServer.models

