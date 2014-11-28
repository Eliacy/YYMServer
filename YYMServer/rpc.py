# -*- coding: utf-8 -*-

import json
import time

from sqlalchemy import func, desc
from sqlalchemy.orm import aliased
from werkzeug.security import generate_password_hash, check_password_hash

from flask import jsonify, request, url_for
from flask.ext.restful import reqparse, Resource, fields, marshal_with, marshal, abort
from flask.ext.restful import output_json as restful_output_json
from flask.ext.hmacauth import hmac_auth

from qiniu.auth import digest

from YYMServer import app, db, cache, api, util, message, baseurl_share
from YYMServer.models import *

from flask.ext.restful.representations.json import output_json
output_json.func_globals['settings'] = {'ensure_ascii': False, 'encoding': 'utf8'}


@api.representation('application/json')
def output_json(data, code, headers=None):
    ''' 定制输出内容，固定输出 status 和 message 字段，以方便客户端解析。'''
    message = 'OK'
    if type(data) == dict:
        if data.has_key('message'):
            message = data.pop('message')
        if data.has_key('status'):
            code = data.pop('status')
    data = {'status': code, 'message': message, 'data':data}
    return restful_output_json(data, code, headers)


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


class CacheTime(Resource):
    '''服务器缓存时间查询。'''
    def get(self):
        return {'cache_time': app.config['CACHE_DEFAULT_TIMEOUT']}

api.add_resource(CacheTime, '/rpc/cache_time')


# 常用公共辅助：
id_parser = reqparse.RequestParser()
id_parser.add_argument('id', type=long)


class ImageUrl(fields.Raw):
    def format(self, path):
        return util.extend_image_path(path)


# 图片信息查询接口：
image_parser = reqparse.RequestParser()
image_parser.add_argument('id', type=long)       # ToDo: 这里的 type 参数指明的 类型，需要保证与 model 中的对应字段一致！model 中的 Integer 这里对应 long； model 中的 SmallInteger 这里对应 int。
image_parser.add_argument('offset', type=int)    # offset 偏移量。
image_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
image_parser.add_argument('site', type=long)      # 指定 POI id，获取所有相关图片
image_parser.add_argument('review', type=long)   # 指定晒单评论 id，获取所有相关图片

image_parser_detail = reqparse.RequestParser()         # 用于创建一个图片上传信息的参数集合
image_parser_detail.add_argument('type', type=int, default=4, required=True)      # 图片分类：1 表示店铺 logo；2 表示店铺门脸图；3 表示用户头像；4 表示评论图片。
image_parser_detail.add_argument('path', type=unicode, required=True)  # 图片保存地址的完整 url （通常应该是云存储地址）
image_parser_detail.add_argument('user', type=long, required=True)      # 图片上传人的账号 id 

image_fields_mini = {
    'id': fields.Integer,
    'url': ImageUrl(attribute='path'),
}

image_fields = {
    'type': fields.Integer,
    'create_time': util.DateTime,    # RFC822-formatted datetime string in UTC
    'user_id': fields.Integer,
    'mime': fields.String,
    'width': fields.Integer,
    'height': fields.Integer,
}
image_fields.update(image_fields_mini)


# ToDo: 图片上传的接口！
class ImageList(Resource):
    '''提供图片的增、查、删三组服务。'''
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    @cache.memoize()
    # 貌似不需要处理动态缓存更新，site 可以接受图片更新延迟，review 则通常不会单独从这个接口取图片。
    def _get(self, id=None, site=None, review=None):
        query = db.session.query(Image).filter(Image.valid == True)
        if id:
            query = query.filter(Image.id == id)
            return query.all()
        else:
            if review:
                related_review = db.session.query(Review).filter(Review.valid == True).filter(Review.published == True).filter(Review.id == review).first()
                if related_review:
                    return util.get_images(related_review.images or '')
            if site:
                return util.get_images(util.get_site_images(site))
        return []

    @hmac_auth('api')
    @marshal_with(image_fields)
    def get(self):
        args = image_parser.parse_args()
        id = args['id']
        result = self._get(id, args['site'], args['review'])
        offset = args['offset']
        if offset:
            result = result[offset:]
        limit = args['limit']
        if limit:
            result = result[:limit]
        return result

    @hmac_auth('api')
    def delete(self):
        # 不会真正删除信息，只是设置 valid = False ，以便未来查询。
        args = id_parser.parse_args()
        id = args['id']
        image = db.session.query(Image).filter(Image.id == id).filter(Image.valid == True).first()
        if image:
            image.valid = False
            db.session.commit()
            return '', 204
        abort(404, message='Target Image do not exists!')

    @hmac_auth('api')
    def post(self):
        ''' 保存新图片信息的接口。'''
        args = image_parser_detail.parse_args()
        image = Image(valid = True,
                      type = args['type'],      # 这里没有做 type 取值是否在标准集合范围内的判断
                      path = args['path'],
                      create_time = datetime.datetime.now(),
                      user_id = args['user'],
                     )
        db.session.add(image)
        db.session.commit()
        return {'id': image.id}, 201

api.add_resource(ImageList, '/rpc/images')


# 图片上传的回调接口：
image_call_parser= reqparse.RequestParser()         # 用于创建七牛云存储 callback 接口的参数集合
image_call_parser.add_argument('id', type=long)      # 图片在数据库中的 id ，如果是覆盖数据库中已存在的图片，则应提供这个参数指定图片的原始 id 。
image_call_parser.add_argument('type', type=int, default=4, required=True)      # 图片分类：1 表示店铺 logo；2 表示店铺门脸图；3 表示用户头像；4 表示评论图片。
image_call_parser.add_argument('user', type=long, required=True)      # 图片上传人的账号 id 
image_call_parser.add_argument('note', type=unicode, required=True)  # 图片备注信息
image_call_parser.add_argument('name', type=unicode, required=True)  # 图片原始文件名
image_call_parser.add_argument('size', type=long, required=True)  # 图片大小
image_call_parser.add_argument('mime', type=str, required=True)  # 图片 MIME TYPE
image_call_parser.add_argument('width', type=int, required=True)  # 图片宽
image_call_parser.add_argument('height', type=int, required=True)  # 图片高
image_call_parser.add_argument('hash', type=str, required=True)  # 图片 hash ，也即 etag 取值。

class ImageCall(Resource):
    '''配合七牛云存储的上传回调接口，将保存已上传到云存储的图片的信息到数据库。'''

    @marshal_with(image_fields)
    def post(self):
        # 检查七牛签名：
        sign = request.headers.get('Authorization', '').strip().split()[-1]
        path = request.script_root + request.path
        #TODO: check request length before calling get_data() to avoid memory exaustion issues
        #see http://werkzeug.pocoo.org/docs/0.9/wrappers/#werkzeug.wrappers.BaseRequest.get_data
        #and http://stackoverflow.com/questions/10999990/get-raw-post-body-in-python-flask-regardless-of-content-type-header
        #these parameters should be the default, but just in case things change...
        body = request.get_data(cache=True,as_text=False, parse_form_data=False)
        mac = digest.Mac()
        data = path.encode('utf-8') + '\n' + body
        token = mac.sign(data)
        if sign != token:
            abort(403, message='QiNiu Authorization failed!')
        # 更新回调发过来的图片信息
        args = image_call_parser.parse_args()
        id = args['id']
        is_new_image = True
        if id:
            image = db.session.query(Image).filter(Image.valid == True).filter(Image.id == id).first()
            if image:
                is_new_image = False
        if is_new_image:
            image = Image(valid = True)
        image.type = args['type']
        image.path = 'qiniu:%s' % args['hash']
        if args['note']:
            image.note = args['note']
        if args['user']:
            image.user_id = args['user']
        if args['name']:
            image.name = args['name']
        image.size = args['size']
        image.mime = args['mime']
        image.width = args['width']
        image.height = args['height']
        if is_new_image:
            db.session.add(image)
        db.session.commit()
        return image

api.add_resource(ImageCall, '/rpc/images/call')


# 七牛云存储签名验证生成接口：
uptoken_parser = reqparse.RequestParser()
uptoken_parser.add_argument('params', type=unicode, required=True)         # callbackBody 数据


class UpTokenList(Resource):
    '''根据输入参数，计算七牛云存储图片上传 token 的接口。'''
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    @hmac_auth('public')
    def post(self):
        ''' 生成七牛文件上传 token 。'''
        args = uptoken_parser.parse_args()
        params = args['params']
        callback_dic = json.loads(params)
        return {'token': util.gen_upload_token(callback_dic)}, 201

api.add_resource(UpTokenList, '/rpc/uptokens')


