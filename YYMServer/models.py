# -*- coding: utf-8 -*-

import datetime, random, time, uuid

from sqlalchemy import event
from sqlalchemy import DDL
from werkzeug.security import generate_password_hash

from YYMServer import db

random.seed()


class Real(db.REAL):
    """ Flask-admin 通过读取 Column Type 的 scale 参数确定编辑/创建表单的数字小数点后位数，因此创建本封装类强制使用高精度。"""
    scale = 10


#####################################################################################################
## 注意：所有 Model 中的 DateTime 都会被当做时区 'Asia/Shanghai' 中的时间进行后续处理！输入输出时可能需要做时区转换！
#####################################################################################################

PAYMENT_TYPES = {'V': u'Visa',
                 'M': u'Master',
                 'Amex': u'American Express',
                 'D': u'Discover',
                 'UP': u'银联',
                 'PP': u'Paypal',
                 'Ali': u'支付宝',
                 'JCB': u'JCB',
                 'GW': u'Google Wallet',
                 'AP': u'Amazon Payment',
                 'WU': u'Western Union',
                 'DC': u'Diners Club',
                 'JCB': u'JCB',
                 'HSBC': u'HSBC',
                 'Serve': u'Serve',
                 'Cash': u'Cash Only',
                 'Mae': u'Masestro',
                 'VE': u'Visa Electron',
                 'YM': u'Yandex Money',
                 'CPYW': u'Cash Pay Your Way',
                 'QIWI': u'QIWI Wallet',
                 'moneta': u'moneta ru',
                 'ZONG': u'ZONG',
                 'boku': u'boku',
                 'BML': u'Bill Me Later',
                 'CB': u'Click and Buy',
                 }
payment_types = dict(([key.lower(), value] for key, value in PAYMENT_TYPES.items()))

# ToDo: 需要给每组用户默认属性指定一个默认 icon 图片 id ！
DEFAULT_USER_GROUPS = ((u'美丽', None),  # (昵称前缀, 该组默认头像)
                       (u'幸福', None),
                       (u'快乐', None),
                       (u'高雅', None),
                       (u'智慧', None),
                       (u'可爱', None),
                       )
CHINESE_MONTHS = {1: u'一月',
                  2: u'二月',
                  3: u'三月',
                  4: u'四月',
                  5: u'五月',
                  6: u'六月',
                  7: u'七月',
                  8: u'八月',
                  9: u'九月',
                  10: u'十月',
                  11: u'十一月',
                  12: u'十二月',
                  }


class TextLib(db.Model):   # 供替换用的文本库
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, default=True)   # 控制是否用户可见
    create_time = db.Column(db.DateTime, default=datetime.datetime.now)        # 数据最初创建时间，以服务器时间为准
    update_time = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)        # 数据修改时间，以服务器时间为准
    create_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # 品牌信息上传人
    create_user = db.relationship('User', backref=db.backref('created_textlibs', lazy='dynamic'), foreign_keys=[create_user_id])
    update_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # 品牌信息最后修改人
    update_user = db.relationship('User', backref=db.backref('updated_textlibs', lazy='dynamic'), foreign_keys=[update_user_id])
    note = db.Column(db.Unicode(80), default=u'')    # 提示文本内容、用途的简短信息
    content = db.Column(db.UnicodeText)     # 品牌的简介描述

    def __unicode__(self):
        return u'<TextLib [%d] %s>' % (self.id, self.note)


class Country(db.Model):   # 国家
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, default=False)   # 控制是否用户可见
    order = db.Column(db.Integer, default=0)    # 控制在前台的显示顺序，数字越大越靠前
    name = db.Column(db.Unicode(20), default=u'')    # 国家名称
    extend = db.Column(db.SmallInteger, default=0)      # 确定当搜索该国家下属的城市内店铺时，允许也纳入距离城市中心点多远的店铺（单位：公里，默认：50）
    default_city_id = db.Column(db.Integer, db.ForeignKey('city.id', use_alter=True, name='fk_default_city'))   # 每个国家指定一个默认城市，用于天气预报等
    default_city = db.relationship('City', foreign_keys=[default_city_id], post_update=True)

    def __unicode__(self):
        return u'<Country [%d] %s>' % (self.id, self.name)


