# -*- coding: utf-8 -*-

from calendar import timegm
from email.utils import formatdate

import pytz

from flask.ext.restful import fields

from YYMServer import db
from YYMServer.models import *


def get_users(user_ids_str):
    ''' 辅助函数：文本的用户 id 列表转为 User 对象的列表。'''
    user_ids = ()
    try:
        user_ids = map(int, user_ids_str.split(' '))
    except:
        pass
    users = []
    if user_ids:
        for user_id in user_ids:
            user = db.session.query(User).get(user_id)
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
        for image_id in image_ids:
            image = db.session.query(Image).get(image_id)
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


