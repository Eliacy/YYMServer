# -*- coding: utf-8 -*-

# 强制 json 输出采用 utf-8 ：
JSON_AS_ASCII = False
# Create dummy secrey key so we can use flash
SECRET_KEY = 'YouYouMM_and_KeshaQ_SEC_KEY_408'
# 设置静态文件（主要是图片）存储路径
STATIC_FOLDER = 'files'
# 数据库连接设置：
SQLALCHEMY_DATABASE_URI = 'mysql://root:root@127.0.0.1:8889/keshaq'
# Cache 服务设置：
CACHE_TYPE = 'simple'
#CACHE_TYPE = 'redis'
#CACHE_HOST = '127.0.0.1'
#CACHE_PORT = '6379'
#CACHE_PASSWORD = ''