class City(db.Model):   # 城市
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, default=False)   # 控制是否用户可见
    order = db.Column(db.Integer, default=0)    # 控制在前台的显示顺序，数字越大越靠前
    name = db.Column(db.Unicode(20), default=u'')    # 城市名称
    longitude = db.Column(Real, default=0.0)     # 城市中心点，经度
    latitude = db.Column(Real, default=0.0)      # 城市中心点，纬度
    # ToDo: 这里需要一个用于查询天气的唯一代码的字段！
    country_id = db.Column(db.Integer, db.ForeignKey('country.id'))
    country = db.relationship('Country', backref=db.backref('cities', lazy='dynamic'), foreign_keys=[country_id])

    def __unicode__(self):
        return u'<City [%d] %s>' % (self.id, self.name)


class Area(db.Model):   # 商区
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, default=False)   # 控制是否用户可见
    order = db.Column(db.Integer, default=0)    # 控制在前台的显示顺序，数字越大越靠前
    name = db.Column(db.Unicode(20), default=u'')    # 商区名称
    longitude = db.Column(Real, default=0.0)     # 商圈中心点，经度
    latitude = db.Column(Real, default=0.0)      # 商圈中心点，纬度
    city_id = db.Column(db.Integer, db.ForeignKey('city.id'))
    city = db.relationship('City', backref=db.backref('areas', lazy='dynamic'))

    def __unicode__(self):
        return u'<Area [%d] %s>' % (self.id, self.name)


class Brand(db.Model):   # 品牌
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, default=False)   # 控制是否用户可见
    order = db.Column(db.Integer, default=0)    # 控制在前台的显示顺序，数字越大越靠前
    create_time = db.Column(db.DateTime, default=datetime.datetime.now)        # 数据最初创建时间，以服务器时间为准
    update_time = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)        # 数据修改时间，以服务器时间为准
    create_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # 品牌信息上传人
    create_user = db.relationship('User', backref=db.backref('created_brands', lazy='dynamic'), foreign_keys=[create_user_id])
    update_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # 品牌信息最后修改人
    update_user = db.relationship('User', backref=db.backref('updated_brands', lazy='dynamic'), foreign_keys=[update_user_id])
    name = db.Column(db.Unicode(80), default=u'')    # 品牌名称
    name_zh = db.Column(db.Unicode(80), default=u'')    # 品牌中文名称
    source = db.Column(db.Unicode(20), default=u'')  # 发源地
    level = db.Column(db.Unicode(10), default=u'')     # 品牌档次
    description = db.Column(db.UnicodeText)     # 品牌的简介描述

    def __unicode__(self):
        return u'<Brand [%d] %s>' % (self.id, self.name)


categories = db.Table('categories',
    db.Column('category_id', db.Integer, db.ForeignKey('category.id')),
    db.Column('site_id', db.Integer, db.ForeignKey('site.id'))
)


