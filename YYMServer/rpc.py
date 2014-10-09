# -*- coding: utf-8 -*-

import time

from flask import jsonify, request, url_for
from flask.ext.restful import reqparse, Resource, fields, marshal_with, marshal
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


# 常用公共辅助：
id_parser = reqparse.RequestParser()
id_parser.add_argument('id', type=int)


class ImageUrl(fields.Raw):
    def format(self, image):
        return url_for('static', filename=image.path, _external=True)


# 分类及子分类接口：
category_fields = {
    'id':fields.Integer,
    'name': fields.String,
    'order': fields.Integer,
}

nested_category_fields = {
    'sub_categories': fields.List(fields.Nested(category_fields), attribute='valid_sub_categories'),
}
nested_category_fields.update(category_fields)


class CategoryList(Resource):
    '''获取 POI 分类及子分类列表。'''

    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    @cache.memoize()
    def _get(self, id=None):
        query = db.session.query(Category).filter(Category.valid == True).filter(Category.parent_id == None).order_by(Category.order.desc())
        if id:
            query = query.filter(Category.id == id)
        result = []
        for category in query:
            category.valid_sub_categories = category.children.filter(Category.valid == True).order_by(Category.order.desc()).all()
            result.append(category)
        return result

    @hmac_auth('api')
    @marshal_with(nested_category_fields)
    def get(self):
        args = id_parser.parse_args()
        id = args['id']
        return self._get(id)

api.add_resource(CategoryList, '/rpc/categories')


# 商区接口：
area_fields = {
    'id':fields.Integer,
    'name': fields.String,
    'order': fields.Integer,
    'longitude': fields.Float,
    'latitude': fields.Float,
}


# 城市接口：
city_fields = {
    'id':fields.Integer,
    'name': fields.String,
    'order': fields.Integer,
    'longitude': fields.Float,
    'latitude': fields.Float,
}

nested_city_fields = {
    'areas': fields.List(fields.Nested(area_fields), attribute='valid_areas'),
}
nested_city_fields.update(city_fields)


class CityList(Resource):
    '''获取全部城市及指定城市名字的服务，也可用于查询指定城市下的商圈列表。'''

    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    @cache.memoize()
    def _get(self, id=None):
        query = db.session.query(City).filter(City.valid == True).order_by(City.order.desc())
        if id:
            query = query.filter(City.id == id)
        result = []
        for city in query:
            city.valid_areas = city.areas.filter(Area.valid == True).order_by(Area.order.desc()).all()
            result.append(city)
        return result

    @hmac_auth('api')
    @marshal_with(nested_city_fields)
    def get(self):
        args = id_parser.parse_args()
        id = args['id']
        return self._get(id)

api.add_resource(CityList, '/rpc/cities')


# 国家接口：
country_fields = {
    'id':fields.Integer,
    'name': fields.String,
    'order': fields.Integer,
    'default_city_id': fields.Integer,
    'cities': fields.List(fields.Nested(city_fields), attribute='valid_cities'),
}

class CountryList(Resource):
    '''获取全部国家及指定国家名字的服务，也可用于查询指定国家下属的城市列表。'''

    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    @cache.memoize()
    def _get(self, id=None):
        query = db.session.query(Country).filter(Country.valid == True).order_by(Country.order.desc())
        if id:
            query = query.filter(Country.id == id)
        result = []
        for country in query:
            country.valid_cities = country.cities.filter(City.valid == True).order_by(City.order.desc()).all()
            result.append(country)
        return result

    @hmac_auth('api')
    @marshal_with(country_fields)
    def get(self):
        args = id_parser.parse_args()
        id = args['id']
        return self._get(id)

api.add_resource(CountryList, '/rpc/countries')


# POI 接口：
site_parser = reqparse.RequestParser()
site_parser.add_argument('brief', type=int)     # 大于 0 表示只输出概要信息即可。
site_parser.add_argument('offset', type=int)    # offset 偏移量。
site_parser.add_argument('limit', type=int)     # limit 限制，与 SQL 语句中的 limit 含义一致。
site_parser.add_argument('id', type=int)
site_parser.add_argument('keywords', type=unicode)  # 搜索关键词，空格或英文加号分隔，默认的关系是“且”。搜索时大小写不敏感。
site_parser.add_argument('area', type=int)      # 商圈 id。
site_parser.add_argument('city', type=int)      # 城市 id。
site_parser.add_argument('range', type=int)     # 范围公里数。如果是 -1，则表示“全城”。如果商圈、范围都是空，则表示默认的“智能范围”。
site_parser.add_argument('category', type=int)  # 分类 id。为空则表示“全部分类”。
site_parser.add_argument('order', type=int)     # 0 表示默认的“智能排序”，1 表示“距离最近”（约近约靠前），2 表示“人气最高”（点击量由高到低），3 表示“评价最好”（评分由高到低）。
site_parser.add_argument('longitude', type=float)       # 用户当前位置的经度
site_parser.add_argument('latitude', type=float)        # 用户当前位置的维度

