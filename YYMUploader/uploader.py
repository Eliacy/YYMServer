# -*- coding: utf-8 -*-

import codecs
import os, os.path
import getpass
import sys
import time
import hashlib
import json
import hmac

import requests
import qiniu.io

''' 如果 exe 程序出现杀毒软件报错，可以用 upx 加壳来保护。'''

API_HOST = 'http://rpc.youyoumm.com'
API_KEY = '9oF_9Y0a0e'
API_SECRET = 'Nj4_iv_52Y'

LOG_NAME = 'uploader.log'

default_encoding = sys.stdin.encoding

current_path = os.path.split(os.path.realpath(__file__))[0]
print '=', u'尝试上传目录 %s 中未上传过的图片文件（jpg, png, gif）：' % current_path

# 准备日志：
import logging
logger = logging.getLogger('YYMUploader')
hdlr = logging.FileHandler(os.path.join(current_path, LOG_NAME), encoding=default_encoding)
formatter = logging.Formatter(u'%(asctime)s | %(levelname)s | %(message)s')
hdlr.setFormatter(formatter)
logger.addHandler(hdlr) 
logger.setLevel(logging.INFO)

# 首先进行对时：
ts = time.time()
resp = requests.get(API_HOST + '/rpc/time')
server_ts = json.loads(resp.text)['data']['timestamp']
time_diff = ts - server_ts

def extract(filename):
    ''' 辅助函数：处理原始文件名，拆分为真实文件名和注释（中文括号之内的部分当做注释）。'''
    if type(filename) == str:
        filename = unicode(filename, default_encoding)
    if u'（' not in filename or u'）' not in filename:
        return filename, u''
    leading = u''
    note = filename
    if u'（' in note:
        leading, note = note.split(u'（', 1)
    ending = u''
    if u'）' in note:
        note, ending = note.split(u'）', 1)
    return leading + ending, note

def rpc_post(path, param, payload):
    timestamp = int(time.time() - time_diff)
    params = {'timestamp': str(timestamp), 'key': API_KEY,}
    params.update(param)
    query = '&'.join(('='.join((key, value.encode('utf-8'))) for key, value in params.items()))
    hasher = hmac.new(API_SECRET, digestmod=hashlib.sha1, msg=path + '?' + query)
    body = json.dumps(payload, ensure_ascii=False)
    hasher.update(body)     # 如果是 POST 方法发送的，则 POST 的 body 也需要加入签名内容！
    sig = hasher.hexdigest()
    resp = requests.post(API_HOST + path, params=params, data=json.dumps(payload), headers={'X-Auth-Signature': sig, 'Content-Type':'application/json'})
    resp_dic = json.loads(resp.text)
    return resp_dic

def upload_image(file_path, id, type, user, note, name):
    ''' 辅助函数：上传文件到七牛云存储。'''
    callback_dic = {
      'id': str(id),
      'type': str(type),
      'user': str(user),
      'note': note or u'',
      'name': name or u'',   # 原始文件名这个不靠谱，最好自己存
      'size': '$(fsize)',
      'mime': '$(mimeType)',
      'width': '$(imageInfo.width)',
      'height': '$(imageInfo.height)',
      'hash': '$(etag)',
    }
    resp = rpc_post('/rpc/uptokens', {}, {'params': json.dumps(callback_dic, ensure_ascii=False).encode('utf8')})
    status = resp['status']
    if status == 201:
        uptoken = resp['data']['token']
        ret, err = qiniu.io.put_file(uptoken, None, file_path)
        return (ret, err)
    else:
        return (resp, resp)

# 用户登陆
user_id = None
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
with codecs.open(os.path.join(current_path, LOG_NAME), 'r', default_encoding) as f:
    for line in f.readlines():
        time_str, level, message = line.split('|', 2)
        filename, note, id_str, resp = message.strip().split(':', 3)
        level = level.strip()
        filename = filename.strip()
        if level.lower() == 'info':
            history_dic[filename] = True

# 列出图片文件：
for filename in os.listdir(current_path):
    endfix = filename.split('.')[-1].lower()
    if endfix in ['jpg', 'jpeg', 'png', 'gif']:
        full_path = os.path.join(current_path, filename)
        filename, note = extract(filename)
        if history_dic.has_key(filename):
            continue
        ret, err = upload_image(full_path, 0, 2, user_id, note, filename)
        if err is None:
            image_id = ret['data']['id']
            print '*', filename, u'上传成功。id 为：', image_id, u'注释为：', note
            logger.info(filename + u':' + note + u':' + unicode(image_id) + u':' + unicode(ret))
        else:
            print '*', filename, u'上传出错！', err
            logger.error(filename + u':' + note + u': :' + err)

print '=', u'找不到更多未上传的图片文件了！'
print '=', u'按回车键结束程序运行。'
raw_input()