class Site(db.Model):   # 店铺或景点等 POI
    id = db.Column(db.Integer, primary_key=True)        # ToDo：这个 id 应该考虑改成 UUID （已放弃，改为从特定数值开始）。
    valid = db.Column(db.Boolean, default=False)   # 控制是否用户可见
    order = db.Column(db.Integer, default=0)    # 控制在前台的显示顺序，数字越大越靠前
    create_time = db.Column(db.DateTime, default=datetime.datetime.now)        # 数据最初创建时间，以服务器时间为准
    update_time = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)        # 数据修改时间，以服务器时间为准
    create_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # POI 信息上传人
    create_user = db.relationship('User', backref=db.backref('created_sites', lazy='dynamic'), foreign_keys=[create_user_id])
    update_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # POI 信息最后修改人
    update_user = db.relationship('User', backref=db.backref('updated_sites', lazy='dynamic'), foreign_keys=[update_user_id])
    code = db.Column(db.String(20), default='')     # POI 的内部运营编号
    name = db.Column(db.Unicode(80), default=u'')        # POI 的名字
    name_orig = db.Column(db.Unicode(80), default=u'')       # POI 的当地文字原名
    brand_id = db.Column(db.Integer, db.ForeignKey('brand.id'))         # POI 所属品牌名称
    brand = db.relationship('Brand', backref=db.backref('sites', lazy='dynamic'))
    logo_id = db.Column(db.Integer, db.ForeignKey('image.id'))     # POI logo 首图的图片 id
    logo = db.relationship('Image')
    level = db.Column(db.Unicode(10), default=u'')     # 用文字表示的 POI 质量等级，通常为 SS、S、A+、A 其中之一。
    stars = db.Column(db.Float, default=0.0)         # POI 的评论星级，由于是统计结果，因而存在半颗星等小数。
    popular = db.Column(db.Integer, default=0)    # 统计店铺人气指数，用于搜索排序，每天更新！
    review_num = db.Column(db.SmallInteger, default=0)    # 该店铺拥有的晒单评论数量，是一个缓存值
    categories = db.relationship('Category', secondary=categories,
                                 backref=db.backref('sites', lazy='dynamic'))
    environment = db.Column(db.Unicode(50), default=u'')      # 环境特点的文字描述
    flowrate = db.Column(db.Unicode(20), default=u'')        # 人流量情况
    payment = db.Column(db.Unicode(50), default=u'')         # 支持的支付方式
    menu = db.Column(db.Unicode(20), default=u'')    # 是否提供中文菜单
    ticket = db.Column(db.UnicodeText)         # 门票票价及购买方式，应支持换行
    booking = db.Column(db.UnicodeText)        # 预定方式，应支持换行
    business_hours = db.Column(db.UnicodeText)         # 营业时间描述，应支持换行，支持 {{text:id#注释}} 样式的标准文本替换
    phone = db.Column(db.UnicodeText)    # 联系电话
    transport = db.Column(db.UnicodeText)          # 公共交通的线路和站点文字描述，应支持换行
    description = db.Column(db.UnicodeText)     # POI 的简介描述
    longitude = db.Column(Real, default=0.0)     # 经度
    latitude = db.Column(Real, default=0.0)      # 纬度
    # ToDo: 缺经纬度对应的方格坐标的缓存字段！
    area_id = db.Column(db.Integer, db.ForeignKey('area.id'))   # 所属商区
    area = db.relationship('Area', backref=db.backref('sites', lazy='dynamic'))
    address = db.Column(db.UnicodeText)        # POI 地址，应支持换行
    address_orig = db.Column(db.UnicodeText)   # POI 地址的当地文字版本，应支持换行
    keywords = db.Column(db.Unicode(200), default=u'')       # POI 关键词，可以认为是一个缓存，被 {} 括起来的是系统自动统计得到的，其他是运营人工设置。正常情况是使用空格分隔
    top_images = db.Column(db.String(100), default='')      # 热门图片的 id 列表，英文空格分隔
    images_num = db.Column(db.SmallInteger, default=0)    # 该店铺拥有的晒单评论相关图片数量，是一个缓存值
    gate_images = db.Column(db.String(100), default='')     # 店铺门脸展示图片的 id 列表，英文空格分隔
    data_source = db.Column(db.Unicode(500), default=u'')    # 本 POI 数据采集的原始网址

    def __unicode__(self):
        return u'<Site [%d] %s>' % (self.id, self.name)


event.listen(
    Site.__table__,
    "after_create",
    DDL("ALTER TABLE %(table)s AUTO_INCREMENT = 3421;").execute_if(dialect=('postgresql', 'mysql'))
)


class Category(db.Model):       # POI 分类
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, default=False)   # 控制是否用户可见
    order = db.Column(db.Integer, default=0)    # 控制在前台的显示顺序，数字越大越靠前
    name = db.Column(db.Unicode(20), default=u'')    # 类别名称
    parent_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    parent = db.relationship('Category', remote_side=[id], backref=db.backref('children', lazy='dynamic'))

    def __unicode__(self):
        return u'<Category [%d] %s>' % (self.id, self.name)


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
    target = db.Column(db.Unicode(20), default=u'')  # 用户分享的目的地，比如微信或短信，中文文字描述
    action_time = db.Column(db.DateTime, default=datetime.datetime.now)       # 用户分享文章或店铺的时间点

    def __unicode__(self):
        return u'<ShareRecord [%d] %s: site %d, review %d>' % (self.id, self.user.name, self.site_id or -1, self.review_id or -1)


roles_users = db.Table('roles_users',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('role_id', db.Integer, db.ForeignKey('role.id'))
)


class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Unicode(80), unique=True, default=u'')

    def __unicode__(self):
        return u'<Role [%d] %s>' % (self.id, self.name)


event.listen(
    Role.__table__,
    "after_create",
    DDL("ALTER TABLE %(table)s AUTO_INCREMENT = 7;").execute_if(dialect=('postgresql', 'mysql'))
)


class Token(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    create_time = db.Column(db.DateTime, default=datetime.datetime.now)       # 首次创建时间，以服务器时间为准
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))     # 用户 id
    user = db.relationship('User', backref=db.backref('tokens', lazy='dynamic'), foreign_keys=[user_id])
    token = db.Column(db.String(50), default=uuid.uuid4)         # 用户登陆后的临时唯一标识
    device = db.Column(db.String(50))    # 设备 id


