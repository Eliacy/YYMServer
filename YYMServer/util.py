# -*- coding: utf-8 -*-

import re
from calendar import timegm
from email.utils import formatdate
import os.path

import PIL
import pytz

import flask
from flask.ext.admin import form as admin_form
from flask.ext.restful import fields

import qiniu.rs
import qiniu.io

from YYMServer import db, cache, qiniu_bucket, qiniu_callback
from YYMServer.models import *


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

def format_site(site, brief=True):
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
    if not brief:
        site.valid_gate_images = []
        if site.gate_images:
            site.valid_gate_images = get_images(site.gate_images)
        site.valid_gate_images = site.valid_gate_images[:1]
        site.valid_categories = [category.name for category in site.categories if category.parent_id != None]
    return site

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
                entry = {'class': 'image', 'content': db.session.query(Image).filter(Image.valid == True).filter(Image.id == int(id)).first()}
            elif type == 'site' and id.isdigit():  # POI
                entry = {'class': 'site', 'content': format_site(db.session.query(Site).filter(Site.valid == True).filter(Site.id == int(id)).first())}
        elif line.strip() == u'***':        # 水平分隔线
            entry = {'class': 'hline', 'content': ''}
        if entry == None:       # 普通文本
            entry = {'class': 'text', 'content': line}
        output.append(entry)
    return output

def extend_image_path(path):
    ''' 辅助函数：对给定的图片资源，扩展为外网可访问的完整路径（未处理云存储私有授权问题）。'''
    if path.startswith('qiniu:'):
        etag, params = (path[6:].split('?') + [''])[:2]
        url = qiniu.rs.make_base_url('youyoumm.qiniudn.com', etag)
        if params:
            return url + '?' + params
        return url
    else:
        return flask.url_for('static', filename=path, _external=True)

def url_for(path):
    ''' 辅助函数：对给定图片资源，扩展为经过访问授权的外网完整路径。'''
    base_url = extend_image_path(path)
    if path.startswith('qiniu:'):
        policy = qiniu.rs.GetPolicy()
        return policy.make_request(base_url)
    return base_url

def url_for_thumb(path):
    ''' 辅助函数：对给定图片资源，生成经过访问授权的外网缩略图。'''
    if path.startswith('qiniu:'):
        return url_for(path + '?imageView2/2/w/100')
    else:
        return url_for(admin_form.thumbgen_filename(path))

def gen_upload_token(callback_dic):
    ''' 辅助函数：面向 callback 上传图片场景生成七牛 token。'''
    policy = qiniu.rs.PutPolicy(qiniu_bucket)
    policy.callbackUrl = qiniu_callback
    policy.callbackBody = '&'.join(('='.join((key, value)) for key, value in callback_dic.items()))
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

def get_users(user_ids_str):
    ''' 辅助函数：文本的用户 id 列表转为 User 对象的列表。'''
    user_ids = ()
    user_ids_str = user_ids_str.strip()
    try:
        user_ids = map(int, user_ids_str.split())
    except:
        pass
    users = []
    if user_ids:
        valid_users = db.session.query(User).filter(User.valid == True).filter(User.id.in_(user_ids)).all()
        for user in valid_users:
            if user:
                user.icon_image = user.icon      # 为了缓存存储 User 对象时，icon 子对象仍然能够被读取。
                users.append(user)
    return users

def get_site_images(site_id):
    '''辅助函数：提取指定 site 的所有图片（产品图及所有评论里的图）。'''
    related_reviews = db.session.query(Review).filter(Review.valid == True).filter(Review.published == True).join(Review.site).filter(Site.id == site_id).order_by(Review.selected.desc()).order_by(Review.publish_time.desc()).all()
    # ToDo: 这里完全没有控制图片的排列顺序！
    image_ids_str = ' '.join((review.images or '' for review in related_reviews))
    related_site = db.session.query(Site).filter(Site.valid == True).filter(Site.id == site_id).first()
    if related_site:
        image_ids_str = (related_site.gate_images or '') + ' ' + (related_site.top_images or '') + ' ' + image_ids_str
    image_ids = ()
    try:
        image_ids = map(int, set(image_ids_str.strip().split()))
    except:
        pass
    return list(image_ids)

