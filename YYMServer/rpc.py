# -*- coding: utf-8 -*-

import json
import time, datetime

import pytz
from sqlalchemy import func, desc, or_, and_
from sqlalchemy.orm import aliased
from werkzeug.security import generate_password_hash, check_password_hash

from flask import jsonify, request, url_for
from flask.ext.restful import reqparse, Resource, fields, marshal_with, marshal, abort
from flask.ext.restful import output_json as restful_output_json
from flask.ext.hmacauth import hmac_auth

from qiniu.auth import digest

from YYMServer import app, db, cache, api, util, message, baseurl_share, tz_server
from YYMServer.models import *
from YYMServer.keywords import KEYWORDS_TRANS

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
id_parser.add_argument('id', type=long, default=0l)


class ImageUrl(fields.Raw):
    def format(self, path):
        return util.extend_image_path(path)


# 图片信息查询接口：
image_parser = reqparse.RequestParser()
image_parser.add_argument('id', type=long, default=0l)       # 这里的 type 参数指明的 类型，需要保证与 model 中的对应字段一致！model 中的 Integer 这里对应 long； model 中的 SmallInteger 这里对应 int。
image_parser.add_argument('offset', type=int, default=0)    # offset 偏移量。
image_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
image_parser.add_argument('site', type=long, default=0l)      # 指定 POI id，获取所有相关图片
image_parser.add_argument('review', type=long, default=0l)   # 指定晒单评论 id，获取所有相关图片

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
    'create_time': util.DateTime,    # RFC3339 格式的时间戳字符串
    'user_id': fields.Integer,
    'mime': fields.String,
    'width': fields.Integer,
    'height': fields.Integer,
}
image_fields.update(image_fields_mini)


class ImageList(Resource):
    '''提供图片的增、查、删三组服务。'''
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    @cache.memoize()
    # 貌似不需要处理动态缓存更新，site 可以接受图片更新延迟，review 则通常不会单独从这个接口取图片。
    def _get(self, id=0l, site=0l, review=0l):
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
            return '', 200
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
image_call_parser.add_argument('id', type=long, default=0l)      # 图片在数据库中的 id ，如果是覆盖数据库中已存在的图片，则应提供这个参数指定图片的原始 id 。
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
user_parser.add_argument('id', type=long, default=0l)
user_parser.add_argument('brief', type=int, default=0)     # 大于 0 表示只输出概要信息即可（默认只概要）。
user_parser.add_argument('em', type=str)    # 环信用户名，用于反查 user 信息。多个环信账号用英文逗号分隔。
user_parser.add_argument('offset', type=int, default=0)    # offset 偏移量。
user_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
user_parser.add_argument('follow', type=long, default=0l)      # 关注指定 id 所对应用户的账号列表
user_parser.add_argument('fan', type=long, default=0l)         # 有指定 id 所对应用户作为粉丝的账号列表
user_parser.add_argument('token', type=str)     # 用户 token，用于获取是否关注的关系

user_parser_detail = reqparse.RequestParser()         # 用于创建和更新一个 User 的信息的参数集合
user_parser_detail.add_argument('id', type=long, default=0l)
user_parser_detail.add_argument('icon', type=long)        # 用户头像对应图片的 id
user_parser_detail.add_argument('name', type=unicode)    # 用户昵称，不能与已有的昵称重复，否则报错。
user_parser_detail.add_argument('mobile', type=str)  # 预留手机号接口，但 App 前端在初期版本不应该允许用户修改！不能与其他用户的手机号重复，否则报错。
user_parser_detail.add_argument('password', type=str)  # 账号密码的明文，至少6个字符。
user_parser_detail.add_argument('gender', type=unicode)    # 用户性别：文字直接表示的“男、女、未知”
user_parser_detail.add_argument('token', type=str)  # 注册时代表旧 token，用于迁移登录前发生的匿名行为。查询时用于代表当前用户获取对目标用户的 关注 状态。
user_parser_detail.add_argument('device', type=str)      # 设备 id 。
user_parser_detail.add_argument('old_password', type=str, default='')  # 账号旧密码的明文，至少6个字符。当用户修改密码时，会要求提供正确的旧密码，否则拒绝修改。