class User(db.Model):
    id = db.Column(db.Integer, autoincrement='ignore_fk', primary_key=True)
    valid = db.Column(db.Boolean, default=True)   # 控制是否当作已删除处理（False 表示删除）
    anonymous = db.Column(db.Boolean, default=False)  # 表示是否是系统自动生成的非注册用户
    create_time = db.Column(db.DateTime, default=datetime.datetime.now)       # 首次创建时间，以服务器时间为准
    update_time = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)       # 用户属性信息修改时间，以服务器时间为准
    name = db.Column(db.Unicode(100), unique=True)    # 可见用户昵称。注：由于设置了 unique ，所以未填本项的都保留为 null 。
    username = db.Column(db.String(80), unique=True, default='')    # 登陆用用户名，App 端会是设备 id（匿名用户）或手机号（已注册用户）
    mobile = db.Column(db.String(120), unique=True)     # 用户手机号。注：由于设置了 unique ，所以未填本项的都保留为 null 。
    password = db.Column(db.String(80), default='')         # Hash 处理之后的登陆密码
    icon_id = db.Column(db.Integer, db.ForeignKey('image.id', use_alter=True, name='fk_icon'))     # 用户头像的图片 id
    icon = db.relationship('Image', foreign_keys=[icon_id], post_update=True)
    gender = db.Column(db.Unicode(10), default=u'未知')  # 用户填写的性别参数：男、女、未知
    level = db.Column(db.SmallInteger, default=1)     # 用数字表示的用户等级
    exp = db.Column(db.Integer, default=0)      # 与用户等级对应的用户经验，需要根据每天的行为日志做更新
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
    badges = db.Column(db.Unicode(500), default=u'')  # 用户拥有的徽章名称列表
    roles = db.relationship('Role', secondary=roles_users,
                            backref=db.backref('users', lazy='dynamic'))
    # ToDo: 勋章内容的更新机制暂未实现！

    def is_admin(self):
        check = False
        for role in self.roles:
            if role.id == 7:
                check = True
        return check and self.valid

    def is_operator(self):
        check = False
        for role in self.roles:
            if role.id == 8:
                check = True
        return check and self.valid

    # Flask-Login integration
    def is_authenticated(self):
        return self.valid and not self.anonymous

    def is_active(self):
        return self.valid

    def is_anonymous(self):
        return not self.valid or self.anonymous

    def get_id(self):
        return self.id

    # Required for administrative interface
    def __unicode__(self):
        return u'<User [%d] %s>' % (self.id, self.name)


event.listen(
    User.__table__,
    "after_create",
    DDL("ALTER TABLE %(table)s AUTO_INCREMENT = 321;").execute_if(dialect=('postgresql', 'mysql'))
)

@event.listens_for(User, 'before_insert')
@event.listens_for(User, 'before_update')
def encrypt_password(mapper, connection, target):
    if target.password and not target.password.startswith('pbkdf2:sha1:'):
        target.password = generate_password_hash(target.password)

@event.listens_for(User, 'before_insert')
def generate_default_name_and_icon(mapper, connection, target):
    if not target.name and not target.icon_id:
        name_leading, icon_id = DEFAULT_USER_GROUPS[random.randint(0, 5)]
        month_addon = CHINESE_MONTHS[datetime.date.today().month]
        number_ending = (int(time.time() * 1000)) % 100000
        while True:
            name = name_leading + month_addon + unicode(number_ending)
            has_same_name = db.session.query(User).filter(User.name == name).first()
            if has_same_name:
                number_ending += 97
            else:
                break
        target.name = name
        target.icon_id = icon_id


class Image(db.Model):  # 全局图片存储
    id = db.Column(db.Integer, primary_key=True)        # ToDo：考虑改为 UUID 。
    valid = db.Column(db.Boolean, default=True)   # 控制是否当作已删除处理（False 表示删除）
    type = db.Column(db.SmallInteger, default=1)   # 图片分类：1 表示店铺 logo；2 表示店铺门脸图；3 表示用户头像；4 表示评论图片。
    path = db.Column(db.String(120), default='')    # 图片所在存储路径
    note = db.Column(db.Unicode(120), default=u'')   # 图片的备忘描述文字，[] 中的内容是系统自动生成的，通常用于保存图片原始文件名。
    create_time = db.Column(db.DateTime, default=datetime.datetime.now)       # 图片上传时间，以服务器时间为准
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # 图片上传人
    user = db.relationship('User', backref=db.backref('images', lazy='dynamic'), foreign_keys=[user_id])

    def __unicode__(self):
        return u'<Image [%d] %s>' % (self.id, 'None' if not self.path else self.path.split('/')[-1])


