# -*- coding: utf-8 -*-

from calendar import timegm
from email.utils import formatdate

import pytz

from flask.ext.restful import fields

from YYMServer import db
from YYMServer.models import *


def get_images(image_ids_str):
    ''' 辅助函数：文本的图片 id 列表转为 Image 对象的列表。'''
    image_ids = ()
    try:
        image_ids = map(int, image_ids_str.split(' '))
    except:
        pass
    images = []
    if image_ids:
        for image_id in image_ids:
            image = db.session.query(Image).get(image_id)
            images.append(image)
    return images


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