user_fields_mini = {
    'id': fields.Integer,
    'icon': fields.Nested(image_fields_mini, attribute='icon_image'),   # 用户头像，没有时会变成 id 为 0 的图片
    'name': fields.String,      # 用户昵称
    'level': fields.Integer,    # 用数字表示的用户等级
    'follow_num': fields.Integer,      # 该用户已关注的账号的数量，是一个缓存值
    'fans_num': fields.Integer,      # 该用户拥有的粉丝数量，是一个缓存值
    'followed': fields.Boolean,         # 当前 token 参数表示的用户是否关注了此用户（依赖于有效的 token 参数，否则一定会是 null）
    'badges': fields.List(fields.String, attribute='formated_badges'),    # 用户拥有的徽章名称列表
}
user_fields_brief = {
    'em_username': fields.String,   # 用户对应的环信账号用户名
}
user_fields_brief.update(user_fields_mini)
user_fields = {
    'anonymous': fields.Boolean,
    'create_time': util.DateTime,    # 首次创建时间，RFC3339 格式的时间戳字符串
    'update_time': util.DateTime,    # 用户属性修改时间，RFC3339 格式的时间戳字符串
    'username': fields.String,  # 登陆用用户名，App 端会是设备 id（匿名用户）或手机号（已注册用户）
    'mobile': fields.String,    # 用户手机号    # ToDo: 可能存在用户信息泄露的风险。
    'gender': fields.String,    # 性别：文字直接表示的“男、女、未知”
    'exp': fields.Integer,      # 与用户等级对应的用户经验，需要根据每天的行为日志做更新
    'like_num': fields.Integer,      # 该用户喜欢的晒单评论数量，是一个缓存值
    'share_num': fields.Integer,      # 该用户的分享行为数量，是一个缓存值
    'review_num': fields.Integer,      # 该用户发表的晒单评论数量，是一个缓存值
    'favorite_num': fields.Integer,      # 该用户收藏的店铺的数量，是一个缓存值
    'em_password': fields.String,   # 用户对应的环信账号密码
}
user_fields.update(user_fields_brief)

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

    def _delete_follow_cache(self, follow, fan):
        ''' 辅助函数：清除指定 follow 和 fan 的缓存数据。'''
        follow_id = 0l if not follow else follow.id
        fan_id = 0l if not fan else fan.id
        if follow_id:
            cache.delete_memoized(self._get, self, 0l, follow_id, 0l)
        if fan_id:
            cache.delete_memoized(self._get, self, 0l, 0l, fan_id)

    def _check_password(self, password):
        ''' 辅助函数：用于检查用户提交的新密码的合规性。'''
        if len(password) < 6:
            abort(409, message='The password length should be at least 6 characters!')
    
    @cache.memoize()
    def _get(self, id=0l, em='', follow=0l, fan=0l):
        # 当指定用户 id 进行查询时，即使该用户 valid 为 False，也仍然给出详细信息。
        result = []
        if id:
            query = db.session.query(User.id).filter(User.id == id)
            result = query.all()
        elif em:
            em_ids = em.strip().split(',')
            query = db.session.query(User.id).filter(User.em_username.in_(em_ids))
            result = query.all()
        elif follow:
            Main_User = aliased(User)
            query = db.session.query(User.id).filter(User.valid == True).join(fans, User.id == fans.columns.fan_id).join(Main_User, fans.columns.user_id == Main_User.id).filter(Main_User.id == follow).order_by(fans.columns.action_time.desc())
            result = query.all()
        elif fan:
            Main_User = aliased(User)
            query = db.session.query(User.id).filter(User.valid == True).join(fans, User.id == fans.columns.user_id).join(Main_User, fans.columns.fan_id == Main_User.id).filter(Main_User.id == fan).order_by(fans.columns.action_time.desc())
            result = query.all()
        return result

    @hmac_auth('api')
    def get(self):
        args = user_parser.parse_args()
        id = args['id']
        result = self._get(id, args['em'], args['follow'], args['fan'])
        # 分组输出：
        offset = args['offset']
        if offset:
            result = result[offset:]
        limit = args['limit']
        if limit:
            result = result[:limit]
        # 准备具体属性数据：
        token = args['token']
        if id:
            result = util.get_info_users(map(lambda x: x[0], result), valid_only = False, token = token)
        else:
            result = util.get_info_users(map(lambda x: x[0], result), token = token)
        brief = args['brief']
        if brief:
            return marshal(result, user_fields_brief)
        else:
            return marshal(result, user_fields)

    @hmac_auth('api')
    def post(self):
        ''' 用户注册或创建新的匿名用户的接口。'''
        args = user_parser_detail.parse_args()
        mobile = args['mobile'] or None
        password = args['password'] or None
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
        util.update_cache(user, format_func = util.format_user)
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
                if not check_password_hash(user.password, args['old_password']):
                    abort(409, message='The old password is not correct!')
                self._check_password(password)
                user.password = password        # 明文 password 会被 Model 自动加密保存
            gender = args['gender']
            if gender:
                user.gender = gender
            db.session.commit()
            util.update_cache(user, format_func = util.format_user)
            return marshal(user, user_fields), 200
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
    old_user = None
    if old_token:
        old_user = db.session.query(User).join(User.tokens).filter(Token.token == old_token).first()
        if old_user:
            # 建立后台任务，合并旧 token 的行为数据到当前登陆的新账号：
            if new_user.anonymous == False and old_user.anonymous == True and new_user.id != old_user.id:
                task_data = {'from': old_user.id,
                             'to': new_user.id,
                            }
                task = Task(type = 'transfer_actions',
                            data = json.dumps(task_data),
                           )
                db.session.add(task)
                db.session.commit()
    # 永远生成新 token，而不复用之前产生的 token。
    token = Token(user_id = new_user.id,
                  device = device,
                  )
    db.session.add(token)
    db.session.commit()
    # 检查是否应该创建未发送的通知：
    if old_user:
        receiver_check = or_(Message.receiver_user_id == new_user.id, Message.receiver_user_id == old_user.id)
    else:
        receiver_check = or_(Message.receiver_user_id == new_user.id)
    unsent_announces = db.session.query(Announce.id).filter(Announce.valid == True).filter(Announce.at_login == True).outerjoin(Message, and_(Announce.id == Message.announce_id, receiver_check)).filter(Message.id == None)
    for unsent_announce in unsent_announces:
        announce_id = unsent_announce[0]
        util.send_message(323, new_user.id, announce_id)  # 以运营经理名义发送
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
        args = login_parser.parse_args()
        user = db.session.query(User).filter(User.valid == True).filter(User.anonymous == False).filter(User.username == args['username']).first()
        if not user or not check_password_hash(user.password, args['password']):
            abort(403, message='Login Failed!')
        old_token = args['token']
        token = _generate_token(user, args['device'], old_token)    # 把登录前匿名用户的历史行为尽可能地迁移过来！
        util.update_cache(user, format_func = util.format_user)
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
    def _get(self, id=0l):
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
city_parser = reqparse.RequestParser()
city_parser.add_argument('id', type=long, default=0l)
city_parser.add_argument('longitude', type=float)       # 用户当前位置的经度
city_parser.add_argument('latitude', type=float)        # 用户当前位置的维度

