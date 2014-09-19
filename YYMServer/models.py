# -*- coding: utf-8 -*-

import datetime

from sqlalchemy import event
from sqlalchemy import DDL
from werkzeug.security import generate_password_hash

from YYMServer import db


class Real(db.REAL):
    """ Flask-admin 通过读取 Column Type 的 scale 参数确定编辑/创建表单的数字小数点后位数，因此创建本封装类强制使用高精度。"""
    scale = 10


class Country(db.Model):   # 国家
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, default=False)   # 控制是否用户可见
    order = db.Column(db.Integer, default=0)    # 控制在前台的显示顺序
    name = db.Column(db.Unicode(20))    # 国家名称
    extend = db.Column(db.SmallInteger, default=0)      # 确定当搜索该国家下属的城市内店铺时，允许也纳入距离城市中心点多远的店铺（单位：公里，默认：50）
    cities = db.relationship('City', backref='country', lazy='dynamic')

    def __unicode__(self):
        return u'<Country %s>' % self.name


class City(db.Model):   # 城市
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, default=False)   # 控制是否用户可见
    order = db.Column(db.Integer, default=0)    # 控制在前台的显示顺序
    name = db.Column(db.Unicode(20))    # 城市名称
    longitude = db.Column(Real)     # 城市中心点，经度
    latitude = db.Column(Real)      # 城市中心点，纬度
    areas = db.relationship('Area', backref='city', lazy='dynamic')
    country_id = db.Column(db.Integer, db.ForeignKey('country.id'))

    def __unicode__(self):
        return u'<City %s>' % self.name


class Area(db.Model):   # 商区
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, default=False)   # 控制是否用户可见
    order = db.Column(db.Integer, default=0)    # 控制在前台的显示顺序
    name = db.Column(db.Unicode(20))    # 商区名称
    longitude = db.Column(Real)     # 商圈中心点，经度
    latitude = db.Column(Real)      # 商圈中心点，纬度
    sites = db.relationship('Site', backref='area', lazy='dynamic')
    city_id = db.Column(db.Integer, db.ForeignKey('city.id'))

    def __unicode__(self):
        return u'<Area %s>' % self.name


class Brand(db.Model):   # 品牌
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, default=False)   # 控制是否用户可见
    order = db.Column(db.Integer, default=0)    # 控制在前台的显示顺序
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
    valid = db.Column(db.Boolean, default=False)   # 控制是否用户可见
    order = db.Column(db.Integer, default=0)    # 控制在前台的显示顺序
    create_time = db.Column(db.DateTime, default=datetime.datetime.now)        # 数据最初创建时间，以服务器时间为准
    update_time = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)        # 数据修改时间，以服务器时间为准
    code = db.Column(db.String(20))     # POI 的内部运营编号
    name = db.Column(db.Unicode(80))        # POI 的名字
    name_orig = db.Column(db.Unicode(80))       # POI 的当地文字原名
    brand_id = db.Column(db.Integer, db.ForeignKey('brand.id'))         # POI 所属品牌名称
    logo_id = db.Column(db.Integer, db.ForeignKey('image.id'))     # POI logo 首图的图片 id
    logo = db.relationship('Image')
    level = db.Column(db.Unicode(10))     # 用文字表示的 POI 质量等级，通常为 SS、S、A+、A 其中之一。
    stars = db.Column(db.Float)         # POI 的评论星级，由于是统计结果，因而存在半颗星等小数。
    review_num = db.Column(db.SmallInteger, default=0)    # 该店铺拥有的晒单评论数量，是一个缓存值
    reviews = db.relationship('Review', backref='site', lazy='dynamic')       # 相关的评论
    categories = db.relationship('Category', secondary=categories,
                                 backref=db.backref('sites', lazy='dynamic'))
    environment = db.Column(db.Unicode(50))      # 环境特点的文字描述
    flowrate = db.Column(db.Unicode(20))        # 人流量情况
    payment = db.Column(db.Unicode(50))         # 支持的支付方式
    menu = db.Column(db.Unicode(20))    # 是否提供中文菜单
    ticket = db.Column(db.Unicode(200))         # 门票票价及购买方式，应支持换行符“\n”
    booking = db.Column(db.Unicode(200))        # 预定方式，应支持换行符“\n”
    business_hours = db.Column(db.Unicode(200))         # 营业时间描述，应支持换行符“\n”
    phone = db.Column(db.String(50))    # 联系电话
    transport = db.Column(db.Unicode(200))          # 公共交通的线路和站点文字描述，应支持换行符“\n”
    description = db.Column(db.UnicodeText)     # POI 的简介描述
    longitude = db.Column(Real)     # 经度
    latitude = db.Column(Real)      # 纬度
    area_id = db.Column(db.Integer, db.ForeignKey('area.id'))   # 所属商区
    address = db.Column(db.Unicode(200))        # POI 地址，应支持换行符“\n”
    address_orig = db.Column(db.Unicode(200))   # POI 地址的当地文字版本，应支持换行符“\n”
    keywords = db.Column(db.Unicode(200))       # POI 关键词，可以认为是一个缓存，被 {} 括起来的是系统自动统计得到的，其他是运营人工设置。正常情况是使用空格分隔
    top_images = db.Column(db.String(100))      # 热门图片的 id 列表，英文空格分隔
    gate_images = db.Column(db.String(100))     # 店铺门脸展示图片的 id 列表，英文空格分隔
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
    valid = db.Column(db.Boolean, default=False)   # 控制是否用户可见
    order = db.Column(db.Integer, default=0)    # 控制在前台的显示顺序
    name = db.Column(db.Unicode(20))    # 类别名称
    parent_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    parent = db.relationship('Category', remote_side=[id], backref='children')

    def __unicode__(self):
        return u'<Category %s>' % self.name


