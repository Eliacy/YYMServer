# -*- coding: utf-8 -*-

import os, os.path

from flask import Flask
from flask.ext.cache import Cache
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext import restful
from flask.ext.hmacauth import DictAccountBroker, HmacManager


# 准备配置文件
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
cache = Cache(app, config=app.config)

# 准备 api 接口
api = restful.Api(app)

# 准备 api 签名机制
accountmgr = DictAccountBroker(
    accounts={
        '4nM^mLISvh': {'secret': 'Yu8{Lnka%Y', 'rights': ['api', 'demo']},
        'demo_key': {'secret': 'demo_secret', 'rights': ['demo']},
    })
hmacmgr = HmacManager(accountmgr, app, account_id=lambda x: x.values.get('key'), timestamp=lambda x: x.values.get('timestamp'))

import YYMServer.views
import YYMServer.models