city_fields = {
    'id': fields.Integer,
    'name': fields.String,
    'order': fields.Integer,
    'longitude': fields.Float,
    'latitude': fields.Float,
    'timezone': fields.String,  # 城市对应的时区，例如 America/New_York 。
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
        children.sort(key = lambda x: x.name.encode('GB18030', 'ignore'))  # 按拼音排序，忽略了 order 的效果。
        for child in children:
            self._get_children_areas(child)
        parent.valid_areas = children

    @cache.memoize()
    def _get(self, id=0l):
        query = db.session.query(City).filter(City.valid == True).order_by(City.order.desc())
        if id:
            query = query.filter(City.id == id)
        sorted_result = query.all()
        sorted_result.sort(key = lambda x: x.name.encode('GB18030', 'ignore'))  # 按拼音排序，忽略了 order 的效果。
        result = []
        for city in sorted_result:
            self._get_children_areas(city)
            result.append(city)
        return result

    @hmac_auth('api')
    @marshal_with(nested_city_fields)
    def get(self):
        # ToDo: 这里默认对每个城市会输出其 areas 列表，在城市多了之后这一块的响应性能可能会很差。
        args = city_parser.parse_args()
        id = args['id']
        result = self._get(id)
        longitude = args['longitude']
        latitude = args['latitude']
        # 参数中存在经纬度信息时，将距离最近的城市放到最前，其余城市按照拼音顺序排序
        first_city = None
        if longitude and latitude:
            sorted_result = []
            for city in result:
                lon = city.longitude
                lat = city.latitude
                distance = 40000.0 if not lon or not lat else util.get_distance(longitude, latitude, lon, lat)
                sorted_result.append({'obj': city,
                                      'dist': distance,
                                     })
            sorted_result.sort(key = lambda x: x['dist'])
            if sorted_result[0]['dist'] > 300:  # 最近的城市距离有 300 公里时，则默认城市改为放到最前
                for i in range(len(sorted_result)):
                    if sorted_result[i]['obj'].id == 1:     # 默认纽约
                        default_city = sorted_result.pop(i)
                        sorted_result.insert(0, default_city)
            first_city = sorted_result[0]['obj']
        if first_city:
            for i in range(len(result)):
                if result[i].id == first_city.id:
                    result.pop(i)
                    result.insert(0, first_city)
        return result

api.add_resource(CityList, '/rpc/cities')


# 国家接口：
country_parser = reqparse.RequestParser()
country_parser.add_argument('id', type=long, default=0l)
country_parser.add_argument('longitude', type=float)       # 用户当前位置的经度
country_parser.add_argument('latitude', type=float)        # 用户当前位置的维度

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
    def _get(self, id=0l):
        query = db.session.query(Country).filter(Country.valid == True).order_by(Country.order.desc())
        if id:
            query = query.filter(Country.id == id)
        sorted_result = query.all()
        sorted_result.sort(key = lambda x: x.name.encode('GB18030', 'ignore'))  # 按拼音排序，忽略了 order 的效果。
        result = []
        for country in sorted_result:
            country.valid_cities = country.cities.filter(City.valid == True).order_by(City.order.desc()).all()
            country.valid_cities.sort(key = lambda x: x.name.encode('GB18030', 'ignore'))  # 按拼音排序，忽略了 order 的效果。
            country.valid_default_city = country.default_city   # 为了能使动态绑定数据被缓存，从而允许 self.get() 中使用。
            result.append(country)
        return result

    @hmac_auth('api')
    @marshal_with(country_fields)
    def get(self):
        args = country_parser.parse_args()
        id = args['id']
        result = self._get(id)
        longitude = args['longitude']
        latitude = args['latitude']
        # 参数中存在经纬度信息时，将距离最近的国家放到最前，其余国家按照拼音顺序排序
        # ToDo: 此排序实现在国家比较多的时候可能存在性能问题。。。
        first_country = None
        if longitude and latitude:
            sorted_result = []
            for country in result:
                if country.valid_default_city:
                    lon = country.valid_default_city.longitude
                    lat = country.valid_default_city.latitude
                else:
                    lon = None
                    lat = None
                distance = 40000.0 if not lon or not lat else util.get_distance(longitude, latitude, lon, lat)
                sorted_result.append({'obj': country,
                                      'dist': distance,
                                     })
            sorted_result.sort(key = lambda x: x['dist'])
            if sorted_result[0]['dist'] > 5000:  # 最近的国家距离有 5000 公里时，则默认国家改为放到最前
                for i in range(len(sorted_result)):
                    if sorted_result[i]['obj'].id == 1:     # 默认美国
                        default_country = sorted_result.pop(i)
                        sorted_result.insert(0, default_country)
            first_country = sorted_result[0]['obj']
        if first_country:
            for i in range(len(result)):
                if result[i].id == first_country.id:
                    result.pop(i)
                    result.insert(0, first_country)
        return result

api.add_resource(CountryList, '/rpc/countries')


# POI 接口：
site_parser = reqparse.RequestParser()
site_parser.add_argument('id', type=long, default=0l)
site_parser.add_argument('brief', type=int, default=1)     # 大于 0 表示只输出概要信息即可（默认只概要）。
site_parser.add_argument('offset', type=int, default=0)    # offset 偏移量。
site_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
site_parser.add_argument('keywords', type=unicode)  # 搜索关键词，空格或英文加号分隔，默认的关系是“且”。搜索时大小写不敏感。
site_parser.add_argument('area', type=long, default=0l)      # 商圈 id。
site_parser.add_argument('city', type=long, default=0l)      # 城市 id。
site_parser.add_argument('range', type=int, default=0)     # 范围公里数。如果是 -1，则表示“全城”。如果商圈、范围都是空，则表示默认的“智能范围”。
site_parser.add_argument('category', type=long, default=0l)  # 分类 id。为空则表示“全部分类”。
site_parser.add_argument('order', type=int, default=0)     # 0 表示默认的“智能排序”，1 表示“距离最近”（约近约靠前），2 表示“人气最高”（点击量由高到低），3 表示“评价最好”（评分由高到低）。
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
    def _get(self, brief=0, id=0l, keywords=u'', area=0l, city=0l, range=0, category=0l, order=0, geohash=None):
        ''' 本函数实际上只是根据搜索条件，给出搜索结果对应的 POI id 序列。详细属性需要通过 util.get_info_sites 函数读取，以减小缓存提及。'''
        # ToDo: 需要利用 geohash，实现高效率的距离初步筛选！
        query = db.session.query(Site.id, Site.longitude, Site.latitude).filter(Site.valid == True)
        if order is not None:
            if order == 1:      # 距离最近：
                pass    # 在 _get_sorted 函数中实现。
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
            for i in xrange(len(keyword_list)):
                target = KEYWORDS_TRANS.get(keyword_list[i], None)
                if target != None:
                    keyword_list.append(target)
            for keyword in keyword_list:
                query = query.filter(Site.name.ilike(u'%{}%'.format(keyword)) | 
                                     Site.name_orig.ilike(u'%{}%'.format(keyword)) |
                                     Site.address.ilike(u'%{}%'.format(keyword)) |
                                     Site.address_orig.ilike(u'%{}%'.format(keyword)) 
                                    )
        result = query.all()
        return result

    @cache.memoize()
    def _get_sorted(self, brief=0, id=0l, keywords=u'', area=0l, city=0l, range=0, category=0l, order=0, longitude = None, latitude = None):
        ''' 本函数基于 _get 函数封装数据库查询给出的基础结果，进一步用 Python 处理复杂的排序条件等，并利用缓存支撑用户端分批读取。'''
        if not area and (range == None or range == 0):
            range = 5   # ToDo: 如果商圈和 range 都没有设置，表示智能范围（注意：range 为 -1 时表示全城搜索）。这里暂时只是把搜索范围置成5公里了。
        # ToDo: 应当利用 geohash，实现高效率的距离初步筛选！
        geohash = None
        result = []
        site_items = self._get(brief, id, keywords, area, city, range, category, order, geohash)
        for site_item in site_items:
            id, lon, lat = site_item
            distance = 0.0 if not longitude or not latitude else util.get_distance(longitude, latitude, lon, lat)
            if range and distance > range:
                continue
            result.append({'id': id,
                           'dist': distance,
                          })
        if order == 1:
            result.sort(key = lambda x: x['dist'])
        result = map(lambda x: x['id'], result)
        return result

    @hmac_auth('api')
    def get(self):
        args = site_parser.parse_args()
        longitude = args['longitude']
        latitude = args['latitude']
        longitude = None if not longitude else round(longitude, 4)     # 降低位置精度到 10m 量级，期望靠这个保证用户稍稍移动时缓存仍然有效。
        latitude = None if not latitude else round(latitude, 4)
        # 基本搜索条件处理：
        brief = args['brief']
        result = self._get_sorted(brief, args['id'], args['keywords'], args['area'], args['city'], args['range'], args['category'], args['order'], longitude, latitude)
        offset = args['offset']
        if offset:
            result = result[offset:]
        limit = args['limit']
        if limit:
            result = result[:limit]
        # 读取具体的 site 信息详情：
        result = util.get_info_sites(result)
        # 提取 favorite 关系：
        if not brief:
            token = args['token']
            if token:        # ToDo: 这里查询收藏关系使用的是数据库查询，存在性能风险！
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
article_parser.add_argument('id', type=long, default=0l)
article_parser.add_argument('brief', type=int, default=1)     # 大于 0 表示只输出概要信息即可（默认只概要）。
article_parser.add_argument('offset', type=int, default=0)    # offset 偏移量。
article_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
article_parser.add_argument('city', type=long, default=0l)      # 城市 id。

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
    'create_time': util.DateTime,    # RFC3339 格式的时间戳字符串
    'title': fields.String,         # 首页文章的标题
    'caption': fields.Nested(image_fields_mini, attribute='caption_image'),     # 首页文章的标题衬图（也即首图）
    'keywords': fields.List(fields.String, attribute='formated_keywords'),      # 概要状态通常只使用第一个关键词
}
article_fields = {
    'update_time': util.DateTime,    # RFC3339 格式的时间戳字符串
    'content': fields.List(ContentEntry, attribute='formated_content'),         # 首页文章的文本正文，需区分自然段、小标题、图片、店铺链接、分隔符等特殊格式！
    'comment_num': fields.Integer,
}
article_fields.update(article_fields_brief)