fans = db.Table('fans',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('fan_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('action_time', db.DateTime, default=datetime.datetime.now)        # 发生关注行为的时间点
)


likes = db.Table('likes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('review_id', db.Integer, db.ForeignKey('review.id')),
    db.Column('action_time', db.DateTime, default=datetime.datetime.now)        # 用户表示喜欢一篇晒单评论的时间点
)


favorites = db.Table('favorites',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('site_id', db.Integer, db.ForeignKey('site.id')),
    db.Column('action_time', db.DateTime, default=datetime.datetime.now)        # 用户收藏一个店铺的时间点
)


class ShareRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # 进行共享的人
    user = db.relationship('User', backref=db.backref('share_records', lazy='dynamic'), foreign_keys=[user_id])
    site_id = db.Column(db.Integer, db.ForeignKey('site.id'))     # 如果被共享的是店铺，则在这里做绑定
    site = db.relationship('Site')
    review_id = db.Column(db.Integer, db.ForeignKey('review.id'))     # 如果被共享的是晒单评论，则在这里做绑定
    review = db.relationship('Review')
    target = db.Column(db.Unicode(20))  # 用户分享的目的地，比如微信或短信，中文文字描述
    action_time = db.Column(db.DateTime, default=datetime.datetime.now)       # 用户分享文章或店铺的时间点

    def __unicode__(self):
        return u'<ShareRecord %s: site %d, review %d>' % (self.user.name, self.site_id or -1, self.review_id or -1)


class User(db.Model):
    id = db.Column(db.Integer, autoincrement='ignore_fk', primary_key=True)
    create_time = db.Column(db.DateTime, default=datetime.datetime.now)       # 首次创建时间，以服务器时间为准
    update_time = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)       # 用户属性信息修改时间，以服务器时间为准
    name = db.Column(db.Unicode(100))    # 可见用户昵称
    username = db.Column(db.String(80), unique=True)    # 登陆用用户名，App 端会是设备 id（匿名用户）或手机号（已注册用户）
    mobile = db.Column(db.String(120), unique=True)     # 用户手机号
    password = db.Column(db.String(80))         # Hash 处理之后的登陆密码
    icon_id = db.Column(db.Integer, db.ForeignKey('image.id', use_alter=True, name='fk_icon'))     # 用户头像的图片 id
    icon = db.relationship('Image', foreign_keys=[icon_id], post_update=True)
    gender = db.Column(db.Unicode(10), default=u'未知')  # 用户填写的性别参数：男、女、未知
    level = db.Column(db.SmallInteger, default=1)     # 用数字表示的用户等级
    follow_num = db.Column(db.SmallInteger, default=0)  # 该用户已关注的账号的数量，是一个缓存值
    fans_num = db.Column(db.SmallInteger, default=0)    # 该用户拥有的粉丝数量，是一个缓存值
    fans = db.relationship('User', secondary=fans,
                                   primaryjoin=id==fans.c.user_id,
                                   secondaryjoin=id==fans.c.fan_id,
                                   backref=db.backref('follows', lazy='dynamic'))
    like_num = db.Column(db.SmallInteger, default=0)    # 该用户喜欢的晒单评论数量，是一个缓存值
    likes = db.relationship('Review', secondary=likes,
                                      backref=db.backref('fans', lazy='dynamic'))
    share_num = db.Column(db.SmallInteger, default=0)   # 该用户的分享行为数量，是一个缓存值
    review_num = db.Column(db.SmallInteger, default=0)    # 该用户发表的晒单评论数量，是一个缓存值
    favorite_num = db.Column(db.SmallInteger, default=0)    # 该用户收藏的店铺的数量，是一个缓存值
    favorites = db.relationship('Site', secondary=favorites,
                                      backref=db.backref('fans', lazy='dynamic'))
    badges = db.Column(db.Unicode(500))  # 用户拥有的徽章名称列表

    def is_admin(self):
        return True if self.id >= 321 and self.id <=323 else False

    # Flask-Login integration
    def is_authenticated(self):
        return True

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return self.id

    # Required for administrative interface
    def __unicode__(self):
        return u'<User %s>' % self.name


