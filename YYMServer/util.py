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
            return textlib_item.content
    except Exception, e:
        pass
    return textlib_pattern

def replace_textlib(text):
    ''' 辅助函数：检查输入的 text 数据是否匹配 TextLib 替换代码，如果是则替换后返回。'''
    return textlib_re.sub(_replace_textlib, text)

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

def get_images(image_ids_str, valid_only=True):
    ''' 辅助函数：文本的图片 id 列表转为 Image 对象的列表。'''
    image_ids = ()
    image_ids_str = image_ids_str.strip()
    try:
        image_ids = map(int, image_ids_str.split())
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