class Review(db.Model):        # 用户晒单评论
    id = db.Column(db.Integer, primary_key=True)        # ToDo: 考虑改为 UUID（已放弃，改为从特定数值开始）。
    valid = db.Column(db.Boolean, default=False)   # 控制是否当作已删除处理（False 表示删除）
    selected = db.Column(db.Boolean, default=False)     # 控制本文是否强制加入精选推荐
    published = db.Column(db.Boolean, default=False)       # 控制是否对外发布
    publish_time = db.Column(db.DateTime, default=None)       # 首次发布时间，以服务器时间为准
    update_time = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)       # 评论修改时间，以服务器时间为准
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # 晒单评论的作者
    user = db.relationship('User', backref=db.backref('reviews', lazy='dynamic'))
    at_list = db.Column(db.String(200), default='')         # 本评论将@的用户 id 列表，后端代码需要实现注意控制长度！多个 id 使用英文空格分隔。
    stars = db.Column(db.Float, default=0.0)         # POI 的评论星级，出于与统计结果，使用小数表示，实际只能是1～5
    content = db.Column(db.UnicodeText)         # 晒单评论的文本正文，只需分自然段，无需支持特殊格式。
    images = db.Column(db.String(200), default='')  # 晒单评论的附属图片的 id 列表，空格分隔。
    keywords = db.Column(db.Unicode(200), default=u'')       # 晒单评论关键词，空格分隔
    total = db.Column(db.Integer, default=0)       # 本次购物总价
    currency = db.Column(db.Unicode(10), default=u'')        # 购物总价所对应的币种，这里没有做强制类别限制，需要在接收前端数据前作检查、判断
    site_id = db.Column(db.Integer, db.ForeignKey('site.id'))   # 关联的 POI
    site = db.relationship('Site', backref=db.backref('reviews', lazy='dynamic'))
    like_num = db.Column(db.Integer, default=0)        # 喜欢本晒单的人数，这只是相当于一个缓存，实际数据根据“喜欢”的行为表计算得出
    comment_num = db.Column(db.Integer, default=0)      # 本晒单的评论总数，只是一个缓存值，实际数据根据“评论”的行为表计算得出

    def __unicode__(self):
        return u'<Review [%d] %s: %s>' % (self.id, self.user.name, self.update_time.strftime('%y-%m-%d'))


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
    review_id = db.Column(db.Integer, db.ForeignKey('review.id'))       # 子评论所关联的晒单评论
    review = db.relationship('Review', backref=db.backref('comments', lazy='dynamic'))
    article_id = db.Column(db.Integer, db.ForeignKey('article.id'))     # 子评论所关联的首页文章
    article = db.relationship('Article', backref=db.backref('comments', lazy='dynamic'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # 评论的作者
    user = db.relationship('User', backref=db.backref('comments', lazy='dynamic'))
    at_list = db.Column(db.String(200), default='')         # 本评论将@的用户 id 列表，通常子评论只能@一个人，也就是所回复的子评论的原作者
    content = db.Column(db.UnicodeText)        # 评论的文字正文，需要注意检查内容长度

    def __unicode__(self):
        return u'<Comment [%d] %s: %s>' % (self.id, self.user.name, self.update_time.strftime('%y-%m-%d'))


city_articles = db.Table('city_articles',
    db.Column('city_id', db.Integer, db.ForeignKey('city.id')),
    db.Column('article_id', db.Integer, db.ForeignKey('article.id')),
)


country_articles = db.Table('country_articles',
    db.Column('country_id', db.Integer, db.ForeignKey('country.id')),
    db.Column('article_id', db.Integer, db.ForeignKey('article.id')),
)


class Article(db.Model):        # 首页推荐文章
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, default=False)   # 控制是否当作已删除处理（False 表示删除）
    order = db.Column(db.Integer, default=0)    # 控制在前台的显示顺序，数字越大越靠前
    create_time = db.Column(db.DateTime, default=datetime.datetime.now)       # 首次创建时间，以服务器时间为准
    update_time = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)       # 评论修改时间，以服务器时间为准
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # 晒单评论的作者
    user = db.relationship('User', backref=db.backref('articles', lazy='dynamic'))
    cities = db.relationship('City', secondary=city_articles,
                                      backref=db.backref('articles', lazy='dynamic'))
    countries = db.relationship('Country', secondary=country_articles,
                                      backref=db.backref('articles', lazy='dynamic'))
    title = db.Column(db.Unicode(50), default=u'')   # 首页文章的标题
    content = db.Column(db.UnicodeText)         # 晒单评论的文本正文，需区分自然段、小标题、图片、店铺链接、分隔符等特殊格式！
    keywords = db.Column(db.Unicode(200), default=u'')       # 晒单评论关键词，空格分隔
    comment_num = db.Column(db.Integer, default=0)      # 本晒单的评论总数，只是一个缓存值，实际数据根据“评论”的行为表计算得出

    def __unicode__(self):
        return u'<Article [%d] %s: %s>' % (self.id, self.user.name, self.title)


