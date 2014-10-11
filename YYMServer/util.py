# -*- coding: utf-8 -*-

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


