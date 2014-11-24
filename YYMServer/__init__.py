# -*- coding: utf-8 -*-

import os, os.path
from cStringIO import StringIO

from flask import Flask
from flask.ext.cache import Cache
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext import restful
from flask.ext.hmacauth import DictAccountBroker, HmacManager

import qiniu.conf


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

# 准备共享数据的基本 url 路径：
baseurl_share = app.config['BASEURL_SHARE']

# 准备七牛 API：
qiniu.conf.ACCESS_KEY = app.config['QINIU_ACCESS_KEY']
qiniu.conf.SECRET_KEY = app.config['QINIU_SECRET_KEY']
qiniu_bucket = app.config['QINIU_BUCKET']
qiniu_callback = app.config['QINIU_CALLBACK']

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
api = restful.Api(app, catch_all_404s=True)

# 准备 api 签名机制
accountmgr = DictAccountBroker(
    accounts={
        # 注意：key 中尽量不用特殊字符，例如 ^ 之类，因为 key 会用于 url 拼接，有可能因为 url 自动转义造成签名验证问题。
        '4nM_mLISvh': {'secret': 'Yu8{Lnka%Y', 'rights': ['api', 'public', 'demo']},    # App 用的秘钥
        'demo_key': {'secret': 'demo_secret', 'rights': ['demo']},
        '9oF_9Y0a0e': {'secret': 'Nj4_iv_52Y', 'rights': ['public', 'demo']},    # 文件上传脚本用的秘钥
    })
hmacmgr = HmacManager(accountmgr, app, account_id=lambda x: x.values.get('key'), timestamp=lambda x: x.values.get('timestamp'))

import YYMServer.views
import YYMServer.models

