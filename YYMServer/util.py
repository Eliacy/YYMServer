# -*- coding: utf-8 -*-

import json
import math
import random
import re
from calendar import timegm
import os.path

import PIL
import pytz
from rfc3339 import rfc3339
from sqlalchemy.orm import aliased

import flask
from flask.ext.admin import form as admin_form
from flask.ext.restful import fields

import qiniu.rs
import qiniu.io

from YYMServer import db, cache, qiniu_bucket, qiniu_callback, tz_server
from YYMServer.models import *


def get_distance(long1, lat1, long2, lat2):
    ''' 根据经纬度计算距离，代码来自：http://www.johndcook.com/blog/python_longitude_latitude/ 。'''
 
    # Convert latitude and longitude to
    # spherical coordinates in radians.
    degrees_to_radians = math.pi / 180.0
         
    # phi = 90 - latitude
    phi1 = (90.0 - lat1) * degrees_to_radians
    phi2 = (90.0 - lat2) * degrees_to_radians
         
    # theta = longitude
    theta1 = long1 * degrees_to_radians
    theta2 = long2 * degrees_to_radians
         
    # Compute spherical distance from spherical coordinates.
         
    # For two locations in spherical coordinates
    # (1, theta, phi) and (1, theta, phi)
    # cosine( arc length ) =
    #    sin phi sin phi' cos(theta-theta') + cos phi cos phi'
    # distance = rho * arc length
     
    cos = (math.sin(phi1) * math.sin(phi2) * math.cos(theta1 - theta2) + math.cos(phi1) * math.cos(phi2))
    arc = math.acos(cos)
 
    # Remember to multiply arc by the radius of the earth
    # in your favorite set of units to get length.
    return arc * 6378.1     # 后者是地球半径（单位是公里）

# @cache.memoize()    # 本应对常用的批量对象格式化结果进行缓存，避免对缓存服务进行频繁读取。但具体数据内容变化（例如评论数）时，无法自动更新这一级缓存，因而放弃。
def get_info_ids(model_class, ids, format_func = None, valid_only = True):
    ''' 根据输入的 id，从缓存中获取对应 model 实例的详情信息。'''
    key_template = 'one_' + model_class.__tablename__ + '_%d'
    has_valid_column = True if model_class.__tablename__ + '.valid' in model_class.__table__.columns else False
    cached_result = []
    uncached_ids = []
    for id in ids:
        id = id or 0
        key = key_template % id
        obj = cache.get(key)
        if obj:
            if valid_only and has_valid_column and not obj.valid:
                continue
            cached_result.append(obj)
        else:
            cached_result.append(id)
            uncached_ids.append(id)
    tmp_dic = {}
    if uncached_ids:
        query = db.session.query(model_class).filter(model_class.id.in_(uncached_ids))
        if valid_only and has_valid_column:
            query = query.filter(model_class.valid == True)
        for obj in query.all():
            if format_func != None:
                obj = format_func(obj)
            key = key_template % obj.id
            cache.set(key, obj)
            tmp_dic[obj.id] = obj
    result = []
    for item in cached_result:
        if isinstance(item, model_class):
            result.append(item)
            continue
        if tmp_dic.has_key(item):
            result.append(tmp_dic[item])
    return result

def update_cache(model, format_func = None):
    ''' 将单个 model 实例放入缓存。通常用于 post 和 put 操作数据的保存。'''
    model_class = model.__class__
    key_template = 'one_' + model_class.__tablename__ + '_%d'
    key = key_template % model.id
    if format_func != None:
        model = format_func(model)
    cache.set(key, model)

textlib_re = re.compile(r'(\{\{text:\d+(|#.*?)\}\})')

@cache.memoize()
def _get_textlib(textlib_id):
    textlib_item = db.session.query(TextLib).filter(TextLib.id == textlib_id).first()
    return textlib_item

def _replace_textlib(textlib_match):
    ''' 私有辅助函数，对匹配得到的 textlib 标记，查库完成替换。'''
    textlib_pattern = textlib_match.group()
    try:
        text_id = int(textlib_pattern.strip('{}').split(':')[1].split('#')[0])
        textlib_item = _get_textlib(text_id)
        if textlib_item:
            return textlib_item.content.strip()
    except Exception, e:
        pass
    return textlib_pattern

