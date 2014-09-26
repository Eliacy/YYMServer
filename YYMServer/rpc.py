# -*- coding: utf-8 -*-

import time

from flask import jsonify, request
from flask.ext.restful import reqparse, Resource, fields, marshal_with
from flask.ext.hmacauth import hmac_auth

from YYMServer import app, db, cache, api
from YYMServer.models import *

from flask.ext.restful.representations.json import output_json
output_json.func_globals['settings'] = {'ensure_ascii': False, 'encoding': 'utf8'}


class Time(Resource):
    '''服务器对时服务。'''
    def get(self):
        return {'timestamp': time.time()}


api.add_resource(Time, '/rpc/time')


site_fields = {
    'name': fields.String,
    'address': fields.String,
    'business_hours': fields.String,
    'description': fields.String,
}


class SiteList(Resource):
    '''“附近”搜索功能对应的 POI 列表获取。'''
#    @hmac_auth('api')
    @marshal_with(site_fields)
    def get(self):
        return db.session.query(Site).first()


api.add_resource(SiteList, '/rpc/sites')


# json 网络服务样例
@app.route('/rpc/_add_numbers')
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


class Calculator(Resource):
    @hmac_auth('api')
    def get(self):
        args = cac_parser.parse_args()
        return {'restful_result': args['a'] + args['b']}

api.add_resource(Calculator, '/rpc/accumulator')


