# -*- coding: utf-8 -*-

import requests
import time
import hashlib

from flask.ext.hmacauth import hmac

path_and_query = "/accumulator?timestamp="+str(int(time.time()))+"&key=4nM^mLISvh&a=10&b=100"
host = "http://127.0.0.1:5000"
sig=hmac.new("Yu8{Lnka%Y", digestmod=hashlib.sha1, msg=path_and_query).hexdigest()
print sig
req = requests.get(host+path_and_query, headers={'X-Auth-Signature': sig})
print req
print req.text