def replace_textlib(text):
    ''' 辅助函数：检查输入的 text 数据是否匹配 TextLib 替换代码，如果是则替换后返回。'''
    return textlib_re.sub(_replace_textlib, text)

default_user_icon = db.session.query(Image).filter(Image.id == 9).first()

def format_user(user):
    ''' 辅助函数：用于格式化 User 实例，用于接口输出。'''
    user.formated_badges = () if not user.badges else user.badges.strip().split()
    user.icon_image = user.icon
    if not user.icon_id:
        user.icon_image = default_user_icon
    return user

def format_site(site):
    ''' 为了 API 输出及缓存需要，对原始 Site object 的数据格式进行调整。'''
    if site == None:
        return None
    site.stars = site.stars or 0.0      # POI 无星级时输出0，表示暂无评分。
    site.environment = site.environment or u''
    site.formated_payment_types = [] if not site.payment else [payment_types.get(code.lower(), code) for code in site.payment.split()]
    site.menu = site.menu or u''
    site.formated_ticket = u'' if not site.ticket else replace_textlib(site.ticket).strip()
    site.booking = (site.booking or u'').strip()
    site.formated_business_hours = u'' if not site.business_hours else replace_textlib(site.business_hours).strip()
    site.phone = (site.phone or u'').strip()
    site.transport = (site.transport or u'').strip()
    site.description = (site.description or u'').strip()
    site.address = (site.address or u'').strip()
    site.address_orig = (site.address_orig or u'').strip()
    site.logo_image = site.logo         # 为了缓存能工作
    site.city_name = '' if not site.area else site.area.city.name
    site.formated_keywords = [] if not site.keywords else site.keywords.translate({ord('{'):None, ord('}'):None}).split()
    site.valid_top_images = []
    if site.top_images:
        site.valid_top_images = get_images(site.top_images)
    site.valid_top_images = site.valid_top_images[:5]
    # 永远按照详情页的需要格式化 site 信息：
    site.valid_gate_images = []
    if site.gate_images:
        site.valid_gate_images = get_images(site.gate_images)
    site.valid_gate_images = site.valid_gate_images[:1]
    site.valid_categories = [category.name for category in site.categories if category.parent_id != None]
    return site

def get_info_sites(site_ids):
    ''' 根据输入的 POI id，从缓存中获取对应的详情信息。'''
    return get_info_ids(Site, site_ids, format_func = format_site)

def get_info_site(site_id):
    result = get_info_sites([site_id])
    return None if not result else result[0]

def get_info_users(user_ids, valid_only = True, token = None):
    ''' 辅助函数：提取指定 id 的用户属性详情，并使用缓存。'''
    result = get_info_ids(User, user_ids, format_func = format_user, valid_only = valid_only)
    # 补充与当前用户间的关注关系：
    if token:        # ToDo: 这里查询关注关系使用的是数据库查询，存在性能风险！
        Main_User = aliased(User)
        query = db.session.query(User.id).filter(User.valid == True).join(fans, User.id == fans.columns.user_id).join(Main_User, fans.columns.fan_id == Main_User.id).join(Token, Main_User.id == Token.user_id).filter(Token.token == token).filter(User.id.in_([user.id for user in result]))
        follow_dic = {}
        for user_id in query:
            follow_dic[user_id[0]] = True
        for user in result:
            user.followed = follow_dic.get(user.id, False)
    return result

def get_info_user(user_id, valid_only = True, token = None):
    ''' 与 get_info_users 的区别是只接收和返回单个的数据实例。'''
    result = get_info_users([user_id], valid_only, token = token)
    return None if not result else result[0]

def get_info_announce(announce_id, valid_only = True):
    ''' 辅助函数：提取指定 id 的用户通知，并使用缓存。'''
    result = get_info_ids(Announce, [announce_id], format_func = None, valid_only = valid_only)
    return None if not result else result[0]