# 用户信息查询接口：
user_parser = reqparse.RequestParser()
user_parser.add_argument('id', type=long)
user_parser.add_argument('offset', type=int)    # offset 偏移量。
user_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
user_parser.add_argument('follow', type=long)      # 关注指定 id 所对应用户的账号列表
user_parser.add_argument('fan', type=long)         # 有指定 id 所对应用户作为粉丝的账号列表
user_parser.add_argument('token', type=str)     # 用户 token，用于获取是否关注的关系

user_parser_detail = reqparse.RequestParser()         # 用于创建和更新一个 User 的信息的参数集合
user_parser_detail.add_argument('id', type=long)
user_parser_detail.add_argument('icon', type=long)        # 用户头像对应图片的 id
user_parser_detail.add_argument('name', type=unicode)    # 用户昵称，不能与已有的昵称重复，否则报错。
user_parser_detail.add_argument('mobile', type=str)  # 预留手机号接口，但 App 前端在初期版本不应该允许用户修改！不能与其他用户的手机号重复，否则报错。
user_parser_detail.add_argument('password', type=str)  # 账号密码的明文，至少6个字符。
user_parser_detail.add_argument('gender', type=unicode)    # 用户性别：文字直接表示的“男、女、未知”
user_parser_detail.add_argument('token', type=str)  # 旧 token，用于迁移登录前发生的匿名行为。
user_parser_detail.add_argument('device', type=str)      # 设备 id 。

user_fields_mini = {
    'id': fields.Integer,
    'icon': fields.Nested(image_fields_mini, attribute='icon_image'),   # 用户头像，没有时会变成 id 为 0 的图片
    'name': fields.String,      # 用户昵称
    'level': fields.Integer,    # 用数字表示的用户等级
}
user_fields = {
    'anonymous': fields.Boolean,
    'create_time': util.DateTime,    # 首次创建时间，RFC822-formatted datetime string in UTC
    'update_time': util.DateTime,    # 用户属性修改时间，RFC822-formatted datetime string in UTC
    'username': fields.String,  # 登陆用用户名，App 端会是设备 id（匿名用户）或手机号（已注册用户）
    'mobile': fields.String,    # 用户手机号
    'gender': fields.String,    # 性别：文字直接表示的“男、女、未知”
    'exp': fields.Integer,      # 与用户等级对应的用户经验，需要根据每天的行为日志做更新
    'follow_num': fields.Integer,      # 该用户已关注的账号的数量，是一个缓存值
    'fans_num': fields.Integer,      # 该用户拥有的粉丝数量，是一个缓存值
    'like_num': fields.Integer,      # 该用户喜欢的晒单评论数量，是一个缓存值
    'share_num': fields.Integer,      # 该用户的分享行为数量，是一个缓存值
    'review_num': fields.Integer,      # 该用户发表的晒单评论数量，是一个缓存值
    'favorite_num': fields.Integer,      # 该用户收藏的店铺的数量，是一个缓存值
    'badges': fields.String,    # 用户拥有的徽章名称列表
    'followed': fields.Boolean,         # 当前 token 参数表示的用户是否关注了此用户（仅查询时指定了 id 参数时提供，否则都是 null）
    'em_username': fields.String,   # 用户对应的环信账号用户名
    'em_password': fields.String,   # 用户对应的环信账号密码
}
user_fields.update(user_fields_mini)

def _format_user(user):
    ''' 辅助函数：用于格式化 User 实例，用于接口输出。'''
    # 也会被 /rpc/tokens 接口使用
    user.icon_image = user.icon
    return user

def _prepare_msg_account(user):
    ''' 辅助函数：检查 user 拥有的环信账号，如果没有则创建一个。'''
    if not user.em_username or not user.em_password:
        success, result, username, password = message.prepare_msg_account()
        if not success:
            abort(403, message='EaseMob account registration failed!')
        else:
            user.em_username = username
            user.em_password = password
    return user


class UserList(Resource):
    '''对用户账号信息进行查询、注册、修改的服务接口。不提供删除接口。'''
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    def _delete_cache(self, model):
        ''' 辅助函数：清除指定 user 的缓存数据。'''
        # ToDo: 其实这里是有问题的。Review 和 Comment 会内嵌显示 user 的概要信息，user 属性改了之后这里没有要求清空 Review 和 Comment 的缓存。
        cache.delete_memoized(self._get, self, model.id, None, None)

    def _delete_follow_cache(self, follow, fan):
        ''' 辅助函数：清除指定 follow 和 fan 的缓存数据。'''
        follow_id = 0 if not follow else follow.id
        fan_id = 0 if not fan else fan.id
        if follow_id:
            cache.delete_memoized(self._get, self, None, follow_id, None)
        if fan_id:
            cache.delete_memoized(self._get, self, None, None, fan_id)

    def _check_password(self, password):
        ''' 辅助函数：用于检查用户提交的新密码的合规性。'''
        if len(password) < 6:
            abort(403, message='The password length should be at least 6 characters!')
    
    @cache.memoize()
    def _get(self, id=None, follow=None, fan=None):
        # 当指定用户 id 进行查询时，即使该用户 valid 为 False，也仍然给出详细信息。
        result = []
        if id:
            query = db.session.query(User).filter(User.id == id)
            result = query.all()
        elif follow:
            Main_User = aliased(User)
            query = db.session.query(User).filter(User.valid == True).join(fans, User.id == fans.columns.fan_id).join(Main_User, fans.columns.user_id == Main_User.id).filter(Main_User.id == follow).order_by(fans.columns.action_time.desc())
            result = query.all()
        elif fan:
            Main_User = aliased(User)
            query = db.session.query(User).filter(User.valid == True).join(fans, User.id == fans.columns.user_id).join(Main_User, fans.columns.fan_id == Main_User.id).filter(Main_User.id == fan).order_by(fans.columns.action_time.desc())
            result = query.all()
        [_format_user(user) for user in result]
        return result

    @hmac_auth('api')
    @marshal_with(user_fields)
    def get(self):
        args = user_parser.parse_args()
        id = args['id']
        result = self._get(id, args['follow'], args['fan'])
        token = args['token']
        if id and token:        # ToDo：这里查询关注关系使用的是数据库查询，存在性能风险！
            for user in result:
                Main_User = aliased(User)
                query = db.session.query(User.id).filter(User.valid == True).join(fans, User.id == fans.columns.user_id).join(Main_User, fans.columns.fan_id == Main_User.id).join(Token, Main_User.id == Token.user_id).filter(Token.token == token)
                if query.first() == None:
                    user.followed = False
                else:
                    user.followed = True
        offset = args['offset']
        if offset:
            result = result[offset:]
        limit = args['limit']
        if limit:
            result = result[:limit]
        return result

    @hmac_auth('api')
    def post(self):
        ''' 用户注册或创建新的匿名用户的接口。'''
        args = user_parser_detail.parse_args()
        mobile = args['mobile']
        password = args['password']
        device = args['device']
        token = args['token']
        # 以匿名用户作为默认选择：
        anonymous = True
        username = unicode(device)
        # 优先返回同一个设备上曾经注册过的匿名用户
        user = db.session.query(User).filter(User.valid == True).filter(User.anonymous == True).join(User.tokens).filter(Token.device == device).order_by(Token.id.desc()).first()
        if mobile and password:     # 用户正在尝试注册非匿名用户
            has_same_mobile = db.session.query(User).filter(User.mobile == mobile).first()
            if has_same_mobile:
                abort(409, message='This mobile number has been used by another user!')
            self._check_password(password)
            anonymous = False
            username = mobile
        if user is None:
            has_same_username = db.session.query(User).filter(User.username == username).first()
            if has_same_username:
                abort(409, message='The username has been used by another user! Please check mobile number & device id.')
            user = User(valid = True,
                        anonymous = anonymous,
                        create_time = datetime.datetime.now(),
                        update_time = datetime.datetime.now(),
                        icon_id = args['icon'],
                        name = args['name'],        # name 为空时，Model 会自动生成默认的 name 和 icon 
                        username = username,
                        mobile = mobile,
                        password = password,        # 明文 password 会被 Model 自动加密保存
                        gender = args['gender'],
                       )
            _prepare_msg_account(user)
            db.session.add(user)
            db.session.commit()
        else:   # 将已有匿名用户账号重置为新注册的信息（匿名用户改为非匿名用户）
            user.valid = True
            user.anonymous = anonymous
            user.update_time = datetime.datetime.now()
            user.icon_id = args['icon']
            user.name = args['name']    # name 为空时，Model 会自动生成默认的 name 和 icon
            user.username = username
            user.mobile = mobile
            user.password = password
            user.gender = args['gender']
            _prepare_msg_account(user)
            db.session.commit()
        self._delete_cache(user)
        _format_user(user)
        # 注册后要调用登陆逻辑，返回用户 token 等。
        token = _generate_token(user, device, args['token'], )
        return marshal({'user': user, 'token': token}, token_fields), 201

    @hmac_auth('api')
    def put(self):
        ''' 修改用户详细属性信息的接口。'''
        args = user_parser_detail.parse_args()
        id = args['id']
        user = db.session.query(User).filter(User.id == id).filter(User.valid == True).first()
        if user:
            user.update_time = datetime.datetime.now()
            icon_id = args['icon']
            if icon_id:
                user.icon_id = icon_id
            name = args['name']
            if name:
                has_same_name = db.session.query(User).filter(User.name == name).first()
                if has_same_name and has_same_name.id != id:
                    abort(409, message='The name has been used by another user!')
                user.name = name
            password = args['password']
            if password:
                self._check_password(password)
                user.password = password        # 明文 password 会被 Model 自动加密保存
            gender = args['gender']
            if gender:
                user.gender = gender
            db.session.commit()
            self._delete_cache(user)
            _format_user(user)
            return marshal(user, user_fields), 201
        abort(404, message='Target User do not exists!')

