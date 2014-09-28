# -*- coding: utf-8 -*-

import time

from flask import jsonify, request
from flask.ext.restful import reqparse, Resource, fields, marshal_with
from flask.ext.hmacauth import hmac_auth

from YYMServer import app, db, cache, api
from YYMServer.models import *

from flask.ext.restful.representations.json import output_json
output_json.func_globals['settings'] = {'ensure_ascii': False, 'encoding': 'utf8'}


# 基础接口：
class Version(Resource):
    '''服务器版本查询服务。'''
    def get(self):
        return {'minimal_available_version': 1}

api.add_resource(Version, '/rpc/version')


class Time(Resource):
    '''服务器对时服务。'''
    def get(self):
        return {'timestamp': time.time()}

api.add_resource(Time, '/rpc/time')


# 国家接口：
country_parser = reqparse.RequestParser()
country_parser.add_argument('id', type=int)

country_fields = {
    'id':fields.Integer,
    'name': fields.String,
    'order': fields.Integer,
}

class CountryList(Resource):
    '''获取全部国家及指定国家名字的服务。'''
    @hmac_auth('api')
    @marshal_with(country_fields)
    def get(self):
        # ToDo: 需要创建查询缓存！
        args = country_parser.parse_args()
        id = args['id']
        query = db.session.query(Country).filter(Country.valid == True).order_by(Country.order.desc())
        if id:
            query = query.filter(Country.id == id)
        return query.all()

api.add_resource(CountryList, '/rpc/countries')


# POI 接口：
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


# ==== json 网络服务样例 ====
cac_parser = reqparse.RequestParser()
cac_parser.add_argument('a', type=int, help=u'被相加的第一个数字')
cac_parser.add_argument('b', type=int, help=u'被相加的第二个数字')


class Calculator(Resource):
    @hmac_auth('api')
    def get(self):
        args = cac_parser.parse_args()
        return {'restful_result': args['a'] + args['b']}

api.add_resource(Calculator, '/rpc/accumulator')


