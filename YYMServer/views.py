# -*- coding: utf-8 -*-

import time

from flask import jsonify, render_template, request
from flask.ext import restful
from flask.ext.restful import reqparse
from flask.ext.hmacauth import hmac_auth

from YYMServer import app, db, cache, api
import YYMServer.admin

# 主页，负责提供后台管理界面的链接
@app.route('/')
def index():
    return render_template('index.html')


class Time(restful.Resource):
    def get(self):
        return {'timestamp': time.time()}


api.add_resource(Time, '/rpc/time')


# ToDo: 前台 App 调用接口时应发送用户唯一标识，以追踪用户行为


# json 网络服务样例
@app.route('/_add_numbers')
@hmac_auth('api')
def add_numbers():
    a = request.args.get('a', 0, type=int)
    b = request.args.get('b', 0, type=int)
    key = '%d_%d' % (a,b)
    result = cache.get(key)
    if result is None:
        result = a + b
        cache.set(key, result, timeout=5 * 60)
    else:
        print '{{{Cache hit!}}}'
    return jsonify(result=result)


cac_parser = reqparse.RequestParser()
cac_parser.add_argument('a', type=int, help=u'被相加的第一个数字')
cac_parser.add_argument('b', type=int, help=u'被相加的第二个数字')


class Calculator(restful.Resource):
    @hmac_auth('api')
    def get(self):
        args = cac_parser.parse_args()
        return {'restful_result': args['a'] + args['b']}

api.add_resource(Calculator, '/accumulator')