api.add_resource(UserList, '/rpc/users')


# 用户登陆接口：
login_parser = reqparse.RequestParser()
login_parser.add_argument('username', type=str, required=True)         # 用户名，只支持 ASCii 字符。
login_parser.add_argument('password', type=str, required=True)    # 密码，只支持 ASCii 字符。
login_parser.add_argument('token', type=str)     # 旧 token，用于迁移登录前发生的匿名行为。
login_parser.add_argument('device', type=str, required=True)      # 设备 id 。

token_fields = {
    'user': fields.Nested(user_fields),     # 登陆成功时，返回该用户的全部详情
    'token': fields.String,      # 用户本次登陆对应的 token
}

def _generate_token(new_user, device, old_token=None):
    '''辅助函数：根据新登陆的 user 实例创建对应 token。如果提供了旧 token ，相应做旧 token 的历史行为记录迁移。'''
    if old_token:
        old_user = db.session.query(User).join(User.tokens).filter(Token.token == old_token).first()
        if old_user:
            pass        # ToDo: 生成一个后台任务，合并旧 token 的行为数据到当前登陆的新账号！
    # 永远生成新 token，而不复用之前产生的 token。
    token = Token(user_id = new_user.id,
                  device = device,
                  )
    db.session.add(token)
    db.session.commit()
    return token.token


class TokenList(Resource):
    '''用户登陆，并返回账号 token 的接口。'''
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    @hmac_auth('public')
    @marshal_with(token_fields)
    def post(self):
        ''' 用户登陆接口。'''
        # ToDo: 用户登录时，应当把登录前匿名用户的历史行为尽可能地迁移过来！
        args = login_parser.parse_args()
        user = db.session.query(User).filter(User.valid == True).filter(User.anonymous == False).filter(User.username == args['username']).first()
        if not user or not check_password_hash(user.password, args['password']):
            abort(403, message='Login Failed!')
        old_token = args['token']
        token = _generate_token(user, args['device'], old_token)
        _format_user(user)
        return {'user': user, 'token': token}, 201

api.add_resource(TokenList, '/rpc/tokens')


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
area_fields['children'] = fields.List(fields.Nested(area_fields), attribute='valid_areas')


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

    def _get_children_areas(self, parent):
        ''' 辅助函数：按层级从父节点开始输出各级商区。'''
        children = []
        if not isinstance(parent, Area):
            query = parent.areas.filter(Area.valid == True).order_by(Area.order.desc()).filter(Area.parent_id == None)
        else:
            query = parent.children.filter(Area.valid == True).order_by(Area.order.desc())
        children = query.all()
        for child in children:
            self._get_children_areas(child)
        parent.valid_areas = children

    @cache.memoize()
    def _get(self, id=None):
        query = db.session.query(City).filter(City.valid == True).order_by(City.order.desc())
        if id:
            query = query.filter(City.id == id)
        result = []
        for city in query:
            self._get_children_areas(city)
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
site_parser.add_argument('id', type=long)
site_parser.add_argument('brief', type=int, default=1)     # 大于 0 表示只输出概要信息即可（默认只概要）。
site_parser.add_argument('offset', type=int)    # offset 偏移量。
site_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
site_parser.add_argument('keywords', type=unicode)  # 搜索关键词，空格或英文加号分隔，默认的关系是“且”。搜索时大小写不敏感。
site_parser.add_argument('area', type=long)      # 商圈 id。
site_parser.add_argument('city', type=long)      # 城市 id。
site_parser.add_argument('range', type=int)     # 范围公里数。如果是 -1，则表示“全城”。如果商圈、范围都是空，则表示默认的“智能范围”。
site_parser.add_argument('category', type=long)  # 分类 id。为空则表示“全部分类”。
site_parser.add_argument('order', type=int)     # 0 表示默认的“智能排序”，1 表示“距离最近”（约近约靠前），2 表示“人气最高”（点击量由高到低），3 表示“评价最好”（评分由高到低）。
site_parser.add_argument('longitude', type=float)       # 用户当前位置的经度
site_parser.add_argument('latitude', type=float)        # 用户当前位置的维度
site_parser.add_argument('token', type=str)     # 用户 token，用于获取是否收藏的关系

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
    'payment': fields.List(fields.String, attribute='formated_payment_types'),
    'menu': fields.String,      # 空字符串表示没有
    'ticket': fields.String(attribute='formated_ticket'),    # 空字符串表示没有
    'tour': fields.String,    # 空字符串表示没有
    'booking': fields.String,   # 空字符串表示没有
    'business_hours': fields.String(attribute='formated_business_hours'),    # 空字符串表示没有
    'phone': fields.String,     # 空字符串表示没有
    'transport': fields.String,         # 空字符串表示没有
    'description': fields.String,       # 空字符串表示没有
    'images_num': fields.Integer,
    'favorited': fields.Boolean,         # 当前 token 参数表示的用户是否收藏了此 POI
}
site_fields.update(site_fields_brief)

@cache.memoize()
def _get_category_subtree_ids(category_id):
    ''' 辅助函数：对指定 category_id ，获取其自身及其所有层级子节点的 id。'''
    return util.get_self_and_children(Category, category_id)

@cache.memoize()
def _get_area_subtree_ids(area_id):
    ''' 辅助函数：对指定 area_id ，获取其自身及其所有层级子节点的 id。'''
    return util.get_self_and_children(Area, area_id)

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
            area_ids = _get_area_subtree_ids(area)
            query = query.filter(Site.area_id.in_(area_ids))
        if city:
            query = query.join(Site.area).filter(Area.city_id == city)
            # ToDo: 除了直接使用 city id 判断外，还应该把城市中心点距离一定范围内（即使是属于其他城市的）的 POI 纳入搜索结果！
        if category:
            category_ids = _get_category_subtree_ids(category)
            query = query.join(Site.categories).filter(Category.id.in_(category_ids))
        if keywords:
            # 搜索关键词目前支持在 POI 名称、地址的中文、原文中进行模糊搜索。
            # ToDo: 搜索关键词还应考虑支持 description 和 keywords 两项！
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
            result.append(util.format_site(site, brief))
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
        # 提取 favorite 关系：
        if not brief:
            token = args['token']
            if token:        # ToDo：这里查询收藏关系使用的是数据库查询，存在性能风险！
                query = db.session.query(Site.id).filter(Site.valid == True).join(Site.fans).join(Token, User.id == Token.user_id).filter(Token.token == token).filter(Site.id.in_([site.id for site in result]))
                favorite_dic = {}
                for site_id in query:
                    favorite_dic[site_id[0]] = True
                for site in result:
                    site.favorited = favorite_dic.get(site.id, False)
        # 输出数据：
        if brief:
            return marshal(result, site_fields_brief)
        else:
            return marshal(result, site_fields)

api.add_resource(SiteList, '/rpc/sites')


# 首页文章接口：
article_parser = reqparse.RequestParser()
article_parser.add_argument('id', type=long)
article_parser.add_argument('brief', type=int, default=1)     # 大于 0 表示只输出概要信息即可（默认只概要）。
article_parser.add_argument('offset', type=int)    # offset 偏移量。
article_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
article_parser.add_argument('city', type=long)      # 城市 id。

article_content_fields_entry = {
    'class': fields.String,
    'type': fields.Integer,
    'content': fields.String,
}

article_content_fields_image = article_content_fields_entry.copy()
article_content_fields_image['content'] = fields.Nested(image_fields_mini)

article_content_fields_site = article_content_fields_entry.copy()
article_content_fields_site['content'] = fields.Nested(site_fields_brief)


class ContentEntry(fields.Raw):
    ''' 输出富媒体每行内容的 fields 定制封装。'''
    def output(self, key, data):
        type = data['class']
        data['type'] = {'text': 1,
                        'title': 2,
                        'image': 3,
                        'site': 4,
                        'hline': 5,
                        }.get(type, 0)
        if type == 'image':
            return marshal(data, article_content_fields_image)
        elif type == 'site':
            return marshal(data, article_content_fields_site)
        else:
            return marshal(data, article_content_fields_entry)
        return ''