def get_info_articles(article_ids, valid_only = True):
    ''' 辅助函数：提取指定 id 的首页文章内容详情，并使用缓存。'''
    return util.get_info_ids(Article, article_ids, format_func = util.format_article, valid_only = valid_only)

def get_info_article(article_id, valid_only = True):
    result = get_info_articles([article_id], valid_only = valid_only)
    return None if not result else result[0]


class ArticleList(Resource):
    '''按城市获取相关首页推荐文章的接口。'''

    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    @cache.memoize()
    def _get(self, id=0l, city=0l):
        query = db.session.query(Article).filter(Article.valid == True)
        if id:
            query = query.filter(Article.id == id)
        if city:
            # 指定城市及该城市对应国家的文章都输出，以增加文章丰富度：
            city_object = db.session.query(City).filter(City.valid == True).filter(City.id == city).first()
            country = -1 if not city_object else city_object.country_id
            query_city = query.join(Article.cities).filter(City.id == city)
            query_country = query.join(Article.countries).filter(Country.id == country)
            query = query_city.union(query_country)
        query = query.order_by(Article.order.desc()).order_by(Article.create_time.desc())
        result = map(lambda x: x.id, query.all())
        return result

    @hmac_auth('api')
    def get(self):
        args = article_parser.parse_args()
        result = self._get(args['id'], args['city'])
        offset = args['offset']
        if offset:
            result = result[offset:]
        limit = args['limit']
        if limit:
            result = result[:limit]
        result = get_info_articles(result)
        brief = args['brief']
        if brief:
            return marshal(result, article_fields_brief)
        else:
            return marshal(result, article_fields)

api.add_resource(ArticleList, '/rpc/articles')


# 小贴士接口：
tips_parser = reqparse.RequestParser()
tips_parser.add_argument('id', type=long, default=0l)
tips_parser.add_argument('brief', type=int, default=1)     # 大于 0 表示只输出概要信息即可（默认只概要）。
tips_parser.add_argument('city', type=long, default=0l)      # 城市 id。

