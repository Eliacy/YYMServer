# -*- coding: utf-8 -*-
#! /usr/bin/python

'''本文件全部路径需要改成实际环境的对应路径！'''

import sys
sys.path.insert(0, '/Users/elias/WorkNow/KeshaQ/server/lib/python2.7/site-packages')
sys.path.insert(0, '/Users/elias/WorkNow/KeshaQ/server/YYMServer/flask-hmacauth')
sys.path.insert(0, '/Users/elias/WorkNow/KeshaQ/server/YYMServer')

import os
os.environ['YYMSERVER_SETTINGS'] = '/Users/elias/WorkNow/KeshaQ/server/settings.py'

import YYMServer.downloader

storage_dir = '/Users/elias/tmp/qiniu_download'
logging_path = '/Users/elias/tmp/qiniu_download/download.log'

YYMServer.downloader.download(storage_dir, logging_path)