article_fields_brief = {
    'id': fields.Integer,
    'create_time': util.DateTime,    # RFC822-formatted datetime string in UTC
    'title': fields.String,         # 首页文章的标题
    'caption': fields.Nested(image_fields_mini, attribute='caption_image'),     # 首页文章的标题衬图（也即首图）
    'keywords': fields.List(fields.String, attribute='formated_keywords'),      # 概要状态通常只使用第一个关键词
}
article_fields = {
    'update_time': util.DateTime,    # RFC822-formatted datetime string in UTC
    'content': fields.List(ContentEntry, attribute='formated_content'),         # 首页文章的文本正文，需区分自然段、小标题、图片、店铺链接、分隔符等特殊格式！
    # ToDo: 这里需要和客户端统一一下图文混排的方案！
    'comment_num': fields.Integer,
}
article_fields.update(article_fields_brief)

def _format_article(article):
    article.caption_image = article.caption
    article.formated_keywords = [] if not article.keywords else article.keywords.strip().split()
    article.formated_content = util.parse_textstyle(util.replace_textlib(article.content))
    return article


class ArticleList(Resource):
    '''按城市获取相关首页推荐文章的接口。'''

    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    @cache.memoize()
    def _get(self, brief=None, id=None, city=None):
        # ToDo: Article 表中各计数缓存值的数据没有做动态更新，例如子评论数！
        query = db.session.query(Article).filter(Article.valid == True)
        if id:
            query = query.filter(Article.id == id)
        if city:
            city_object = db.session.query(City).filter(City.valid == True).filter(City.id == city).first()
            country = -1 if not city_object else city_object.country_id
            query_city = query.join(Article.cities).filter(City.id == city)
            query_country = query.join(Article.countries).filter(Country.id == country)
            query = query_city.union(query_country)
        query = query.order_by(Article.order.desc()).order_by(Article.create_time.desc())
        result = []
        for article in query:
            _format_article(article)
            result.append(article)
        return result

    @hmac_auth('api')
    def get(self):
        args = article_parser.parse_args()
        brief = args['brief']
        result = self._get(brief, args['id'], args['city'])
        offset = args['offset']
        if offset:
            result = result[offset:]
        limit = args['limit']
        if limit:
            result = result[:limit]
        if brief:
            return marshal(result, article_fields_brief)
        else:
            return marshal(result, article_fields)

api.add_resource(ArticleList, '/rpc/articles')


# 小贴士接口：
tips_parser = reqparse.RequestParser()
tips_parser.add_argument('id', type=long)
tips_parser.add_argument('brief', type=int, default=1)     # 大于 0 表示只输出概要信息即可（默认只概要）。
tips_parser.add_argument('city', type=long)      # 城市 id。

tips_fields_brief = {
    'id': fields.Integer,
    'default': fields.Boolean,  # 是否是当前城市的默认贴士
    'create_time': util.DateTime,    # RFC822-formatted datetime string in UTC
    'title': fields.String,         # Tips 的标题，用于列表选单，不用于正文显示
}
tips_fields = {
    'update_time': util.DateTime,    # RFC822-formatted datetime string in UTC
    'content': fields.List(ContentEntry, attribute='formated_content'),         # 小贴士的文本正文，需区分自然段、小标题、分隔符、排序列表等特殊格式！以及支持对其他 Tips 的引用（例如该国家通用的内容）
    # ToDo: 这里需要和客户端统一一下图文混排的方案！
}
tips_fields.update(tips_fields_brief)


class TipsList(Resource):
    '''按城市获取相关小贴士文档的接口。'''

    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    @cache.memoize()
    def _get(self, brief=None, id=None, city=None):
        query = db.session.query(Tips).filter(Tips.valid == True)
        if id:
            query = query.filter(Tips.id == id)
        if city:
            query= query.filter(Tips.city_id == city)
        query = query.order_by(Tips.default.desc())
        result = query.all()
        for tips in query:
            tips.formated_content = util.parse_textstyle(util.replace_textlib(tips.content))
        return result

    @hmac_auth('api')
    def get(self):
        args = tips_parser.parse_args()
        brief = args['brief']
        result = self._get(brief, args['id'], args['city'])
        if brief:
            return marshal(result, tips_fields_brief)
        else:
            return marshal(result, tips_fields)

api.add_resource(TipsList, '/rpc/tips')


# 晒单评论接口：
review_parser = reqparse.RequestParser()
review_parser.add_argument('id', type=long)
review_parser.add_argument('brief', type=int, default=1)     # 大于 0 表示只输出概要信息即可（默认只概要）。
review_parser.add_argument('selected', type=int)     # 大于 0 表示只输出置顶信息即可（例如 POI 详情页面中的晒单评论），不够 limit 的要求时，会用非置顶信息补足。
review_parser.add_argument('published', type=int, default=1)     # 大于 0 表示只输出已发表的（默认只已发表的），否则也可输出草稿。
review_parser.add_argument('offset', type=int)    # offset 偏移量。
review_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
review_parser.add_argument('user', type=long)
review_parser.add_argument('site', type=long)    # 相关联的 POI id
review_parser.add_argument('city', type=long)    # 相关联的城市 id
review_parser.add_argument('token', type=str)     # 用户 token，用于获取是否喜欢的关系

review_parser_detail = reqparse.RequestParser()         # 用于创建和更新一个 Review 的信息的参数集合
review_parser_detail.add_argument('id', type=long)
review_parser_detail.add_argument('published', type=bool, required=True)
review_parser_detail.add_argument('user', type=long, required=True)
review_parser_detail.add_argument('at_list', type=str, required=True)  # 最多允许@ 20 个用户，更多的可能会被丢掉。
review_parser_detail.add_argument('stars', type=float, required=True)
review_parser_detail.add_argument('content', type=unicode, required=True)
review_parser_detail.add_argument('images', type=str, required=True)   # 最多允许绑定 10 张图片，更多的可能会被丢掉。
review_parser_detail.add_argument('keywords', type=unicode, required=True)     # 最多允许键入 15 个关键词，更多的可能会被丢掉。
review_parser_detail.add_argument('total', type=float, required=True)
review_parser_detail.add_argument('currency', type=unicode, required=True)
review_parser_detail.add_argument('site', type=long, required=True)

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
    'total': fields.Float,
    'currency': fields.String,
    'site': fields.Nested(site_fields_mini, attribute='valid_site'),
    'liked': fields.Boolean,         # 当前 token 参数表示的用户是否喜欢了此晒单评论
}
review_fields = {
    'at_list': fields.List(fields.Nested(user_fields_mini), attribute='valid_at_users'),
    'keywords': fields.List(fields.String, attribute='formated_keywords'),
}
review_fields.update(review_fields_brief)
review_fields['content'] = fields.String        # 非 brief 模式下，提供完整的文字内容

def _format_review(review, brief=None):
    ''' 辅助函数：用于格式化 Review 实例，用于接口输出。'''
    review.valid_user = review.user
    review.valid_user.icon_image = review.user.icon
    review.valid_site = review.site
    if review.site:
        review.valid_site.city_name = '' if not review.site.area else review.site.area.city.name
    review.images_num = 0 if not review.images else len(review.images.split())
    review.currency = review.currency or u'人民币'
    review.content = (review.content or u'').strip()
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
    return review

def _format_review_like(reviews, token):
    ''' 辅助函数：用于在 Review 实例中，插入当前 token 对应用户是否喜欢它的信息。'''
    if token:        # ToDo：这里查询喜欢关系使用的是数据库查询，存在性能风险！
        query = db.session.query(Review.id).filter(Review.valid == True).join(Review.fans).join(Token, User.id == Token.user_id).filter(Token.token == token).filter(Review.id.in_([review.id for review in reviews]))
        like_dic = {}
        for review_id in query:
            like_dic[review_id[0]] = True
        for review in reviews:
            review.liked = like_dic.get(review.id, False)
    return review


