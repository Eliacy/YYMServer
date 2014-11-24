# -*- coding: utf-8 -*-

DEBUG = False
# 显示共享数据的 html5 页面链接基础路径：
BASEURL_SHARE = 'http://h5.youyoumm.com/share'
# 设置时区：
""" 服务器时区应设置为 'Asia/Shanghai' ，否则可能数据出错！"""
# 强制 json 输出采用 utf-8 ：
JSON_AS_ASCII = False
# Create dummy secrey key so we can use flash
SECRET_KEY = 'YouYouMM_and_KeshaQ_SEC_KEY_408'
# 七牛 key：
QINIU_ACCESS_KEY = 'SHOULD_REPLACE_TO_REAL_QINIU_ACCESS_KEY'
QINIU_SECRET_KEY = 'SHOULD_REPLACE_TO_REAL_QINIU_SECRET_KEY'
QINIU_BUCKET = 'youyoumm'
QINIU_CALLBACK = 'http://rpc.youyoumm.com/rpc/images/call'
# 设置静态文件（主要是图片）存储路径
STATIC_FOLDER = 'files'
# 数据库连接设置：
SQLALCHEMY_DATABASE_URI = 'mysql://root:root@127.0.0.1:8889/keshaq'
# Cache 服务设置：详细参数参考 http://pythonhosted.org/Flask-Cache/
CACHE_TYPE = 'simple'
CACHE_DEFAULT_TIMEOUT = 15 * 60
#CACHE_TYPE = 'redis'
#CACHE_REDIS_HOST = '127.0.0.1'
#CACHE_REDIS_PORT = 6379
#CACHE_REDIS_PASSWORD = ''