event.listen(
    User.__table__,
    "after_create",
    DDL("ALTER TABLE %(table)s AUTO_INCREMENT = 321;").execute_if(dialect=('postgresql', 'mysql'))
)

@event.listens_for(User, 'before_insert')
@event.listens_for(User, 'before_update')
def encrypt_password(mapper, connection, target):
    if not target.password.startswith('pbkdf2:sha1:'):
        target.password = generate_password_hash(target.password)


class Image(db.Model):  # 全局图片存储
    id = db.Column(db.Integer, primary_key=True)        # ToDo：考虑改为 UUID 。
    valid = db.Column(db.Boolean, default=True)   # 控制是否当作已删除处理（False 表示删除）
    type = db.Column(db.SmallInteger, default=1)   # 图片分类：1 表示店铺 logo；2 表示店铺门脸图；3 表示用户头像；4 表示评论图片。
    path = db.Column(db.String(120))    # 图片所在存储路径
    note = db.Column(db.Unicode(120))   # 图片的备忘描述文字
    create_time = db.Column(db.DateTime, default=datetime.datetime.now)       # 图片上传时间，以服务器时间为准
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # 图片上传人
    user = db.relationship('User', backref=db.backref('images', lazy='dynamic'), foreign_keys=[user_id])

    def __unicode__(self):
        return u'<Image %s>' % 'None' if not self.path else self.path.split('/')[-1]


class Review(db.Model):        # 用户晒单评论
    id = db.Column(db.Integer, primary_key=True)        # ToDo: 考虑改为 UUID（已放弃，改为从特定数值开始）。
    valid = db.Column(db.Boolean, default=False)   # 控制是否当作已删除处理（False 表示删除）
    published = db.Column(db.Boolean, default=False)       # 控制是否对外发布
    publish_time = db.Column(db.DateTime, default=None)       # 首次发布时间，以服务器时间为准
    update_time = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)       # 评论修改时间，以服务器时间为准
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # 晒单评论的作者
    user = db.relationship('User', backref=db.backref('reviews', lazy='dynamic'))
    at_list = db.Column(db.String(200))         # 本评论将@的用户 id 列表，后端代码需要实现注意控制长度！
    stars = db.Column(db.Float)         # POI 的评论星级，出于与统计结果，使用小数表示，实际只能是1～5
    content = db.Column(db.UnicodeText)         # 晒单评论的文本正文，只需分自然段，无需支持特殊格式。
    images = db.Column(db.String(200))  # 晒单评论的附属图片的 id 列表
    keywords = db.Column(db.Unicode(200))       # 晒单评论关键词，空格分隔
    total = db.Column(db.Integer)       # 本次购物总价
    currency = db.Column(db.Unicode(10))        # 购物总价所对应的币种，这里没有做强制类别限制，需要在接收前端数据前作检查、判断
    site_id = db.Column(db.Integer, db.ForeignKey('site.id'))   # 关联的 POI
    like_num = db.Column(db.Integer, default=0)        # 喜欢本晒单的人数，这只是相当于一个缓存，实际数据根据“喜欢”的行为表计算得出
    comment_num = db.Column(db.Integer, default=0)      # 本晒单的评论总数，只是一个缓存值，实际数据根据“评论”的行为表计算得出

    def __unicode__(self):
        return u'<Review %s: %s>' % (self.user.name, self.update_time.strftime('%y-%m-%d'))


event.listen(
    Review.__table__,
    "after_create",
    DDL("ALTER TABLE %(table)s AUTO_INCREMENT = 2991;").execute_if(dialect=('postgresql', 'mysql'))
)


class Comment(db.Model):        # 用户子评论
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, default=False)   # 控制是否当作已删除处理（False 表示删除）
    publish_time = db.Column(db.DateTime, default=datetime.datetime.now)       # 首次发布时间，以服务器时间为准
    update_time = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)       # 评论修改时间，以服务器时间为准
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # 评论的作者
    user = db.relationship('User', backref=db.backref('comments', lazy='dynamic'))
    at_list = db.Column(db.String(200))         # 本评论将@的用户 id 列表，通常子评论只能@一个人，也就是所回复的子评论的原作者
    content = db.Column(db.Unicode(500))        # 评论的文字正文，需要注意检查内容长度

    def __unicode__(self):
        return u'<Comment %s: %s>' % (self.user.name, self.update_time.strftime('%y-%m-%d'))