class ReviewList(Resource):
    '''获取某 POI 的晒单评论列表，以及对单独一条晒单评论详情进行查、增、删、改的服务。'''
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    def _delete_cache(self, model, site, user):
        ''' 辅助函数：尝试覆盖组合参数的主要可能性，清空对应缓存。'''
        # ToDo: 我有点儿怀疑这个搞法的效率，太多次 cache 访问了。感觉至少应该用 delete_many 处理。
        params = [(brief, selected, published) for brief in (0, 1) for selected in (None, 0, 1) for published in (0, 1)]
        id = 0 if not model else model.id
        site_id = 0 if not site else site.id
        city_id = 0 if not site else model.site.area.city.id
        user_id = 0 if not user else user.id
        for brief, selected, published in params:
            if id:
                cache.delete_memoized(self._get, self, brief, selected, published, id, None, None, None)
            if site_id:
                cache.delete_memoized(self._get, self, brief, selected, published, None, site_id, None, None)
            if city_id:
                cache.delete_memoized(self._get, self, brief, selected, published, None, None, city_id, None)
            if user_id:
                cache.delete_memoized(self._get, self, brief, selected, published, None, None, None, user_id)

    def _count_reviews(self, model):
        ''' 辅助函数，对晒单评论涉及的用户账号和 POI ，重新计算其星级和评论数。'''
        user = model.user
        site = model.site
        util.count_reviews([user] if user else [], [site] if site else [])
        if site:
            util.count_images(site)
        # 清除 Review 详情缓存：
        self._delete_cache(model, site, user)

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
            # 在“动态”栏目显示晒单评论的时候，不显示无图片评论：
            query = query.filter(Review.images != '')
        result = []
        if selected == None:
            # ToDo: 后台需要有个定时任务，将被关注多的 Review 设置成 selected 。
            pass
        else:   # 要求只返回 selected 或者只返回一定没被 selected 的内容时：
            query = query.filter(Review.selected == selected)   # selected 取值为合法 boolean 这一点，由 get(self) 函数调用 _get 前负责保证！
        if published:
            query = query.filter(Review.published == True)
        for review in query:
            _format_review(review, brief)
            result.append(review)
        return result

    @hmac_auth('api')
    def get(self):
        args = review_parser.parse_args()
        brief = args['brief']
        selected = args['selected']
        limit = args['limit']
        if selected:
            # 如果 selected 数量不够，就得用没被 selected 的内容来补。
            result = self._get(brief, True, args['published'], args['id'], args['site'], args['city'], args['user'])
            if limit and len(result) < limit:
                result += self._get(brief, False, args['published'], args['id'], args['site'], args['city'], args['user'])
        else:
            result = self._get(brief, None, args['published'], args['id'], args['site'], args['city'], args['user'])
        offset = args['offset']
        if offset:
            result = result[offset:]
        if limit:
            result = result[:limit]
        # 提取 like 关系：
        _format_review_like(result, args['token'])
        # 输出结果：
        if brief:
            return marshal(result, review_fields_brief)
        else:
            return marshal(result, review_fields)

    @hmac_auth('api')
    def delete(self):
        # 不会真正删除信息，只是设置 valid = False ，以便未来查询。
        args = id_parser.parse_args()
        id = args['id']
        review = db.session.query(Review).filter(Review.id == id).filter(Review.valid == True).first()
        if review:
            review.valid = False
            db.session.commit()
            self._count_reviews(review)
            return '', 204
        abort(404, message='Target Review do not exists!')

    @hmac_auth('api')
    def post(self):
        ''' 创建新晒单评论的接口。'''
        args = review_parser_detail.parse_args()
        at_list = util.truncate_list(args['at_list'], 200, 20)
        images = util.truncate_list(args['images'], 200, 10)
        keywords = util.truncate_list(args['keywords'], 200, 15)
        keywords = keywords if not keywords or len(keywords) < 200 else keywords[:200]
        review = Review(valid = True,
                        published = args['published'],
                        update_time = datetime.datetime.now(),
                        user_id = args['user'],
                        at_list = at_list,
                        stars = args['stars'],
                        content = args['content'],
                        images = images,
                        keywords = keywords,
                        total = args['total'],
                        currency = args['currency'],    # 这里没有做币种文字是否在有效范围内的判断
                        site_id = args['site'],
                       )
        if args['published']:
            review.publish_time = datetime.datetime.now()
        db.session.add(review)
        db.session.commit()
        self._count_reviews(review)
        return {'id': review.id}, 201

    @hmac_auth('api')
    def put(self):
        ''' 修改晒单评论内容的接口。'''
        args = review_parser_detail.parse_args()
        id = args['id']
        review = db.session.query(Review).filter(Review.id == id).filter(Review.valid == True).first()
        if review:
            at_list = util.truncate_list(args['at_list'], 200, 20)
            images = util.truncate_list(args['images'], 200, 10)
            keywords = util.truncate_list(args['keywords'], 200, 15)
            keywords = keywords if not keywords or len(keywords) < 200 else keywords[:200]
            review.published = args['published']
            review.update_time = datetime.datetime.now()
            review.user_id = args['user']
            review.at_list = at_list
            review.stars = args['stars']
            review.content = args['content']
            review.images = images
            review.keywords = keywords
            review.total = args['total']
            review.currency = args['currency']    # 这里没有做币种文字是否在有效范围内的判断
            review.site_id = args['site']
            if args['published'] and not review.publish_time:   # 只有首次发布才记录 publish_time 
                review.publish_time = datetime.datetime.now()
            db.session.commit()
            _format_review(review, brief=0)
            self._count_reviews(review)
            return marshal(review, review_fields), 201
        abort(404, message='Target Review do not exists!')


api.add_resource(ReviewList, '/rpc/reviews')


# 二级子评论接口：
comment_parser = reqparse.RequestParser()
comment_parser.add_argument('id', type=long)
comment_parser.add_argument('offset', type=int)    # offset 偏移量。
comment_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
comment_parser.add_argument('article', type=long)      # 指定推荐文章的 id，获取所有相关子评论
comment_parser.add_argument('review', type=long)         # 指定晒单评论 id，获取所有相关子评论

comment_parser_detail = reqparse.RequestParser()         # 用于创建和更新一个 Comment 的信息的参数集合
comment_parser_detail.add_argument('id', type=long)
comment_parser_detail.add_argument('review', type=long, required=True)
comment_parser_detail.add_argument('article', type=long, required=True)
comment_parser_detail.add_argument('user', type=long, required=True)
comment_parser_detail.add_argument('at_list', type=str)  # 最多允许@ 20 个用户，更多的可能会被丢掉。
comment_parser_detail.add_argument('content', type=unicode, required=True)

comment_fields = {
    'id': fields.Integer,
    'publish_time': util.DateTime,    # RFC822-formatted datetime string in UTC
    'update_time': util.DateTime,    # RFC822-formatted datetime string in UTC
    'review_id': fields.Integer,        # 绑定的晒单评论 id
    'article_id': fields.Integer,        # 绑定的首页文章 id
    'user': fields.Nested(user_fields_mini, attribute='valid_user'),
    'at_list': fields.List(fields.Nested(user_fields_mini), attribute='valid_at_users'),        # 子评论通常只允许 @ 一个人，但为了界面一致，仍然用列表输出。
    'content': fields.String,   
}


class CommentList(Resource):
    '''获取某晒单评论的子评论列表，或者进行增、删、改的服务。'''
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    def _delete_cache(self, model, article, review):
        ''' 辅助函数：尝试覆盖组合参数的主要可能性，清空对应缓存。'''
        id = 0 if not model else model.id
        article_id = 0 if not article else article.id
        review_id = 0 if not review else review.id
        if id:
            cache.delete_memoized(self._get, self, id, None, None)
        if article_id:
            cache.delete_memoized(self._get, self, None, article_id, None)
        if review_id:
            cache.delete_memoized(self._get, self, None, None, review_id)
    
    def _count_comments(self, model):
        ''' 辅助函数，对子评论涉及的首页文章和晒单评论，重新计算其子评论计数。'''
        user = model.user
        article = model.article
        review = model.review
        util.count_comments([user] if user else [], [article] if article else [], [review] if review else [])
        # 清除相关数据缓存：
        self._delete_cache(model, article, review)

    def _format_comment(self, comment):
        ''' 辅助函数：用于格式化 Comment 实例，用于接口输出。'''
        comment.valid_user = comment.user
        comment.valid_at_users = util.get_users(comment.at_list or '')
        comment.content = (comment.content or u'').strip()
        return comment
    
    @cache.memoize()
    def _get(self, id=None, article=None, review=None):
        query = db.session.query(Comment).filter(Comment.valid == True)
        query = query.order_by(Comment.publish_time.desc())
        if id:
            query = query.filter(Comment.id == id)
        if article:
            query = query.filter(Comment.article_id == article)
        if review:
            query = query.filter(Comment.review_id == review)
        result = []
        for comment in query:
            self._format_comment(comment)
            result.append(comment)
        return result

    @hmac_auth('api')
    @marshal_with(comment_fields)
    def get(self):
        args = comment_parser.parse_args()
        result = self._get(args['id'], args['article'], args['review'])
        offset = args['offset']
        if offset:
            result = result[offset:]
        limit = args['limit']
        if limit:
            result = result[:limit]
        return result

    @hmac_auth('api')
    def delete(self):
        # 不会真正删除信息，只是设置 valid = False ，以便未来查询。
        args = id_parser.parse_args()
        id = args['id']
        comment = db.session.query(Comment).filter(Comment.id == id).filter(Comment.valid == True).first()
        if comment:
            comment.valid = False
            db.session.commit()
            self._count_comments(comment)
            return '', 204
        abort(404, message='Target Comment do not exists!')

    @hmac_auth('api')
    def post(self):
        ''' 创建新的子评论的接口。'''
        args = comment_parser_detail.parse_args()
        at_list = util.truncate_list(args['at_list'], 200, 20)
        comment = Comment(valid = True,
                          publish_time = datetime.datetime.now(),
                          update_time = datetime.datetime.now(),
                          review_id = args['review'],
                          article_id = args['article'],
                          user_id = args['user'],
                          at_list = at_list,
                          content = args['content'],
                         )
        db.session.add(comment)
        db.session.commit()
        self._count_comments(comment)
        return {'id': comment.id}, 201

    @hmac_auth('api')
    def put(self):
        ''' 修改子评论内容的接口。'''
        args = comment_parser_detail.parse_args()
        id = args['id']
        comment = db.session.query(Comment).filter(Comment.id == id).filter(Comment.valid == True).first()
        if comment:
            at_list = util.truncate_list(args['at_list'], 200, 20)
            comment.update_time = datetime.datetime.now()
            comment.review_id = args['review']
            comment.article_id = args['article']
            comment.user_id = args['user']
            comment.at_list = at_list
            comment.content = args['content']
            db.session.commit()
            self._format_comment(comment)
            return marshal(comment, comment_fields), 201
        abort(404, message='Target Comment do not exists!')

