# -*- coding: utf-8 -*-

import sys
import os.path

import requests

from YYMServer import db, util
from YYMServer.models import Image

storage_dir = os.path.split(os.path.realpath(__file__))[0]
logging_path = os.path.join(os.path.split(os.path.realpath(__file__))[0], 'downloader.log')
default_encoding = sys.stdin.encoding

def download(storage_dir=storage_dir, logging_path=logging_path):
    all_synced = True
    largest_success_id = 0
    # 读取上一次的处理进度
    record_path = logging_path + '.record'
    try:
        with open(record_path, 'r') as record:
            line = record.readline()
            largest_success_id = long(line.strip())
    except:
        pass

    # 准备日志：
    import logging
    logger = logging.getLogger('YYMServer.downloader')
    hdlr = logging.FileHandler(logging_path, encoding=default_encoding)
    formatter = logging.Formatter(u'%(asctime)s | %(levelname)s | %(message)s')
    hdlr.setFormatter(formatter)
    logger.addHandler(hdlr) 
    logger.setLevel(logging.INFO)

    for image in db.session.query(Image).filter(Image.id > largest_success_id).order_by(Image.id):
        path = image.path
        if not path.lower().startswith('qiniu:'):
            all_synced = False
            print 'x', image.id, 'not synced to qiniu'
            logger.error(unicode(image.id) + u':' + unicode(path.replace(':', '~')) + u':' + unicode(image.size) + u':' + u'not in qiniu')
            continue

        filename = path[6:]
        storage_path = os.path.join(storage_dir, filename)
        # 如果目标文件和本地文件大小一致，就不重新下载了：
        if os.path.exists(storage_path):
            real_size = os.path.getsize(storage_path)
            if image.size == real_size:
                if all_synced:  # 只有至少经过一次本地文件比对通过之后，才认为备份是有效的，下次可以跳过！
                    largest_success_id = image.id
                continue
        all_synced = False
        # 没下载过的开始下载：
        try:
            url = util.url_for(image.path)
            r = requests.get(url) 
            if r.status_code != 200:
                raise Exception(unicode(r))
            with open(storage_path, "wb") as code:
                 code.write(r.content)
            real_size = os.path.getsize(storage_path)
            print '*', image.id, 'downloaded'
            logger.info(unicode(image.id) + u':' + unicode(filename) + u':' + unicode(image.size) + u':' + unicode(real_size))
        except Exception, e:
            print 'x', image.id, 'error'
            logger.error(unicode(image.id) + u':' + unicode(filename) + u':' + unicode(image.size) + u':' + unicode(e))

    # 记录连续下载成功的最大 Image id，下次备份时从那个最大 id 开始扫描就行了。
    with open(record_path, 'w') as record:
        record.write(str(largest_success_id))