def get_images(image_ids, valid_only=True):
    ''' 辅助函数：文本的图片 id 列表转为 Image 对象的列表。'''
    if type(image_ids) != list:
        image_ids_str = image_ids
        image_ids = ()
        try:
            image_ids = map(int, image_ids_str.strip().split())
        except:
            pass
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

tz_cn = pytz.timezone('Asia/Shanghai')

class DateTime(fields.DateTime):
    """Return a RFC822-formatted datetime string in UTC"""

    def format(self, value):
        """数据库默认认为以 'Asia/Shanghai' 时区存储，在输出时做转换。"""
        try:
            dt = tz_cn.localize(value)
            return formatdate(timegm(dt.utctimetuple()))
        except AttributeError as ae:
            raise fields.MarshallingException(ae)

def diff_list(old, new):
    ''' 辅助函数，给出两个列表内容不同的部分，通常用于比较数据库 Instance 具体字段更新前后的变化（不保证原始数据顺序）。'''
    old_set = set(old)
    new_set = set(new)
    return list(old_set - new_set) + list(new_set - old_set)

def count_follow_fans(follows, fans):
    ''' 辅助函数，对交互行为涉及的用户账号，重新计算其 follow_num 和 fans_num 。'''
    # ToDo: 这个实现受读取 User 信息的接口的缓存影响，还不能保证把有效的值传递给前端。
    for follow in follows:
        follow.fans_num = follow.fans.filter(User.valid == True).count()
    for fan in fans:
        fan.follow_num = fan.follows.filter(User.valid == True).count()
    db.session.commit()

def count_likes(users, reviews):
    ''' 辅助函数，对喜欢行为涉及的用户账号和晒单评论，重新计算其 like_num 。'''
    # ToDo: 这个实现受读取 User 信息和 Review 信息的接口的缓存影响，还不能保证把有效的值传递给前端。
    for user in users:
        user.like_num = user.likes.filter(Review.valid == True).count()
    for review in reviews:
        review.like_num = review.fans.filter(User.valid == True).count()
    db.session.commit()

def count_favorites(users, sites):
    ''' 辅助函数，对收藏行为涉及的用户账号和 POI ，重新计算其 favorite_num 。'''
    # ToDo: 这个实现受读取 User 信息和 Site 信息的接口的缓存影响，还不能保证把有效的值传递给前端。
    for user in users:
        user.favorite_num = user.favorites.filter(Site.valid == True).count()
    # Site 暂时没有与 favorite 相关的计数
    db.session.commit()

def count_images(site):
    ''' 辅助函数，重新计算指定 POI 的 image_num 。'''
    # ToDo: 这个实现受读取 site 信息的接口的缓存影响，还不能保证把有效的值传递给前端。
    site.images_num = len(get_site_images(site.id))
    db.session.commit()

def count_reviews(users, sites):
    ''' 辅助函数，对晒单评论的更新，重新计算相关 POI 的星级、评论数，以及相关用户账号的评论数。'''
    # ToDo: 这样每次都重新计算不确定是否存在性能风险。
    for user in users:
        user.review_num = user.reviews.filter(Review.valid == True).count()
    for site in sites:
        reviews = site.reviews.filter(Review.valid == True).all()
        if reviews:
            review_num = len(reviews)
            site.stars = sum([review.stars for review in reviews]) / review_num   # 假定用户发晒单评论时，星级必须填！
            site.review_num = review_num
    db.session.commit()

def count_comments(users, articles, reviews):
    ''' 辅助函数，对子评论涉及的晒单评论、首页文章、用户账号（用户账号暂时不需要），重新计算其子评论数。'''
    # ToDo: 这样每次都重新计算不确定是否存在性能风险。
    for article in articles:
        article.comment_num = article.comments.filter(Comment.valid == True).count()
    for review in reviews:
        review.comment_num = review.comments.filter(Comment.valid == True).count()
    db.session.commit()