api.add_resource(CommentList, '/rpc/comments')


# 用户关注接口：
follow_parser = reqparse.RequestParser()
follow_parser.add_argument('follow', type=long, required=True)  # 被关注的用户的 id
follow_parser.add_argument('fan', type=long, required=True)    # 作为粉丝的用户 id


class FollowList(Resource):
    '''处理用户关注/取消关注行为的后台服务，其中关注关系的读取在 users 接口中内嵌。'''
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    def _count_follow_fans(self, follow, fan):
        ''' 辅助函数，对交互行为涉及的用户账号，重新计算其 follow_num 和 fans_num 。'''
        # ToDo: 这个实现受读取 User 信息的接口的缓存影响，还不能保证把有效的值传递给前端。
        util.count_follow_fans([follow] if follow else [], [fan] if fan else [])
        # 顺便清除相关缓存：
        UserList()._delete_follow_cache(follow, fan)

    @hmac_auth('api')
    def delete(self):
        ''' 取消关注关系的接口。'''
        args = follow_parser.parse_args()
        follow = db.session.query(User).filter(User.valid == True).filter(User.id == args['follow']).first()
        if follow == None:
            abort(404, message='The user follow do not exists!')
        fan = follow.fans.filter(User.id == args['fan']).first()
        if fan != None:
            follow.fans.remove(fan)
            db.session.commit()
            self._count_follow_fans(follow, fan)
        return '', 204

    @hmac_auth('api')
    def post(self):
        ''' 创建新的用户关注关系的接口。'''
        args = follow_parser.parse_args()
        follow = db.session.query(User).filter(User.valid == True).filter(User.id == args['follow']).first()
        if follow == None:
            abort(404, message='The user follow do not exists!')
        fan = db.session.query(User).filter(User.valid == True).filter(User.id == args['fan']).first()
        if fan == None:
            abort(404, message='The user fan do not exists!')
        if follow.fans.filter(User.id == args['fan']).first() == None:  # 避免多次 follow 同一用户。
            follow.fans.append(fan)
            db.session.commit()
            self._count_follow_fans(follow, fan)
        return '', 201

api.add_resource(FollowList, '/rpc/follows')


# 用户喜欢接口：
like_parser = reqparse.RequestParser()
like_parser.add_argument('offset', type=int)    # offset 偏移量。
like_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
like_parser.add_argument('user', type=long, required=True)

like_parser_detail = reqparse.RequestParser()
like_parser_detail.add_argument('user', type=long, required=True)  # 表达喜欢的用户的 id
like_parser_detail.add_argument('review', type=long, required=True)    # 被表达喜欢的晒单评论 id


class LikeList(Resource):
    '''处理用户喜欢/取消喜欢行为的后台服务，其中喜欢关系的读取在 reviews 接口中内嵌。'''
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    def _delete_cache(self, user):
        if user:
            cache.delete_memoized(self._get, self, user.id)

    def _count_likes(self, user, review):
        ''' 辅助函数，对交互行为涉及的用户账号和晒单评论，重新计算其 like_num 。'''
        # ToDo: 这个实现受读取 User 信息的接口的缓存影响，还不能保证把有效的值传递给前端。
        util.count_likes([user] if user else [], [review] if review else [])
        self._delete_cache(user)

    @cache.memoize()
    def _get(self, user=None):
        brief = 1
        query = db.session.query(Review).filter(Review.valid == True)
        query = query.join(likes, Review.id == likes.columns.review_id)
        query = query.join(User).filter(User.id == likes.columns.user_id)
        query = query.filter(User.id == user)
        query = query.order_by(likes.columns.action_time.desc())
        query = query.filter(Review.published == True)
        result = []
        for review in query:
            _format_review(review, brief)
            result.append(review)
        return result

    @hmac_auth('api')
    def get(self):
        args = like_parser.parse_args()
        result = self._get(args['user'])
        limit = args['limit']
        offset = args['offset']
        if offset:
            result = result[offset:]
        if limit:
            result = result[:limit]
        # 提取 like 关系：
        for review in result:
            review.liked = True
        # 输出结果：
        return marshal(result, review_fields_brief)

    @hmac_auth('api')
    def delete(self):
        ''' 取消喜欢关系的接口。'''
        args = like_parser_detail.parse_args()
        user = db.session.query(User).filter(User.valid == True).filter(User.id == args['user']).first()
        if user == None:
            abort(404, message='The user do not exists!')
        review = user.likes.filter(Review.id == args['review']).first()
        if review != None:
            user.likes.remove(review)
            db.session.commit()
            self._count_likes(user, review)
        return '', 204

    @hmac_auth('api')
    def post(self):
        ''' 创建新的喜欢关系的接口。'''
        args = like_parser_detail.parse_args()
        user = db.session.query(User).filter(User.valid == True).filter(User.id == args['user']).first()
        if user == None:
            abort(404, message='The user do not exists!')
        review = db.session.query(Review).filter(Review.valid == True).filter(Review.id == args['review']).first()
        if review == None:
            abort(404, message='The review do not exists!')
        if user.likes.filter(Review.id == args['review']).first() == None:  # 避免多次 like 同一 Review 。
            user.likes.append(review)
            db.session.commit()
            self._count_likes(user, review)
        return '', 201

api.add_resource(LikeList, '/rpc/likes')


# 收藏 POI 接口：
favorite_parser = reqparse.RequestParser()
favorite_parser.add_argument('offset', type=int)    # offset 偏移量。
favorite_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
favorite_parser.add_argument('user', type=long)      # 用户 id。

favorite_parser_detail = reqparse.RequestParser()
favorite_parser_detail.add_argument('user', type=long, required=True)    # 进行收藏的用户的 id
favorite_parser_detail.add_argument('site', type=long, required=True)    # 被收藏的POI id


class FavoriteList(Resource):
    '''处理用户收藏/取消收藏行为的后台服务，其中收藏关系的读取在 sites 接口中内嵌。'''
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    def _delete_cache(self, user):
        if user:
            cache.delete_memoized(self._get, self, user.id)

    def _count_favorites(self, user, site):
        ''' 辅助函数，对交互行为涉及的用户账号和 POI ，重新计算其 favorite_num 。'''
        # ToDo: 这个实现受读取 User 信息的接口的缓存影响，还不能保证把有效的值传递给前端。
        util.count_favorites([user] if user else [], [site] if site else [])
        self._delete_cache(user)

    @cache.memoize()
    def _get(self, user=None):
        brief = 1
        query = db.session.query(Site).filter(Site.valid == True)
        query = query.join(favorites, Site.id == favorites.columns.site_id)
        query = query.join(User).filter(User.id == favorites.columns.user_id)
        query = query.filter(User.id == user)
        query = query.order_by(favorites.columns.action_time.desc())
        result = []
        for site in query:
            result.append(util.format_site(site, brief))
        return result

    @hmac_auth('api')
    def get(self):
        args = favorite_parser.parse_args()
        result = self._get(args['user'])
        offset = args['offset']
        if offset:
            result = result[offset:]
        limit = args['limit']
        if limit:
            result = result[:limit]
        return marshal(result, site_fields_brief)

    @hmac_auth('api')
    def delete(self):
        ''' 取消收藏关系的接口。'''
        args = favorite_parser_detail.parse_args()
        user = db.session.query(User).filter(User.valid == True).filter(User.id == args['user']).first()
        if user == None:
            abort(404, message='The user do not exists!')
        site = user.favorites.filter(Site.id == args['site']).first()
        if site != None:
            user.favorites.remove(site)
            db.session.commit()
            self._count_favorites(user, site)
        return '', 204

    @hmac_auth('api')
    def post(self):
        ''' 创建新的收藏关系的接口。'''
        args = favorite_parser_detail.parse_args()
        user = db.session.query(User).filter(User.valid == True).filter(User.id == args['user']).first()
        if user == None:
            abort(404, message='The user do not exists!')
        site = db.session.query(Site).filter(Site.valid == True).filter(Site.id == args['site']).first()
        if site == None:
            abort(404, message='The site do not exists!')
        if user.favorites.filter(Site.id == args['site']).first() == None:  # 避免多次 favorite 同一 Site 。
            user.favorites.append(site)
            db.session.commit()
            self._count_favorites(user, site)
        return '', 201