def format_review(review):
    ''' 辅助函数：用于格式化 Review 实例，用于接口输出。本函数对内嵌数据（如 user、site ）的支持并不完整，需要用 _get_info_reviews 函数获取完整的内嵌属性。'''
    review.currency = review.currency or u'人民币'
    review.content = (review.content or u'').strip()
    review.formated_keywords = [] if not review.keywords else review.keywords.split()
    review.valid_images = []
    if review.images:
        review.valid_images = get_images(review.images)    # 图片一般不会保留同一个 id 但修改图片内容，因而无需单独缓存
    else:           # 如果 review 无图，则从对应的 site 的 gate_images 中随机取一个。
        if review.site_id:
            site = get_info_site(review.site_id)
            if site.valid_gate_images:
                review.valid_images = [random.choice(site.valid_gate_images)]
    review.images_num = len(review.valid_images)
    return review

def format_article(article):
    article.caption_image = article.caption
    article.formated_keywords = [] if not article.keywords else article.keywords.strip().split()
    article.formated_content = parse_textstyle(replace_textlib(article.content))
    return article

def parse_textstyle(content):
    ''' 辅助函数：解析富媒体长文本，由类 Wiki 标记转化为结构化的数据结构。'''
    content = (content or '').strip()
    output = []
    for line in content.splitlines():
        line = line.strip()
        if line == '':
            continue
        entry = None
        if line.startswith(u'#'):   # 小标题
            title = line.lstrip('#').strip()
            entry = {'class': 'title', 'content': title}
        elif line.startswith(u'[[') and line.endswith(u']]') and line.find(u':') >= 0:
            link = line.lstrip('[').rstrip(']')
            type, id = link.split(u':', 1)
            id = id.strip()
            if type == 'image' and id.isdigit():   # 图片
                entry = {'class': 'image', 'content': db.session.query(Image).filter(Image.valid == True).filter(Image.id == long(id)).first()}
            elif type == 'site' and id.isdigit():  # POI
                # 这里对 POI 其实直接解析完就把具体信息丢进缓存了，因而不会被实时更新。
                entry = {'class': 'site', 'content': get_info_site(long(id))}
        elif line.strip() == u'***':        # 水平分隔线
            entry = {'class': 'hline', 'content': ''}
        if entry == None:       # 普通文本
            entry = {'class': 'text', 'content': line}
        output.append(entry)
    return output

def extend_image_path(path):
    ''' 辅助函数：对给定的图片资源，扩展为外网可访问的完整路径（未处理云存储私有授权问题）。'''
    path = path or ''
    if path.startswith('qiniu:'):
        etag, params = (path[6:].split('?') + [''])[:2]
        url = qiniu.rs.make_base_url('7qn83g.com1.z0.glb.clouddn.com', etag)
        if params:
            return url + '?' + params
        return url
    else:
        return flask.url_for('static', filename=path, _external=True)

def url_for(path):
    ''' 辅助函数：对给定图片资源，扩展为经过访问授权的外网完整路径。'''
    path = path or ''
    base_url = extend_image_path(path)
    if path.startswith('qiniu:'):
        policy = qiniu.rs.GetPolicy()
        return policy.make_request(base_url)
    return base_url

def url_for_thumb(path):
    ''' 辅助函数：对给定图片资源，生成经过访问授权的外网缩略图。'''
    path = path or ''
    if path.startswith('qiniu:'):
        return url_for(path + '?imageView2/2/w/100')
    else:
        return url_for(admin_form.thumbgen_filename(path))

def gen_upload_token(callback_dic):
    ''' 辅助函数：面向 callback 上传图片场景生成七牛 token。'''
    policy = qiniu.rs.PutPolicy(qiniu_bucket)
    policy.callbackUrl = qiniu_callback
    policy.callbackBody = '&'.join(('='.join((key, value if type(value) in (unicode, str) else unicode(value))) for key, value in callback_dic.items()))
    return policy.token()

def get_image_size(file_path):
    ''' 辅助函数：获取指定图片文件的长、宽参数。'''
    # 有时会丢无效的空路径进来：
    if os.path.exists(file_path) and os.path.isfile(file_path):
        im = PIL.Image.open(file_path)
        return im.size
    else:
        return None