site_fields_brief = {
    'id':fields.Integer,
    'logo': ImageUrl(attribute='logo_image'),   # 没有就是 null
    'name': fields.String,
    'level': fields.String,
    'stars': fields.Float,
    'review_num': fields.Integer,
    'longitude': fields.Float,
    'latitude': fields.Float,
    'address': fields.String,
    'keywords': fields.List(fields.String, attribute='formated_keywords'),
    'top_images': fields.List(ImageUrl, attribute='valid_top_images'),
    'popular': fields.Integer,
}
site_fields = {
    'name_orig': fields.String,
    'address_orig': fields.String,
    'gate_images': fields.List(ImageUrl, attribute='valid_gate_images'),
    'categories': fields.List(fields.String, attribute='valid_categories'),
    'environment': fields.String,       # 空字符串表示没有
    'payment': fields.String,   # 空字符串表示没有
    'menu': fields.String,      # 空字符串表示没有
    'ticket': fields.String,    # 空字符串表示没有
    'booking': fields.String,   # 空字符串表示没有
    'business_hours': fields.String,    # 空字符串表示没有
    'phone': fields.String,     # 空字符串表示没有
    'transport': fields.String,         # 空字符串表示没有
    'description': fields.String,       # 空字符串表示没有
    'images_num': fields.Integer,
}
site_fields.update(site_fields_brief)

# ToDo: 欠一个搜索关键字推荐接口！
class SiteList(Resource):
    '''“附近”搜索功能对应的 POI 列表获取。'''
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    @cache.memoize()
    def _get(self, brief=None, id=None, keywords=None, area=None, city=None, range=None, category=None, order=None, geohash=None):
        # ToDo: Site 表中各计数缓存值的数据没有做动态更新，例如晒单评论数！
        if not area and (range == None or range == 0):
            range = 5   # ToDo: 如果商圈和 range 都没有设置，表示智能范围（注意：range 为 -1 时表示全城搜索）。这里暂时只是把搜索范围置成5公里了。
        query = db.session.query(Site).filter(Site.valid == True)
        if order:
            if order == 1:      # 距离最近：
                pass
            elif order == 2:    # 人气最高：
                query = query.order_by(Site.popular.desc())
            elif order == 3:    # 评价最好：
                query = query.order_by(Site.stars.desc())
            else:       # 这是默认的“智能排序”:
                query = query.order_by(Site.order.desc())
        if id:
            query = query.filter(Site.id == id)
        if area:
            query = query.filter(Site.area_id == area)
        if city:
            query = query.join(Site.area).filter(Area.city_id == city)
            # ToDo: 除了直接使用 city id 判断外，还应该把城市中心点距离一定范围内（即使是属于其他城市的）的 POI 纳入搜索结果！
        if category:
            query = query.join(Site.categories).filter(Category.id == category)
        if keywords:
            # 搜索关键词目前支持在 POI 名称、地址的中文、原文中进行模糊搜索。
            keywords = keywords.translate({ord('+'):' '})
            keyword_list = keywords.split()
            for keyword in keyword_list:
                query = query.filter(Site.name.ilike(u'%{}%'.format(keyword)) | 
                                     Site.name_orig.ilike(u'%{}%'.format(keyword)) |
                                     Site.address.ilike(u'%{}%'.format(keyword)) |
                                     Site.address_orig.ilike(u'%{}%'.format(keyword)) 
                                    )
        result = []
        for site in query:
            site.stars = site.stars or 0.0      # POI 无星级时输出0，表示暂无评分。
            site.environment = site.environment or ''
            site.payment = site.payment or ''
            site.menu = site.menu or ''
            site.ticket = site.ticket or ''
            site.booking = site.booking or ''
            site.business_hours = site.business_hours or ''
            site.phone = site.phone or ''
            site.transport = site.transport or ''
            site.description = site.description or ''
            site.logo_image = site.logo
            site.formated_keywords = [] if not site.keywords else site.keywords.translate({ord('{'):None, ord('}'):None}).split()
            valid_top_images = []
            if site.top_images:
                for image_id in site.top_images:
                    image = db.session.query(Image).get(image_id)
                    if image:
                        valid_top_images.append(image)
            site.valid_top_images = valid_top_images[:5]
            if not brief:
                valid_gate_images = []
                if site.gate_images:
                    for image_id in site.gate_images:
                        image = db.session.query(Image).get(image_id)
                        if image:
                            valid_gate_images.append(image)
                site.valid_gate_images = valid_gate_images[:1]
                site.valid_categories = [category for category in site.categories if category.parent_id != None]
            result.append(site)
        return result

    @hmac_auth('api')
    def get(self):
        args = site_parser.parse_args()
        # ToDo: 基于距离范围的搜索暂时没有实现！
        # ToDo: 按距离最近排序暂时没有实现！
        longitude = args['longitude']
        latitude = args['latitude']
        geohash = None
        # 其他基本搜索条件处理：
        brief = args['brief']
        result = self._get(brief, args['id'], args['keywords'], args['area'], args['city'], args['range'], args['category'], args['order'], geohash)
        offset = args['offset']
        if offset:
            result = result[offset:]
        limit = args['limit']
        if limit:
            result = result[:limit]
        if brief:
            return marshal(result, site_fields_brief)
        else:
            return marshal(result, site_fields)

api.add_resource(SiteList, '/rpc/sites')


# ==== json 网络服务样例 ====
cac_parser = reqparse.RequestParser()
cac_parser.add_argument('a', type=int, help=u'被相加的第一个数字')
cac_parser.add_argument('b', type=int, help=u'被相加的第二个数字')


class Calculator(Resource):
    @hmac_auth('demo')
    def get(self):
        args = cac_parser.parse_args()
        return {'restful_result': args['a'] + args['b']}

api.add_resource(Calculator, '/rpc/accumulator')