tips_fields_brief = {
    'id': fields.Integer,
    'default': fields.Boolean,  # 是否是当前城市的默认贴士
    'create_time': util.DateTime,    # RFC3339 格式的时间戳字符串
    'title': fields.String,         # Tips 的标题，用于列表选单，不用于正文显示
}
tips_fields = {
    'update_time': util.DateTime,    # RFC3339 格式的时间戳字符串
    'content': fields.List(ContentEntry, attribute='formated_content'),         # 小贴士的文本正文，需区分自然段、小标题、分隔符、排序列表等特殊格式！以及支持对其他 Tips 的引用（例如该国家通用的内容）
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
    def _get(self, brief=0, id=0l, city=0l):
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
review_parser.add_argument('id', type=long, default=0l)
review_parser.add_argument('brief', type=int, default=1)     # 大于 0 表示只输出概要信息即可（默认只概要）。
review_parser.add_argument('selected', type=int, default=0)     # 大于 0 表示只输出置顶信息即可（例如 POI 详情页面中的晒单评论），不够 limit 的要求时，会用非置顶信息补足。
review_parser.add_argument('published', type=int, default=1)     # 大于 0 表示只输出已发表的（默认只已发表的），否则也可输出草稿。
review_parser.add_argument('offset', type=int)    # offset 偏移量。
review_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
review_parser.add_argument('user', type=long, default=0l)
review_parser.add_argument('site', type=long, default=0l)    # 相关联的 POI id
review_parser.add_argument('city', type=long, default=0l)    # 相关联的城市 id
review_parser.add_argument('country', type=long, default=0l)    # 相关联的国家 id
review_parser.add_argument('token', type=str)     # 用户 token，用于获取是否喜欢的关系，以及是否 关注 了相关用户

review_parser_detail = reqparse.RequestParser()         # 用于创建和更新一个 Review 的信息的参数集合
review_parser_detail.add_argument('id', type=long, default=0l)
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
    'publish_time': util.DateTime,    # RFC3339 格式的时间戳字符串
    'update_time': util.DateTime,    # RFC3339 格式的时间戳字符串
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

def get_info_reviews(review_ids, valid_only = True, brief = False, token = None):
    ''' 辅助函数：提取指定 id 的晒单评论内容详情，并使用缓存。'''
    result = util.get_info_ids(Review, review_ids, format_func = util.format_review, valid_only = valid_only)
    for review in result:
        review.valid_user = util.get_info_user(review.user_id, token = token)
        review.valid_site = util.get_info_site(review.site_id)
        review.valid_at_users = []
        if review.at_list:
            review.valid_at_users = util.get_users(review.at_list)
        if brief:
            review.brief_content = review.content[:80]
            review.valid_images = review.valid_images[:1]
    # 提取 like 关系：
    _format_review_like(result, token)
    return result

def get_info_review(review_id, valid_only = True, brief = False, token = None):
    result = get_info_reviews([review_id], valid_only = valid_only, brief = brief, token = token)
    return None if not result else result[0]

def _format_review_like(reviews, token):
    ''' 辅助函数：用于在 Review 实例中，插入当前 token 对应用户是否喜欢它的信息。'''
    like_dic = {}
    if token:        # ToDo: 这里查询喜欢关系使用的是数据库查询，存在性能风险！
        query = db.session.query(Review.id).filter(Review.valid == True).join(Review.fans).join(Token, User.id == Token.user_id).filter(Token.token == token).filter(Review.id.in_([review.id for review in reviews]))
        for review_id in query:
            like_dic[review_id[0]] = True
    for review in reviews:
        review.liked = like_dic.get(review.id, False)
    return reviews

@cache.memoize()
def get_reviews_id(selected = None, published = False, id=0l, site=0l, city=0l, country=0l, user=0l):
    query = db.session.query(Review.id).filter(Review.valid == True)
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
    if country:
        query = query.join(Review.site).join(Site.area).join(Area.city).filter(City.country_id == country)
        # 在“动态”栏目显示晒单评论的时候，不显示无图片评论：
        query = query.filter(Review.images != '')
    if selected is None:
        # ToDo: 后台需要有个定时任务，将被关注多的 Review 设置成 selected 。
        pass
    else:   # 要求只返回 selected 或者只返回一定没被 selected 的内容时：
        query = query.filter(Review.selected == selected)   # selected 取值为合法 boolean 这一点，由 ReviewList.get 函数调用 get_reviews_id 前负责保证！
    if published:
        query = query.filter(Review.published == True)
    result = map(lambda x: x[0], query.all())
    return result


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
        params = [(selected, published) for selected in (None, False, True) for published in (False, True)]
        id = 0l if not model else model.id
        site_id = 0l if not site else site.id
        city_id = 0l if not site else model.site.area.city.id
        country_id = 0l if not site else model.site.area.city.country.id
        user_id = 0l if not user else user.id
        for selected, published in params:
            if id:
                cache.delete_memoized(get_reviews_id, selected, published, id, 0l, 0l, 0l, 0l)
            if site_id:
                cache.delete_memoized(get_reviews_id, selected, published, 0l, site_id, 0l, 0l, 0l)
            if city_id:
                cache.delete_memoized(get_reviews_id, selected, published, 0l, 0l, city_id, 0l, 0l)
            if country_id:
                cache.delete_memoized(get_reviews_id, selected, published, 0l, 0l, 0l, country_id, 0l)
            if user_id:
                cache.delete_memoized(get_reviews_id, selected, published, 0l, 0l, 0l, 0l, user_id)

    def _count_reviews(self, model):
        ''' 辅助函数，对晒单评论涉及的用户账号和 POI ，重新计算其星级和评论数。并更新各个缓存。'''
        util.update_cache(model, format_func = util.format_review)
        user = model.user
        site = model.site
        util.count_reviews([user] if user else [], [site] if site else [])
        if site:
            util.count_images(site)
        # 清除 Review 详情缓存：
        self._delete_cache(model, site, user)

    @hmac_auth('api')
    def get(self):
        args = review_parser.parse_args()
        brief = args['brief']
        selected = True if args['selected'] else False
        published = True if args['published'] else False
        limit = args['limit']
        if selected:
            # 如果 selected 数量不够，就得用没被 selected 的内容来补。
            result = get_reviews_id(True, published, args['id'], args['site'], args['city'], args['country'], args['user'])
            if limit and len(result) < limit:
                result += get_reviews_id(False, published, args['id'], args['site'], args['city'], args['country'], args['user'])
        else:
            result = get_reviews_id(None, published, args['id'], args['site'], args['city'], args['country'], args['user'])
        offset = args['offset']
        if offset:
            result = result[offset:]
        if limit:
            result = result[:limit]
        result = get_info_reviews(result, valid_only = True, brief = brief, token = args['token'])
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
            return '', 200
        abort(404, message='Target Review do not exists!')

    @hmac_auth('api')
    def post(self):
        ''' 创建新晒单评论的接口。'''
        args = review_parser_detail.parse_args()
        at_list = util.truncate_list(args['at_list'], 200, 20)
        images = util.truncate_list(args['images'], 200, 10)
        keywords = util.truncate_list(args['keywords'], 200, 15)
        keywords = keywords if not keywords or len(keywords) < 200 else keywords[:200]
        user_id = args['user']
        review = Review(valid = True,
                        published = args['published'],
                        update_time = datetime.datetime.now(),
                        create_user_id = user_id,
                        update_user_id = user_id,
                        user_id = user_id,
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
        # 通过用户消息通知被 @ 的用户：
        for at_id in util.get_ids_from_str(at_list):
            util.send_message(user_id, 
                              at_id, 
                              None, 
                              u'我发表了一篇 @ 您的晒单评论，快来看看吧～',
                              {'review': review.id,}
                             )
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
            review.update_user_id = args['user']
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
            self._count_reviews(review)
            review = get_info_review(review.id)
            return marshal(review, review_fields), 200
        abort(404, message='Target Review do not exists!')


api.add_resource(ReviewList, '/rpc/reviews')


# 二级子评论接口：
comment_parser = reqparse.RequestParser()
comment_parser.add_argument('id', type=long, default=0l)
comment_parser.add_argument('offset', type=int, default=0)    # offset 偏移量。
comment_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
comment_parser.add_argument('article', type=long, default=0l)      # 指定推荐文章的 id，获取所有相关子评论
comment_parser.add_argument('review', type=long, default=0l)         # 指定晒单评论 id，获取所有相关子评论

comment_parser_detail = reqparse.RequestParser()         # 用于创建和更新一个 Comment 的信息的参数集合
comment_parser_detail.add_argument('id', type=long, default=0l)
comment_parser_detail.add_argument('review', type=long, required=True)
comment_parser_detail.add_argument('article', type=long, required=True)
comment_parser_detail.add_argument('user', type=long, required=True)
comment_parser_detail.add_argument('at_list', type=str)  # 最多允许@ 20 个用户，更多的可能会被丢掉。
comment_parser_detail.add_argument('content', type=unicode, required=True)

comment_fields = {
    'id': fields.Integer,
    'publish_time': util.DateTime,    # RFC3339 格式的时间戳字符串
    'update_time': util.DateTime,    # RFC3339 格式的时间戳字符串
    'review_id': fields.Integer,        # 绑定的晒单评论 id
    'article_id': fields.Integer,        # 绑定的首页文章 id
    'user': fields.Nested(user_fields_mini, attribute='valid_user'),
    'at_list': fields.List(fields.Nested(user_fields_mini), attribute='valid_at_users'),        # 子评论通常只允许 @ 一个人，但为了界面一致，仍然用列表输出。
    'content': fields.String,   
}

def format_comment(comment):
    ''' 辅助函数：用于格式化 Comment 实例，用于接口输出。'''
    comment.content = (comment.content or u'').strip()
    return comment

def get_info_comments(comment_ids, valid_only = True):
    ''' 辅助函数：提取指定 id 的子评论详细信息，并使用缓存。'''
    result = util.get_info_ids(Comment, comment_ids, format_func = format_comment, valid_only = valid_only)
    for comment in result:
        comment.valid_user = util.get_info_user(comment.user_id)
        comment.valid_at_users = util.get_users(comment.at_list or '')
    return result

def get_info_comment(comment_id, valid_only = True):
    result = get_info_comments([comment_id], valid_only)
    return None if not result else result[0]

@cache.memoize()
def get_comments_id(id=0l, article=0l, review=0l):
    query = db.session.query(Comment.id).filter(Comment.valid == True)
    query = query.order_by(Comment.publish_time.desc())
    if id:
        query = query.filter(Comment.id == id)
    if article:
        query = query.filter(Comment.article_id == article)
    if review:
        query = query.filter(Comment.review_id == review)
    result = map(lambda x: x[0], query.all())
    return result


class CommentList(Resource):
    '''获取某晒单评论的子评论列表，或者进行增、删、改的服务。'''
    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    def _delete_cache(self, model, article, review):
        ''' 辅助函数：尝试覆盖组合参数的主要可能性，清空对应缓存。'''
        id = 0l if not model else model.id
        article_id = 0l if not article else article.id
        review_id = 0l if not review else review.id
        if id:
            cache.delete_memoized(get_comments_id, id, 0l, 0l)
        if article_id:
            cache.delete_memoized(get_comments_id, 0l, article_id, 0l)
        if review_id:
            cache.delete_memoized(get_comments_id, 0l, 0l, review_id)
    
    def _count_comments(self, model):
        ''' 辅助函数，对子评论涉及的首页文章和晒单评论，重新计算其子评论计数。'''
        util.update_cache(model, format_func = format_comment)
        user = model.user
        article = model.article
        review = model.review
        util.count_comments([user] if user else [], [article] if article else [], [review] if review else [])
        # 清除相关数据缓存：
        self._delete_cache(model, article, review)

    @hmac_auth('api')
    @marshal_with(comment_fields)
    def get(self):
        args = comment_parser.parse_args()
        result = get_comments_id(args['id'], args['article'], args['review'])
        offset = args['offset']
        if offset:
            result = result[offset:]
        limit = args['limit']
        if limit:
            result = result[:limit]
        result = get_info_comments(result)
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
            return '', 200
        abort(404, message='Target Comment do not exists!')

    @hmac_auth('api')
    def post(self):
        ''' 创建新的子评论的接口。'''
        args = comment_parser_detail.parse_args()
        at_list = util.truncate_list(args['at_list'], 200, 20)
        user_id = args['user']
        comment = Comment(valid = True,
                          publish_time = datetime.datetime.now(),
                          update_time = datetime.datetime.now(),
                          review_id = args['review'],
                          article_id = args['article'],
                          user_id = user_id,
                          at_list = at_list,
                          content = args['content'],
                         )
        db.session.add(comment)
        db.session.commit()
        self._count_comments(comment)
        # 通过用户消息通知被 @ 的用户：
        for at_id in util.get_ids_from_str(at_list):
            util.send_message(user_id, 
                              at_id, 
                              None, 
                              u'我回复了您的评论，快来看看吧～',
                              {'review': comment.review_id, 'article': comment.article_id, 'comment': comment.id}
                             )
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
            util.update_cache(comment, format_func = format_comment)
            comment = get_info_comment(comment.id)
            return marshal(comment, comment_fields), 200
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
        return '', 200

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
        # 通过用户消息通知关注的用户：
        util.send_message(fan.id, 
                          follow.id, 
                          None, 
                          u'我刚刚关注了您，期待您发布更多有意思的观点哦～',
                          {'user': fan.id,}
                         )
        return '', 201

api.add_resource(FollowList, '/rpc/follows')


# 用户喜欢接口：
like_parser = reqparse.RequestParser()
like_parser.add_argument('offset', type=int, default=0)    # offset 偏移量。
like_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
like_parser.add_argument('user', type=long, default=0l, required=True)
like_parser.add_argument('token', type=str)     # 用户 token，用于获取是否喜欢的关系

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
        util.count_likes([user] if user else [], [review] if review else [])
        self._delete_cache(user)

    @cache.memoize()
    def _get(self, user=0l):
        query = db.session.query(Review.id).filter(Review.valid == True)
        query = query.join(likes, Review.id == likes.columns.review_id)
        query = query.join(User).filter(User.id == likes.columns.user_id)
        query = query.filter(User.id == user)
        query = query.order_by(likes.columns.action_time.desc())
        query = query.filter(Review.published == True)
        result = map(lambda x: x[0], query.all())
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
        result = get_info_reviews(result, brief = True, token = args['token'])
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
        return '', 200

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
        # 通过用户消息通知被喜欢的用户：
        util.send_message(user.id, 
                          review.user_id, 
                          None, 
                          u'我喜欢您发表的晒单评论，期待能看到更多您的有趣观点哦～',
                          {'user': user.id, 'review': review.id,}
                         )
        return '', 201

api.add_resource(LikeList, '/rpc/likes')


# 收藏 POI 接口：
favorite_parser = reqparse.RequestParser()
favorite_parser.add_argument('offset', type=int, default=0)    # offset 偏移量。
favorite_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致。
favorite_parser.add_argument('user', type=long, default=0l)      # 用户 id。

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
        util.count_favorites([user] if user else [], [site] if site else [])
        self._delete_cache(user)

    @cache.memoize()
    def _get(self, user=0l):
        brief = 1
        query = db.session.query(Site.id).filter(Site.valid == True)
        query = query.join(favorites, Site.id == favorites.columns.site_id)
        query = query.join(User).filter(User.id == favorites.columns.user_id)
        query = query.filter(User.id == user)
        query = query.order_by(favorites.columns.action_time.desc())
        result = map(lambda x: x[0], query.all())
        result = util.get_info_sites(result)
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
        return '', 200

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
share_parser.add_argument('offset', type=int, default=0)    # offset 偏移量
share_parser.add_argument('limit', type=int, default=10)     # limit 限制，与 SQL 语句中的 limit 含义一致
share_parser.add_argument('user', type=long, default=0l)      # 分享人用户 id
share_parser.add_argument('token', type=str)      # 当前用户的登陆 token

share_parser_detail = reqparse.RequestParser()
share_parser_detail.add_argument('user', type=long, required=True)    # 进行分享的用户的 id
share_parser_detail.add_argument('site', type=long, required=True)    # 被分享的POI id
share_parser_detail.add_argument('review', type=long, required=True)    # 被分享的晒单评论 id
share_parser_detail.add_argument('article', type=long, required=True)    # 被分享的首页文章 id
share_parser_detail.add_argument('target', type=unicode, required=True)    # 分享的目标应用，如微信、QQ 等

share_fields = {
    'id': fields.Integer,
    'action_time': util.DateTime,    # RFC3339 格式的时间戳字符串
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
        util.count_shares([user] if user else [], [site] if site else [], [review] if review else [], [article] if article else [])
        self._delete_cache(user)

    def _get_info_shares(self, share_ids, token = None):
        ''' 辅助函数：用于格式化 ShareRecord 实例，用于接口输出并缓存。'''
        result = util.get_info_ids(ShareRecord, share_ids)
        for share in result:
            share.url = ''
            share.image = None
            share.title = u''
            share.description = u''
            if share.article_id:    # 其实 article 不怎么变，完全可以放入缓存。。
                valid_article = get_info_article(share.article_id)
                share.valid_article = valid_article
                share.url = baseurl_share + '/articles/' + share.token
                if valid_article != None:
                    share.image = valid_article.caption
                    share.title = valid_article.title
                    content_list = valid_article.formated_content
                    text_list = filter(lambda x: x['class'] == 'text', content_list)
                    share.description = u'' if len(text_list) == 0 else text_list[0]['content']
            elif share.site_id:    # 其实 site 不怎么变，完全可以放入缓存。。
                valid_site = util.get_info_site(share.site_id)
                share.valid_site = valid_site
                share.url = baseurl_share + '/sites/' + share.token
                if valid_site != None:
                    share.image = valid_site.logo_image
                    share.title = valid_site.name
                    share.description = valid_site.description
            elif share.review_id:
                valid_review = get_info_review(share.review_id, brief = True, token = token)
                share.valid_review = valid_review
                share.url = baseurl_share + '/reviews/' + share.token
                if valid_review != None:
                    images = valid_review.valid_images
                    share.image = None if len(images) == 0 else images[0]
                    share.title = valid_review.valid_user.name
                    share.description = valid_review.content
        return result

    def _get_info_share(self, share_id, token = None):
        result = self._get_info_shares([share_id], token = token)
        return None if not result else result[0]

    @cache.memoize()
    def _get(self, user=0l):
        query = db.session.query(ShareRecord).filter(ShareRecord.user_id == user)
        query = query.order_by(ShareRecord.action_time.desc())  # 对同一个 Article，Site，Review，显示其最新的一次共享
        query = db.session.query().add_entity(ShareRecord, alias=query.subquery()).group_by('article_id', 'site_id', 'review_id')         # 让 order_by 比 group_by 更早生效！
        query = query.order_by(desc('action_time'))      # 保证 group 后输出结果的顺序
        result = map(lambda x: x.id, query.all())
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
        result = self._get_info_shares(result, token = args['token'])
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
        share_record = self._get_info_share(share_record.id)
        return marshal(share_record, share_fields), 201

api.add_resource(ShareList, '/rpc/shares')


# ToDo: 应该做一个发全局通知的接口，避免很多不登陆的用户创建大量的用户消息记录（由于每个消息需要保存每个用户的已读、未读记录）。


# 天气预报接口：
forecast_parser = reqparse.RequestParser()         
forecast_parser.add_argument('city', type=long, default=0l, required=True)     # 获取此城市的天气预报信息

datapoint_fields = {
    'time': util.DateTime,    # RFC3339 格式的时间戳字符串
    'weekday': fields.String,   # 对应日期的星期中文缩写
    'temp': fields.Integer,  # 当前温度（摄氏），每日天气数据中没有这一项
    'low': fields.Integer,  # 最低温度（摄氏），当前时刻天气数据中没有这一项
    'high': fields.Integer,     # 最高温度（摄氏），当前时刻天气数据中没有这一项
    'conditions': fields.String,    # 天气情况的中文说明
    'type_name': fields.String,     # 天气类别的英文名称
    'type_id': fields.Integer,  # 天气类别的 id
    'is_night': fields.Boolean,     # 是否是夜晚。每日天气数据中没有这一项
}

forecast_fields = {
    'city': fields.Nested(city_fields),
    'current': fields.Nested(datapoint_fields),     # 当前的实时（其实是每小时）天气情况
    'forecasts': fields.List(fields.Nested(datapoint_fields)),   # 7天的每天天气情况
}


class ForecastList(Resource):
    '''获取指定城市的天气预报信息，含每小时数据和10天的每日数据。'''

    def __repr__(self):
        '''由于 cache.memoize 读取函数参数时，也读取了 self ，因此本类的实例也会被放入 key 的生成过程。
        于是为了函数缓存能够生效，就需要保证 __repr__ 每次提供一个不变的 key。
        '''
        return '%s' % self.__class__.__name__

    def _format_datapoint(self, datapoint, timezone):
        '''将天气信息解析为接口需要输出的格式。'''
        result = {}
        if datapoint.has_key('FCTTIME'):    # hourly
            fcttime = datapoint['FCTTIME'] 
            result['time'] = datetime.datetime(year=int(fcttime['year']),
                                               month=int(fcttime['mon']),
                                               day=int(fcttime['mday']),
                                               hour=int(fcttime['hour']),
                                               minute=int(fcttime['min']),
                                               second=int(fcttime['sec']),
                                              )
            result['weekday'] = fcttime['weekday_name_abbrev']
            result['conditions'] = datapoint['condition']
        elif datapoint.has_key('date'):     # daily
            fcttime = datapoint['date'] 
            result['time'] = datetime.datetime(year=int(fcttime['year']),
                                               month=int(fcttime['month']),
                                               day=int(fcttime['day']),
                                               hour=int(fcttime['hour']),
                                               minute=int(fcttime['min']),
                                               second=int(fcttime['sec']),
                                              )
            result['weekday'] = fcttime['weekday_short']
            result['conditions'] = datapoint['conditions']
        result['time'] = timezone.localize(result['time'])
        result['temp'] = None if not datapoint.has_key('temp') else datapoint['temp']['metric']
        result['low'] = None if not datapoint.has_key('low') else datapoint['low']['celsius']
        result['high'] = None if not datapoint.has_key('high') else datapoint['high']['celsius']
        result['type_name'] = datapoint['icon']
        result['type_id'] = conditions_dic.get(result['type_name'], 0)
        hour = result['time'].hour
        # ToDo: 目前只是简单地把早7点到晚7点之间当做白天，有些时候不够准确。
        result['is_night'] = None if not datapoint.has_key('temp') else hour < 7 or hour >= 19
        return result

    @cache.memoize()
    def _get(self, city_id=0l):
        now = tz_server.localize(datetime.datetime.now())
        city = db.session.query(City).filter(City.valid == True).filter(City.id == city_id).first()
        if city is None:
            abort(404, message='This is not a valid city id!')
        local_tz = '' if not city else city.timezone
        timezone = pytz.timezone(local_tz)
        dt = timezone.normalize(now)
        result = {'city': city}
        forecast = db.session.query(Forecast).filter(Forecast.city_id == city_id).order_by(Forecast.id.desc()).first()
        if forecast:
            data = forecast.data
            dic = json.loads(data)
            hourly_list = dic['hourly_forecast']
            result['current'] = self._format_datapoint(hourly_list[0], timezone)
            for hourly in hourly_list:
                datapoint = self._format_datapoint(hourly, timezone)
                begin_time = datapoint['time']
                if begin_time <= dt and dt <= begin_time + datetime.timedelta(hours=1):
                    result['current'] = datapoint
                    break
            forecasts = []
            for daily in dic['forecast']['simpleforecast']['forecastday']:
                datapoint = self._format_datapoint(daily, timezone)
                begin_time = datapoint['time']
                if begin_time.date() >= dt.date():
                    forecasts.append(datapoint)
                if len(forecasts) >= 7:
                    break
            result['forecasts'] = forecasts
        return result

    @hmac_auth('api')
    @marshal_with(forecast_fields)
    def get(self):
        args = forecast_parser.parse_args()
        city_id = args['city']
        return self._get(city_id)

api.add_resource(ForecastList, '/rpc/forecasts')


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