def upload_image(file_path, id, type, user, note, name):
    ''' 辅助函数：上传文件到七牛云存储。'''
    # 优先使用本地计算的图片宽、长。因为有时七牛无法计算出一些图片的长宽数值：
    width = '$(imageInfo.width)'
    height = '$(imageInfo.height)'
    size = get_image_size(file_path)
    if size:
        width, height = map(str, size)
    callback_dic = {
      'id': str(id),
      'type': str(type),
      'user': str(user),
      'note': note or u'',
      'name': name or u'',   # 原始文件名这个不靠谱，最好自己存
      'size': '$(fsize)',
      'mime': '$(mimeType)',
      'width': width,
      'height': height,
      'hash': '$(etag)',
    }
    uptoken = gen_upload_token(callback_dic)
    ret, err = qiniu.io.put_file(uptoken, None, file_path)
    return (ret, err)

def truncate_list(text, max_str_length, max_item_length):
    ''' 辅助函数：检查 text 参数是否超出 max_str_length 个字符，如果超出则截断为只包含 max_item_length 个元素。'''
    if text:
        if text > max_str_length:
            text = ' '.join(text.split()[:max_item_length])
    return text

def get_self_and_children(model_class, self_id):
    ''' 辅助函数：对指定 id 的数据，获取其自身及所有层级的子节点的 id 。'''
    entries = [self_id]
    for entry in db.session.query(model_class.id).filter(model_class.parent_id == self_id).all():
        entry_id = entry[0]
        sub_entries = get_self_and_children(model_class, entry_id)
        entries.extend(sub_entries)
    return entries

def get_ids_from_str(ids_str):
    ''' 辅助函数：文本的用户 id 列表转为 long 类型的列表。'''
    ids = ()
    try:
        ids_str = ids_str.strip()
        ids = map(long, ids_str.split())
    except:
        pass
    return ids

def get_users(user_ids_str):
    ''' 辅助函数：文本的用户 id 列表转为 User 对象的列表。'''
    user_ids = get_ids_from_str(user_ids_str)
    return get_info_users(user_ids)

def get_site_images(site_id):
    '''辅助函数：提取指定 site 的所有图片（产品图及所有评论里的图）。'''
    related_reviews = db.session.query(Review).filter(Review.valid == True).filter(Review.published == True).join(Review.site).filter(Site.id == site_id).order_by(Review.selected.desc()).order_by(Review.publish_time.desc()).all()
    # ToDo: 这里完全没有控制图片的排列顺序！
    image_ids_str = ' '.join((review.images or '' for review in related_reviews))
    related_site = db.session.query(Site).filter(Site.valid == True).filter(Site.id == site_id).first()
    if related_site:
        image_ids_str = (related_site.gate_images or '') + ' ' + (related_site.top_images or '') + ' ' + image_ids_str
    image_ids = set(get_ids_from_str(image_ids_str))
    return list(image_ids)

def get_images(image_ids, valid_only=True):
    ''' 辅助函数：文本的图片 id 列表转为 Image 对象的列表。'''
    if type(image_ids) != list:
        image_ids_str = image_ids
        image_ids = get_ids_from_str(image_ids_str)
    images = []
    if image_ids:
        valid_images = db.session.query(Image).filter(Image.valid == True).filter(Image.id.in_(image_ids)).all()
        valid_images_dic = dict(((image.id, image) for image in valid_images))
        for image_id in image_ids:
            image = valid_images_dic.get(image_id, None)
            if valid_only:
                if image:
                    images.append(image)
            else:
                if not image:
                    image = Image(id=image_id, path='')
                images.append(image)
    return images

def strip_image_note(note):
    ''' 辅助函数：去掉图片备注文字中的自动生成部分，输入正常的用户备注。'''
    note = note or u''
    if ('[' not in note) or (']' not in note):
        return note
    leading = u''
    if '[' in note:
        leading = note.split('[')[0]
    ending = u''
    if ']' in note:
        ending = note.split(']')[-1]
    return leading + ending

def send_message(sender_user_id=None, receiver_user_id=None, announce_id=None, content=u'', ext={}):
    ''' 封装发送环信消息的功能，使调用者与 model 的修改分离。'''
    message = Message(sender_user_id = sender_user_id,
                      receiver_user_id = receiver_user_id,
                      announce_id = announce_id,
                      content = content,
                      ext = json.dumps(ext),    # 这里有可能造成中文字符编码问题
                     )
    db.session.add(message)
    db.session.commit()


