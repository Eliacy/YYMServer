# -*- coding: utf-8 -*-

import codecs
import os, os.path
import getpass
import time
import hashlib
import json

import requests

from flask.ext.hmacauth import hmac

from YYMServer import util

API_HOST = 'http://rpc.youyoumm.com'
#API_HOST = 'http://127.0.0.1:5000'
API_KEY = '9oF_9Y0a0e'
API_SECRET = 'Nj4_iv_52Y'

LOG_NAME = 'uploader.log'

current_path = os.path.split(os.path.realpath(__file__))[0]
print '=', u'尝试上传目录 %s 中未上传过的图片文件（jpg, png, gif）：' % current_path

# 准备日志：
import logging
logger = logging.getLogger('YYMUploader')
hdlr = logging.FileHandler(os.path.join(current_path, LOG_NAME), encoding='utf-8')
formatter = logging.Formatter(u'%(asctime)s | %(levelname)s | %(message)s')
hdlr.setFormatter(formatter)
logger.addHandler(hdlr) 
logger.setLevel(logging.INFO)

# 首先进行对时：
ts = time.time()
resp = requests.get(API_HOST + '/rpc/time')
server_ts = json.loads(resp.text)['data']['timestamp']
time_diff = ts - server_ts

def rpc_post(path, param, payload):
    timestamp = int(time.time() - time_diff)
    params = {'timestamp': str(timestamp), 'key': API_KEY,}
    params.update(param)
    query = '&'.join(('='.join((key, value.encode('utf-8'))) for key, value in params.items()))
    hasher = hmac.new(API_SECRET, digestmod=hashlib.sha1, msg=path + '?' + query)
    body = json.dumps(payload, ensure_ascii=False).encode('utf8')
    hasher.update(body)     # 如果是 POST 方法发送的，则 POST 的 body 也需要加入签名内容！
    sig = hasher.hexdigest()
    resp = requests.post(API_HOST + path, params=params, data=json.dumps(payload), headers={'X-Auth-Signature': sig, 'Content-Type':'application/json'})
    resp_dic = json.loads(resp.text)
    return resp_dic

# 用户登陆
user_id = None
#user_id = 321
while not user_id:
    print '=', u'用户名：',
    username = raw_input()
    print '=', u'密码：',
    password = getpass.getpass('')

    path = '/rpc/tokens'
    payload = {'username': username,
               'password': password,
               'device': 'YYMUploader',
              }
    resp = rpc_post(path, {}, payload)
    status = resp['status']
    if status == 201:
        user_id = resp['data']['user_id']
        print '=', u'成功以用户 id %d 登陆！' % user_id
    else:
        print '=', u'用户或密码不正确！'

# 读取历史处理日志：
history_dic = {}
with codecs.open(os.path.join(current_path, LOG_NAME), 'r', 'utf-8') as f:
    for line in f.readlines():
        time_str, level, message = line.split('|')[:3]
        filename, id_str, resp = message.strip().split(':')[:3]
        level = level.strip()
        filename = filename.strip()
        if level.lower() == 'info':
            history_dic[filename] = True

# 列出图片文件：
for filename in os.listdir(current_path):
    endfix = filename.split('.')[-1].lower()
    if endfix in ['jpg', 'jpeg', 'png', 'gif']:
        if history_dic.has_key(filename):
            continue
        full_path = os.path.join(current_path, filename)
        ret, err = util.upload_image(full_path, 0, 2, user_id, u'', filename)
        if err is None:
            image_id = json.loads(ret)['data']['id']
            print '*', filename, u'上传成功。id 为：', image_id
            logger.info(filename + u':' + unicode(image_id) + u':' + unicode(ret))
        else:
            print '*', filename, u'上传出错！', err
            logger.error(filename + u': :' + err)

print '=', u'找不到更多未上传的图片文件了！'