api.add_resource(FavoriteList, '/rpc/favorites')


# 分享 POI，晒单评论，首页文章 接口：
share_parser = reqparse.RequestParser()
share_parser.add_argument('offset', type=int)    # offset 偏移量。
share_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
share_parser.add_argument('user', type=long)      # 用户 id。

share_parser_detail = reqparse.RequestParser()
share_parser_detail.add_argument('user', type=long, required=True)    # 进行分享的用户的 id
share_parser_detail.add_argument('site', type=long, required=True)    # 被分享的POI id
share_parser_detail.add_argument('review', type=long, required=True)    # 被分享的晒单评论 id
share_parser_detail.add_argument('article', type=long, required=True)    # 被分享的首页文章 id
share_parser_detail.add_argument('target', type=unicode, required=True)    # 分享的目标应用，如微信、QQ 等

share_fields = {
    'id': fields.Integer,
    'action_time': util.DateTime,    # RFC822-formatted datetime string in UTC
    'user_id': fields.Integer,        # 进行共享的用户 id （仅用于辅助复查确认，前端展现应该不需要）
    'target': fields.String,        # 分享的目标应用，辅助复查确认用
    'token': fields.String,         # 分享的唯一编码，用于访问被分享的内容
    'url': fields.String,       # 资源在第三方应用中显示详情的网页地址
    'image': fields.Nested(image_fields_mini),   # 资源共享时配合简介的图片，没有时会变成 id 为 0 的图片
    'title': fields.String,     # 资源共享时配合简介的标题
    'description': fields.String,   # 资源共享时配合简介的描述文字
}
share_fields_article = {
    'article': fields.Nested(article_fields_brief, attribute='valid_article'),        # 首页文章的概要信息
    'site': fields.String(attribute='valid_site'),
    'review': fields.String(attribute='valid_review'),
}
share_fields_article.update(share_fields)
share_fields_site = {
    'article': fields.String(attribute='valid_article'),
    'site': fields.Nested(site_fields_brief, attribute='valid_site'),        # POI 的概要信息
    'review': fields.String(attribute='valid_review'),
}
share_fields_site.update(share_fields)
share_fields_review = {
    'article': fields.String(attribute='valid_article'),
    'site': fields.String(attribute='valid_site'),
    'review': fields.Nested(review_fields_brief, attribute='valid_review'),        # 晒单评论的概要信息
}
share_fields_review.update(share_fields)

def marshal_share(data):
    if isinstance(data, (list, tuple)):
        return [marshal_share(d) for d in data]

    if hasattr(data, 'valid_article') and data.valid_article:
        return marshal(data, share_fields_article)
    elif hasattr(data, 'valid_site') and data.valid_site:
        return marshal(data, share_fields_site)
    elif hasattr(data, 'valid_review') and data.valid_review:
        return marshal(data, share_fields_review)
    else:
        abort(404, message='The user shared nothing!')


class ShareList(Resource):
    '''处理用户收藏/取消收藏行为的后台服务，其中收藏关系的读取在 sites 接口中内嵌。'''
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    def _delete_cache(self, user):
        if user:
            cache.delete_memoized(self._get, self, user.id)

    def _count_shares(self, user, site, review, article):
        ''' 辅助函数，对交互行为涉及的用户账号、 POI 、晒单评论、首页文章，重新计算其 share_num 。'''
        # ToDo: 这个实现受读取 User 信息的接口的缓存影响，还不能保证把有效的值传递给前端。
        util.count_shares([user] if user else [], [site] if site else [], [review] if review else [], [article] if article else [])
        self._delete_cache(user)

    def _format_share(self, share):
        ''' 辅助函数：用于格式化 ShareRecord 实例，用于接口输出。'''
        if share.article:
            article = share.article
            share.valid_article = _format_article(article)
            share.url = baseurl_share + '/articles/' + share.token
            share.image = article.caption
            share.title = article.title
            content_list = util.parse_textstyle(util.replace_textlib(article.content))
            text_list = filter(lambda x: x['class'] == 'text', content_list)
            share.description = u'' if len(text_list) == 0 else text_list[0]['content']
        elif share.site:
            site = share.site
            share.valid_site = util.format_site(site)
            share.url = baseurl_share + '/sites/' + share.token
            share.image = site.logo
            share.title = site.name
            share.description = site.description
        elif share.review:
            review = share.review
            share.valid_review = _format_review(review, brief = True)
            share.url = baseurl_share + '/reviews/' + share.token
            images = review.valid_images
            share.image = None if len(images) == 0 else images[0]
            share.title = review.user.name
            share.description = review.content
        else:
            share.url = ''
            share.image = None
            share.title = u''
            share.description = u''
        return share

    @cache.memoize()
    def _get(self, user=None):
        query = db.session.query(ShareRecord).filter(ShareRecord.user_id == user)
        query = query.order_by(ShareRecord.action_time.desc())  # 对同一个 Article，Site，Review，显示其最新的一次共享
        query = db.session.query().add_entity(ShareRecord, alias=query.subquery()).group_by('article_id', 'site_id', 'review_id')         # 让 order_by 比 group_by 更早生效！
        query = query.order_by(desc('action_time'))      # 保证 group 后输出结果的顺序
        result = []
        for share_record in query:
            result.append(self._format_share(share_record))
        return result

    @hmac_auth('api')
    def get(self):
        args = share_parser.parse_args()
        user_id = args['user']
        result = self._get(user_id)
        offset = args['offset']
        if offset:
            result = result[offset:]
        limit = args['limit']
        if limit:
            result = result[:limit]
        # 处理 review 的 like 关系：
        if user_id:
            token = db.session.query(Token).filter(Token.user_id == user_id).first()
            token = '' if not token else token.token
            for share in result:
                if hasattr(share, 'valid_review') and share.valid_review:
                    _format_review_like([share.valid_review], token)
        return marshal_share(result)

    # 共享行为类似一个行为记录，一旦发生就无法取消记录。
    @hmac_auth('api')
    def post(self):
        ''' 创建新的共享行为记录的接口。'''
        args = share_parser_detail.parse_args()
        user_id = args['user']
        site_id = args['site']
        review_id = args['review']
        article_id = args['article']
        user = db.session.query(User).filter(User.valid == True).filter(User.id == user_id).first()
        if user == None:
            abort(404, message='The user do not exists!')
        article = db.session.query(Article).filter(Article.valid == True).filter(Article.id == article_id).first()
        if article_id and article == None:
            abort(404, message='The shared article do not exists!')
        site = db.session.query(Site).filter(Site.valid == True).filter(Site.id == site_id).first()
        if site_id and site == None:
            abort(404, message='The shared site do not exists!')
        review = db.session.query(Review).filter(Review.valid == True).filter(Review.published == True).filter(Review.id == review_id).first()
        if review_id and review == None:
            abort(404, message='The shared review do not exists!')
        share_record = ShareRecord(user_id = user_id,
                                   article_id = article_id or None,
                                   site_id = site_id or None,
                                   review_id = review_id or None,
                                   target = args['target'],
                                   )
        db.session.add(share_record)
        db.session.commit()
        self._count_shares(user, 
                           share_record.site,
                           share_record.review,
                           share_record.article,
                           )
        self._format_share(share_record)
        return marshal(share_record, share_fields), 201

api.add_resource(ShareList, '/rpc/shares')


# ToDo: 应该做一个发全局通知的接口，避免很多不登陆的用户创建大量的用户消息记录（由于每个消息需要保存每个用户的已读、未读记录）。