class DateTime(fields.DateTime):
    '''格式化时间戳为 RFC3339 格式字符串。'''

    def format(self, value):
        '''数据库默认认为以 'Asia/Shanghai' 时区存储，在输出时做转换。'''
        try:
            dt = value if value.tzinfo != None else tz_server.localize(value)
            return rfc3339(dt)
        except AttributeError as ae:
            raise fields.MarshallingException(ae)

def diff_list(old, new):
    ''' 辅助函数，给出两个列表内容不同的部分，通常用于比较数据库 Instance 具体字段更新前后的变化（不保证原始数据顺序）。'''
    old_set = set(old)
    new_set = set(new)
    return list(old_set - new_set) + list(new_set - old_set)

def diff_list_added(old, new):
    ''' 辅助函数，给出列表 new 比列表 old 新增的部分，通常用于比较数据库 Instance 具体字段更新前后的变化（不保证原始数据顺序）。'''
    old_set = set(old)
    new_set = set(new)
    return list(new_set - old_set)

def count_follow_fans(follows, fans):
    ''' 辅助函数，对交互行为涉及的用户账号，重新计算其 follow_num 和 fans_num 。'''
    for follow in follows:
        follow.fans_num = follow.fans.filter(User.valid == True).count()
        db.session.commit()
        update_cache(follow, format_func = format_user)
    for fan in fans:
        fan.follow_num = fan.follows.filter(User.valid == True).count()
        db.session.commit()
        update_cache(fan, format_func = format_user)

def count_likes(users, reviews):
    ''' 辅助函数，对喜欢行为涉及的用户账号和晒单评论，重新计算其 like_num 。'''
    for user in users:
        user.like_num = user.likes.filter(Review.valid == True).count()
        db.session.commit()
        update_cache(user, format_func = format_user)
    for review in reviews:
        review.like_num = review.fans.filter(User.valid == True).count()
        db.session.commit()
        update_cache(review, format_func = format_review)

def count_favorites(users, sites):
    ''' 辅助函数，对收藏行为涉及的用户账号和 POI ，重新计算其 favorite_num 。'''
    for user in users:
        user.favorite_num = user.favorites.filter(Site.valid == True).count()
    # Site 暂时没有与 favorite 相关的计数
        db.session.commit()
        update_cache(user, format_func = format_user)

def count_shares(users, sites, reviews, articles):
    ''' 辅助函数，对共享行为涉及的用户账号、 POI 、晒单评论、和首页文章，重新计算其 share_num 。'''
    for user in users:
        user.share_num = user.share_records.join(ShareRecord.site).filter(Site.valid == True).group_by('site_id').count() + \
                         user.share_records.join(ShareRecord.review).filter(Review.valid == True).group_by('review_id').count() + \
                         user.share_records.join(ShareRecord.article).filter(Article.valid == True).group_by('article_id').count()
        db.session.commit()
        update_cache(user, format_func = format_user)
    # Site 暂时没有与 site, review, article 相关的计数

def count_images(site):
    ''' 辅助函数，重新计算指定 POI 的 image_num 。'''
    site.images_num = len(get_site_images(site.id))
    db.session.commit()
    update_cache(site, format_func = format_site)

def count_reviews(users, sites):
    ''' 辅助函数，对晒单评论的更新，重新计算相关 POI 的星级、评论数，以及相关用户账号的评论数。'''
    for user in users:
        user.review_num = user.reviews.filter(Review.valid == True).count()
        db.session.commit()
        update_cache(user, format_func = format_user)
    for site in sites:
        reviews = site.reviews.filter(Review.valid == True).all()
        if reviews:
            review_num = len(reviews)
            site.stars = sum([review.stars for review in reviews]) / review_num   # 假定用户发晒单评论时，星级必须填！
            site.review_num = review_num
        db.session.commit()
        update_cache(site, format_func = format_site)

def count_comments(users, articles, reviews):
    ''' 辅助函数，对子评论涉及的晒单评论、首页文章、用户账号（用户账号暂时不需要），重新计算其子评论数。'''
    for article in articles:
        article.comment_num = article.comments.filter(Comment.valid == True).count()
        db.session.commit()
        update_cache(article, format_func = format_article)
    for review in reviews:
        review.comment_num = review.comments.filter(Comment.valid == True).count()
        db.session.commit()
        update_cache(review, format_func = format_review)