event.listen(
    Article.__table__,
    "after_create",
    DDL("ALTER TABLE %(table)s AUTO_INCREMENT = 97;").execute_if(dialect=('postgresql', 'mysql'))
)


class Tips(db.Model):        # 首页 Tips 文档
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, default=False)   # 控制是否当作已删除处理（False 表示删除）
    default = db.Column(db.Boolean, default=False)      # 控制是否是该城市默认显示的 Tips
    create_time = db.Column(db.DateTime, default=datetime.datetime.now)       # 首次创建时间，以服务器时间为准
    update_time = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)       # 评论修改时间，以服务器时间为准
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # 晒单评论的作者
    user = db.relationship('User', backref=db.backref('tips', lazy='dynamic'))
    city_id = db.Column(db.Integer, db.ForeignKey('city.id'))   # Tips 所对应的城市
    city = db.relationship('City', backref=db.backref('tips', lazy='dynamic'))
    title = db.Column(db.Unicode(50), default=u'')   # Tips 的标题，用于列表选单，不用于正文显示
    content = db.Column(db.UnicodeText)         # 晒单评论的文本正文，需区分自然段、小标题、分隔符、排序列表等特殊格式！以及支持对其他 Tips 的引用（例如该国家通用的内容）！

    def __unicode__(self):
        return u'<Tips [%d] %s: %s>' % (self.id, self.city.name, self.update_time.strftime('%y-%m-%d'))


event.listen(
    Tips.__table__,
    "after_create",
    DDL("ALTER TABLE %(table)s AUTO_INCREMENT = 59;").execute_if(dialect=('postgresql', 'mysql'))
)


class UserReadMessage(db.Model):        # 辅助用关联关系表，未做 Admin 管理界面
    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # 相关用户
    user = db.relationship('User', backref=db.backref('read_records', lazy='dynamic'), foreign_keys=[user_id])
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'))     # 相关的私信消息
    message = db.relationship('Message', backref=db.backref('read_records', lazy='dynamic'), foreign_keys=[message_id])
    has_read = db.Column(db.Boolean, default=False)     # 该用户是否已经读过特定私信

    def __unicode__(self):
        return u'<UserReadMessage [%d] %s: msg %d, has_read %d>' % (self.id, self.user.name, self.message_id or -1, self.has_read)


class Message(db.Model):        # 用户私信， #ToDo: 当前的数据库结构设计可能存在性能问题。。
    id = db.Column(db.Integer, primary_key=True)
    valid = db.Column(db.Boolean, default=False)   # 控制是否当作已删除处理（False 表示删除）
    create_time = db.Column(db.DateTime, default=datetime.datetime.now)       # 首次创建时间，以服务器时间为准
    sender_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))      # 私信消息的作者
    sender_user = db.relationship('User', backref=db.backref('sent_messages', lazy='dynamic'))  # 反向是该用户发送的所有信息
    content = db.Column(db.UnicodeText)         # 私信消息的文本正文，应支持 App 内信息的链接
    group_key = db.Column(db.String(50), default='')        # 私信消息分组快捷键，将本消息相关 user_id 按从小到大排序，用“_”连接作为 Key
    users = db.relationship('User', secondary=UserReadMessage.__table__,
                                      backref=db.backref('messages', lazy='dynamic'))   # 反向为该用户的全部信息

    def __unicode__(self):
        return u'<Message [%d] %s: %s>' % (self.id, self.sender_user.name, self.create_time.strftime('%y-%m-%d'))


