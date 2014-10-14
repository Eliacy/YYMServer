# -*- coding: utf-8 -*-

import time

from flask import jsonify, request, url_for
from flask.ext.restful import reqparse, Resource, fields, marshal_with, marshal
from flask.ext.hmacauth import hmac_auth

from YYMServer import app, db, cache, api, util
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
    def format(self, path):
        return url_for('static', filename=path, _external=True)


# 图片信息查询接口：
image_fields_mini = {
    'id': fields.Integer,
    'url': ImageUrl(attribute='path'),
}


# 用户信息查询接口：
user_fields_mini = {
    'id': fields.Integer,
    'icon': fields.Nested(image_fields_mini, attribute='icon_image'),   # 没有时会变成 id 为 0 的图片
    'name': fields.String,
}


# 分类及子分类接口：
category_fields = {
    'id': fields.Integer,
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
    'id': fields.Integer,
    'name': fields.String,
    'order': fields.Integer,
    'longitude': fields.Float,
    'latitude': fields.Float,
}


# 城市接口：
city_fields = {
    'id': fields.Integer,
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
    'id': fields.Integer,
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
site_parser.add_argument('brief', type=int, default=1)     # 大于 0 表示只输出概要信息即可（默认只概要）。
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

site_fields_mini = {
    'id': fields.Integer,
    'city_name': fields.String,         # POI 所在城市名
    'name': fields.String,
}
site_fields_brief = {
    'logo': fields.Nested(image_fields_mini, attribute='logo_image'),   # 没有时会变成 id 为 0 的图片
    'level': fields.String,
    'stars': fields.Float,
    'review_num': fields.Integer,
    'longitude': fields.Float,
    'latitude': fields.Float,
    'address': fields.String,
    'keywords': fields.List(fields.String, attribute='formated_keywords'),
    'top_images': fields.List(fields.Nested(image_fields_mini), attribute='valid_top_images'),
    'popular': fields.Integer,
}
site_fields_brief.update(site_fields_mini)
site_fields = {
    'name_orig': fields.String,
    'address_orig': fields.String,
    'gate_images': fields.List(fields.Nested(image_fields_mini), attribute='valid_gate_images'),
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
            site.logo_image = site.logo         # 为了缓存能工作
            site.city_name = '' if not site.area else site.area.city.name
            site.formated_keywords = [] if not site.keywords else site.keywords.translate({ord('{'):None, ord('}'):None}).split()
            site.valid_top_images = []
            if site.top_images:
                site.valid_top_images = util.get_images(site.top_images)
            site.valid_top_images = site.valid_top_images[:5]
            if not brief:
                site.valid_gate_images = []
                if site.gate_images:
                    site.valid_gate_images = util.get_images(site.gate_images)
                site.valid_gate_images = site.valid_gate_images[:1]
                site.valid_categories = [category.name for category in site.categories if category.parent_id != None]
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


# 晒单评论接口：
review_parser = reqparse.RequestParser()
review_parser.add_argument('brief', type=int, default=1)     # 大于 0 表示只输出概要信息即可（默认只概要）。
review_parser.add_argument('selected', type=int)     # 大于 0 表示只输出置顶信息即可（例如 POI 详情页面中的晒单评论），不够 limit 的要求时，会用非置顶信息补足。
review_parser.add_argument('published', type=int, default=1)     # 大于 0 表示只输出已发表的（默认只已发表的），否则也可输出草稿。
review_parser.add_argument('offset', type=int)    # offset 偏移量。
review_parser.add_argument('limit', type=int)     # limit 限制，与 SQL 语句中的 limit 含义一致。
review_parser.add_argument('id', type=int)
review_parser.add_argument('user', type=int)
review_parser.add_argument('site', type=int)    # 相关联的 POI id
review_parser.add_argument('city', type=int)    # 相关联的城市 id

review_fields_brief = {
    'id': fields.Integer,
    'selected': fields.Boolean,
    'published': fields.Boolean,
    'content': fields.String(attribute='brief_content'),   # brief 模式下，会将文字内容截断到特定长度
    'images': fields.List(fields.Nested(image_fields_mini), attribute='valid_images'),  # brief 模式下，只会提供一张图片
    'like_num': fields.Integer,
    'comment_num': fields.Integer,
    'images_num': fields.Integer,
    'user': fields.Nested(user_fields_mini, attribute='valid_user'),
    'publish_time': util.DateTime,    # RFC822-formatted datetime string in UTC
    'update_time': util.DateTime,    # RFC822-formatted datetime string in UTC
    'total': fields.Integer,
    'currency': fields.String,
    'site': fields.Nested(site_fields_mini, attribute='valid_site'),
}
review_fields = {
    'at_list': fields.List(fields.Nested(user_fields_mini), attribute='valid_at_users'),
    'keywords': fields.List(fields.String, attribute='formated_keywords'),
}
review_fields.update(review_fields_brief)
review_fields['content'] = fields.String        # 非 brief 模式下，提供完整的文字内容

class ReviewList(Resource):
    '''获取某 POI 的晒单评论列表，或者单独一条晒单评论详情的服务。'''
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    @cache.memoize()
    def _get(self, brief=None, selected = None, published = None, id=None, site=None, city=None, user=None):
        # ToDo: Review 表中各计数缓存值的数据没有做动态更新，例如“赞”数！
        query = db.session.query(Review).filter(Review.valid == True)
        query = query.order_by(Review.publish_time.desc())
        if id:
            query = query.filter(Review.id == id)
        if user:
            query = query.filter(Review.user_id == user)
        if site:
            query = query.filter(Review.site_id == site)
        if city:
            # ToDo: 搜索 POI 的时候，会把某城市中心点一定范围内的 POI （尽管是别的城市的）也放进来，那么搜 Review 时候是否也应该支持这个？
            query = query.join(Review.site).join(Site.area).filter(Area.city_id == city)
        result = []
        if selected == None:
            # ToDo: 后台需要有个定时任务，将被关注多的 Review 设置成 selected 。
            pass
        else:   # 要求只返回 selected 或者只返回一定没被 selected 的内容时：
            query = query.filter(Review.selected == selected)   # selected 取值为合法 boolean 这一点，由 get(self) 函数调用 _get 前负责保证！
        if published:
            query = query.filter(Review.published == True)
        for review in query:
            review.valid_user = review.user
            review.valid_user.icon_image = review.user.icon
            review.valid_site = review.site
            if review.site:
                review.valid_site.city_name = '' if not review.site.area else review.site.area.city.name
            review.images_num = 0 if not review.images else len(review.images.split())
            review.currency = review.currency or u'人民币'
            review.formated_keywords = [] if not review.keywords else review.keywords.split()
            review.valid_at_users = []
            if review.at_list:
                review.valid_at_users = util.get_users(review.at_list)
            review.valid_images = []
            if review.images:
                review.valid_images = util.get_images(review.images)
            if brief:
                review.brief_content = review.content[:80]
                review.valid_images = review.valid_images[:1]
            result.append(review)
        return result

    @hmac_auth('api')
    def get(self):
        # 如果 selected 数量不够，就得用没被 selected 的内容来补。
        args = review_parser.parse_args()
        brief = args['brief']
        selected = args['selected']
        limit = args['limit']
        if selected:
            result = self._get(brief, True, args['published'], args['id'], args['site'], args['city'], args['user'])
            if limit and len(result) < limit:
                result += self._get(brief, False, args['published'], args['id'], args['site'], args['city'], args['user'])
        else:
            result = self._get(brief, None, args['published'], args['id'], args['site'], args['city'], args['user'])
        offset = args['offset']
        if offset:
            result = result[offset:]
        limit = args['limit']
        if limit:
            result = result[:limit]
        if brief:
            return marshal(result, review_fields_brief)
        else:
            return marshal(result, review_fields)

api.add_resource(ReviewList, '/rpc/reviews')


# 二级子评论接口：
comment_parser = reqparse.RequestParser()
comment_parser.add_argument('review', type=int)         # 相关联的晒单评论 id


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


