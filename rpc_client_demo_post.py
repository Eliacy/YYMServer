# -*- coding: utf-8 -*-

import requests
import time
import hashlib
import json

from flask.ext.hmacauth import hmac

''' 演示在有 api 签名验证的情况下，调用 POST 方法的处理过程。

代码中所使用的 key 及秘钥，可能并没有本代码所调用 api 的相关权限，执行时需要相应修改！
'''

host = "http://127.0.0.1:5000"
#host = "http://rpc.youyoumm.com"

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
path = "/rpc/reviews"
params = {'timestamp': str(timestamp), 'key': 'demo_key', 'some_chinese': u'演示中文用的多余参数'}
query = '&'.join(('='.join((key, value.encode('utf-8'))) for key, value in params.items()))
print path + '?' + query
hasher = hmac.new("demo_secret", digestmod=hashlib.sha1, msg=path + '?' + query)

payload = {'published': '1',
           'user_id': '321',
           'at_list': '321 325 331',
           'stars': '4.1',
           'content': u'空内容post\r\n空内容第二行',
           'images': '13 2396 19',
           'keywords': u'什么关键词 另一个关键词',
           'total': '1500',
           'currency': u'美元',
           'site_id': '3421',
           }
#body = '&'.join(('='.join((key, value.encode('utf-8'))) for key, value in payload.items()))
# 注意：Flask 服务器上读取 POST 参数时，参数的顺序无法被保证，所以约定使用 json 格式封装请求参数。。
#       也即， application/x-www-form-urlencoded 的请求将有可能存在验证无法通过问题，但文件上传相关的数据不会被用于校验！
# 注意：计算 POST 数据签名时，json 字符串必须保证使用 utf-8 编码！
body = json.dumps(payload, ensure_ascii=False).encode('utf8')
print body
hasher.update(body)     # 如果是 POST 方法发送的，则 POST 的 body 也需要加入签名内容！

sig = hasher.hexdigest()
print 'sig:', sig

#resp = requests.post(host+path, params=params, data=payload, headers={'X-Auth-Signature': sig})
resp = requests.post(host+path, params=params, data=body, headers={'X-Auth-Signature': sig, 'Content-Type':'application/json'})
#print resp.request.body
print resp
print resp.text


