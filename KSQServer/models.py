# -*- coding: utf-8 -*-

from sqlalchemy import event
from sqlalchemy import DDL

from KSQServer import db

class Country(db.Model):   # 国家
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, server_default='0')   # 控制是否用户可见
    name = db.Column(db.Unicode(20))    # 国家名称
    cities = db.relationship('City', backref='country', lazy='dynamic')

    def __unicode__(self):
        return u'<Country %s>' % self.name


class City(db.Model):   # 城市
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, server_default='0')   # 控制是否用户可见
    name = db.Column(db.Unicode(20))    # 城市名称
    areas = db.relationship('Area', backref='city', lazy='dynamic')
    country_id = db.Column(db.Integer, db.ForeignKey('country.id'))

    def __unicode__(self):
        return u'<City %s>' % self.name


class Area(db.Model):   # 商区
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, server_default='0')   # 控制是否用户可见
    name = db.Column(db.Unicode(20))    # 商区名称
    sites = db.relationship('Site', backref='area', lazy='dynamic')
    city_id = db.Column(db.Integer, db.ForeignKey('city.id'))

    def __unicode__(self):
        return u'<Area %s>' % self.name


class Brand(db.Model):   # 品牌
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, server_default='0')   # 控制是否用户可见
    name = db.Column(db.Unicode(20))    # 品牌名称
    name_zh = db.Column(db.Unicode(20))    # 品牌中文名称
    source = db.Column(db.Unicode(20))  # 发源地
    level = db.Column(db.Unicode(10))     # 品牌档次
    description = db.Column(db.UnicodeText)     # 品牌的简介描述
    sites = db.relationship('Site', backref='brand', lazy='dynamic')

    def __unicode__(self):
        return u'<Brand %s>' % self.name


categories = db.Table('categories',
    db.Column('category_id', db.Integer, db.ForeignKey('category.id')),
    db.Column('site_id', db.Integer, db.ForeignKey('site.id'))
)


class Site(db.Model):   # 店铺或景点等 POI
    id = db.Column(db.Integer, primary_key=True)        # ToDo：这个 id 应该考虑改成 UUID （已放弃，改为从特定数值开始）。
    valid = db.Column(db.Boolean, server_default='0')   # 控制是否用户可见
    code = db.Column(db.String(20))     # POI 的内部运营编号
    name = db.Column(db.Unicode(80))        # POI 的名字
    name_orig = db.Column(db.Unicode(80))       # POI 的当地文字原名
    brand_id = db.Column(db.Integer, db.ForeignKey('brand.id'))         # POI 所属品牌名称
    logo_id = db.Column(db.Integer, db.ForeignKey('image.id'))     # POI logo 首图的图片 id
    logo = db.relationship("Image")
    level = db.Column(db.Unicode(10))     # 用文字表示的 POI 质量等级，通常为 SS、S、A+、A 其中之一。
    stars = db.Column(db.Float)         # POI 的评论星级，由于是统计结果，因而存在半颗星等小数。
    comments = db.relationship('Comment', backref='site', lazy='dynamic')       # 相关的评论
    categories = db.relationship('Category', secondary=categories,
                                 backref=db.backref('sites', lazy='dynamic'))
    environment = db.Column(db.Unicode(50))      # 环境特点的文字描述
    flowrate = db.Column(db.Unicode(20))        # 人流量情况
    payment = db.Column(db.Unicode(50))         # 支持的支付方式
    menu = db.Column(db.Unicode(20))    # 是否提供中文菜单
    ticket = db.Column(db.Unicode(200))         # 门票票价及购买方式
    booking = db.Column(db.Unicode(200))        # 预定方式
    business_hours = db.Column(db.Unicode(200))         # 营业时间描述
    phone = db.Column(db.String(50))    # 联系电话
    description = db.Column(db.UnicodeText)     # POI 的简介描述
    longitude = db.Column(db.Float)     # 经度
    latitude = db.Column(db.Float)      # 纬度
    area_id = db.Column(db.Integer, db.ForeignKey('area.id'))   # 所属商区
    address = db.Column(db.Unicode(200))        # POI 地址
    address_orig = db.Column(db.Unicode(200))   # POI 地址的当地文字版本
    keywords = db.Column(db.Unicode(200))       # POI 关键词
    top_images = db.Column(db.String(100))      # 热门图片的 id 列表
    data_source = db.Column(db.Unicode(200))    # 本 POI 数据采集的原始网址

    def __unicode__(self):
        return u'<Site %s>' % self.name


event.listen(
    Site.__table__,
    "after_create",
    DDL("ALTER TABLE %(table)s AUTO_INCREMENT = 3421;").execute_if(dialect=('postgresql', 'mysql'))
)


class Category(db.Model):       # POI 分类
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, server_default='0')   # 控制是否用户可见
    name = db.Column(db.Unicode(20))    # 类别名称
    parent_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    children = db.relationship("Category")

    def __unicode__(self):
        return u'<Category %s>' % self.name


class Image(db.Model):  # 全局图片存储
    id = db.Column(db.Integer, primary_key=True)        # ToDo：考虑改为 UUID 。
    type = db.Column(db.SmallInteger)   # 图片分类：1 表示店铺 logo；2 表示用户头像；3 表示评论图片。
    path = db.Column(db.String(120))    # 图片所在存储路径

    def __unicode__(self):
        return u'<Image %s>' % self.path.split('/')[-1]


class Comment(db.Model):        # 用户晒单评论
    id = db.Column(db.Integer, primary_key=True)        # ToDo: 考虑改为 UUID（已放弃，改为从特定数值开始）。
    valid = db.Column(db.Boolean, server_default='0')   # 控制是否当做已删除处理
    published = db.Column(db.Boolean, server_default='0')       # 控制是否对外发布
    time = db.Column(db.DateTime)       # 评论发表时间，以服务器时间为准
    site_id = db.Column(db.Integer, db.ForeignKey('site.id'))   # 关联的 POI

#    def __unicode__(self):
#        return u'<Comment %s>' % self.name


event.listen(
    Comment.__table__,
    "after_create",
    DDL("ALTER TABLE %(table)s AUTO_INCREMENT = 2991;").execute_if(dialect=('postgresql', 'mysql'))
)