# 用户消息对话线索接口
message_parser = reqparse.RequestParser()
message_parser.add_argument('stop', type=long, default=0)   # 截止 message id，也即返回数据只考虑 id 大于这一指定值的 message 消息。（注意：分批读取时每次请求的截止 message id 不能轻易变化，否则会使缓存失效！而应该使用 offset 来控制！）
message_parser.add_argument('offset', type=int)    # offset 偏移量。
message_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
message_parser.add_argument('user', type=long, required=True)      # 仅获取这一指定用户的消息
message_parser.add_argument('thread', type=str)         # 仅获取这一指定对话线索的消息

message_fields_thread = {
    'id': fields.Integer,       # 当前对话线索中，最新一条的消息 id
    'thread': fields.String(attribute='group_key'),        # 对话线索标识，也即后台数据库中的 group_key （私信消息分组快捷键，将本消息相关 user_id 按从小到大排序，用“_”连接作为 Key）
    'create_time': util.DateTime,    # RFC822-formatted datetime string in UTC
    'sender': fields.Nested(user_fields_mini, attribute='valid_sender'),        # 发送人的账号信息
    'content': fields.String,   # 消息文本正文，如果是系统发送的消息，则可能存在应用内资源的跳转链接。（截取前 100 个字符差不多够了吧？）
    'unread': fields.Integer,   # 该线索的未读消息数
}


class MessageThreadList(Resource):
    '''获取对话线索的列表，每个线索提供信息概要和未读数。'''
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    @cache.memoize(50)  # 缓存时间只能设置得非常短，要不新消息会延迟收到。
    def _get(self, stop=0, user=None, thread=None):     # thread 接口的 stop 更新逻辑，需要是没有未读消息时，记录当时的最大 message id 作为下一次 stop 的值。
        # 计算未读数：
        unread_dic = {}
        query = db.session.query(UserReadMessage.id, Message.group_key, func.count(Message.id)).join(UserReadMessage.message).filter(Message.valid == True).filter(Message.id > stop).filter(UserReadMessage.has_read == False)
        if user:
            query = query.filter(UserReadMessage.user_id == user)
        if thread:
            query = query.filter(Message.group_key == thread)
        query = query.group_by(Message.group_key)
        for row in query:
            user_read_message_id, group_key, unread_count = row
            unread_dic[group_key] = unread_count
        # 准备消息线索：
        query = db.session.query(Message).filter(Message.valid == True).filter(Message.id > stop)
        if user:
            query = query.join(Message.users).filter(User.id == user)
        if thread:
            query = query.filter(Message.group_key == thread)
        query = query.order_by(Message.create_time.desc())      # 每个对话组显示最新一条的详情
        query = db.session.query().add_entity(Message, alias=query.subquery()).group_by('group_key')         # 让 order_by 比 group_by 更早生效！
        query = query.order_by(desc('create_time'))     # 保证 group 后输出结果的顺序
        result = []
        for thread in query:
            thread.content = (thread.content or u'').strip()
            thread.valid_sender = thread.sender_user
            thread.unread = unread_dic.get(thread.group_key, 0)         # 输出未读数
            result.append(thread)
        result.reverse()        # 输出时旧的 Thread 先输出，以便分批读取。
        return result

    @hmac_auth('api')
    @marshal_with(message_fields_thread)
    def get(self):
        args = message_parser.parse_args()
        result = self._get(args['stop'], args['user'], args['thread'])
        offset = args['offset']
        if offset:
            result = result[offset:]
        limit = args['limit']
        if limit:
            result = result[:limit]
        return result

api.add_resource(MessageThreadList, '/rpc/messages/threads')


# 用户消息接口
message_parser_detail = reqparse.RequestParser()         # 用于创建新 message 信息的参数集合
message_parser_detail.add_argument('sender', type=long, required=True)     # 消息发送人
message_parser_detail.add_argument('receiver', type=long, required=True)     # 消息接收人
message_parser_detail.add_argument('content', type=unicode, required=True)      # 消息文本正文，如果是系统发送的消息，则可能存在应用内资源的跳转链接。

message_fields = {
    'id': fields.Integer,
    'create_time': util.DateTime,    # RFC822-formatted datetime string in UTC
    'sender_id': fields.Integer,        # 发送人的 user id （message 详情通常用于提取一个对话线索中的详细消息，因此 user 的详细属性就不展开了。）
    'content': fields.String,   # 消息文本正文，如果是系统发送的消息，则可能存在应用内资源的跳转链接。
    'thread': fields.String(attribute='group_key'),        # 对话线索标识。其实是冗余的，因为在参数里通常已经指定 thread 了，但再次显示用于确认。
}


class MessageList(Resource):
    '''获取用户消息详情的列表。并能够通过这一接口创建新用户消息。'''
    # 暂时不提供删除、修改操作。
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    @cache.memoize(50)  # 缓存时间只能设置得非常短，要不新消息会延迟收到。
    def _get(self, stop=0, user=None, thread=None):     # Message 接口的 stop 值，只需考虑当前对话线索历史读取过的最大 id 值即可。
        query = db.session.query(Message).filter(Message.valid == True).filter(Message.id > stop)
        if user:
            query = query.join(Message.users).filter(User.id == user)
        if thread:
            query = query.filter(Message.group_key == thread)
        query = query.order_by(Message.id)      # 从旧的消息开始显示，以便分组读取以及设置 stop
        result = []
        for message in query:
            message.content = (message.content or u'').strip()
            message.sender_id = message.sender_user_id
            result.append(message)
        return result

    @hmac_auth('api')
    @marshal_with(message_fields)
    def get(self):
        args = message_parser.parse_args()
        user = args['user']
        result = self._get(args['stop'], user, args['thread'])
        offset = args['offset']
        if offset:
            result = result[offset:]
        limit = args['limit']
        if limit:
            result = result[:limit]
        # 已发送完的消息将被设置为已读状态：
        message_ids = [message.id for message in result]
        unread_messages = db.session.query(UserReadMessage).filter(UserReadMessage.has_read == False).filter(UserReadMessage.user_id == user).filter(UserReadMessage.message_id.in_(message_ids)).all()
        for unread_message in unread_messages:
            unread_message.has_read = True
        db.session.commit()
        return result

    @hmac_auth('api')
    def post(self):
        ''' 创建新的用户消息的接口。'''
        args = message_parser_detail.parse_args()
        # ToDo: 这里没有对 sender 和 receiver 是否是合法的用户账号进行检查，也即需要客户端保证。
        sender = args['sender']
        receiver = args['receiver']
        user_ids = [sender, receiver]
        user_ids.sort()
        group_key = '_'.join(map(str, user_ids))
        message = Message(valid = True,
                          create_time = datetime.datetime.now(),
                          sender_user_id = sender,
                          content = args['content'],
                          group_key = group_key,
                         )
        db.session.add(message)
        db.session.commit()
        message_id = message.id
        read_record = UserReadMessage(user_id = sender,
                                      message_id = message_id,
                                      has_read = True,
                                      )
        db.session.add(read_record)
        read_record = UserReadMessage(user_id = receiver,
                                      message_id = message_id,
                                      has_read = False,
                                      )
        db.session.add(read_record)
        db.session.commit()
        return {'id': message_id}, 201

api.add_resource(MessageList, '/rpc/messages')


# 用户消息未读数接口
message_parser_unread = reqparse.RequestParser()         
message_parser_unread.add_argument('user', type=long, required=True)     # 仅获取此指定用户的消息
message_parser_unread.add_argument('thread', type=str)   # 对话线索标识，也即后台数据库中的 group_key （私信消息分组快捷键，将本消息相关 user_id 按从小到大排序，用“_”连接作为 Key）

message_fields_unread = {
    'thread': fields.String,        # 对话线索标识，为空时标识是该用户的全部维度消息数
    'unread': fields.Integer,   # 指定用户的未读消息数。当前版本只返回 0 或 1，而不会给准确的具体数字以降低计算量
}


class MessageUnreadList(Resource):
    '''获取指定用户的未读消息信息，当前版本暂时只提供了未读数。'''
    # 为节省性能，应该只返回是否有未读数就行了。
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    # 这个接口我认为不需要缓存！ @cache.memoize(50)  # 缓存时间只能设置得非常短，要不新消息会延迟收到。
    def _get(self, user=None, thread=None):
        query = db.session.query(UserReadMessage).join(UserReadMessage.message).filter(Message.valid == True).filter(UserReadMessage.has_read == False)
        if user:
            query = query.filter(UserReadMessage.user_id == user)
        if thread:
            query = query.filter(Message.group_key == thread)
        has_unread = query.first()
        unread = 1 if has_unread else 0
        return {'thread': thread,
                'unread': unread,
                }

    @hmac_auth('api')
    @marshal_with(message_fields_unread)
    def get(self):
        args = message_parser_unread.parse_args()
        return self._get(args['user'], args['thread'])

api.add_resource(MessageUnreadList, '/rpc/messages/unread')


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


