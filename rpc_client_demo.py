# -*- coding: utf-8 -*-

import requests
import time
import hashlib
import json

from flask.ext.hmacauth import hmac

#host = "http://127.0.0.1:5000"
host = "http://rpc.youyoumm.com"

# 首先进行对时：
ts = time.time()
resp = requests.get(host+"/rpc/time")
print resp
print resp.text
server_ts = json.loads(resp.text)['data']['timestamp']
# 注意：服务器时间戳检查不允许时间戳快于服务器时间，因此做对时调整时需要稍稍多调慢一些，才能增大连接成功的概率！
time_diff = ts - server_ts
print 'time diff:', time_diff, '\n'

# 正式调用服务器接口：
timestamp = int(time.time() - time_diff - 2)
path_and_query = "/rpc/accumulator?timestamp="+str(timestamp)+"&key=demo_key&a=10&b=100"
hasher = hmac.new("demo_secret", digestmod=hashlib.sha1, msg=path_and_query)
# hasher.update(request.body)   # ToDo: 如果是 POST 方法发送的，则 POST 的 body 也需要加入签名内容！
sig = hasher.hexdigest()
print 'sig:', sig
resp = requests.get(host+path_and_query, headers={'X-Auth-Signature': sig})
print resp
print resp.text


