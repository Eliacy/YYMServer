#!/usr/bin/python
# -*- coding: utf-8 -*-

import sys

# 以下路径通常需要根据服务器实际路径修改：
# 用于 virtualenv 的：
sys.path.insert(0, '/var/www/youyoumm/lib/python2.7/site-packages')
# 用于载入 Application 自身的：
sys.path.insert(0, '/var/www/youyoumm/YYMServer/flask-hmacauth')
sys.path.insert(0, '/var/www/youyoumm/YYMServer')

from YYMServer import message

# 建议设定的 cron 执行时间为每天执行一次（随着每日的备份脚本被执行）：
# 47 2 * * *
if __name__ == '__main__':
    # 应当在服务器上复制本文件，修改下面的备份数据存储路径后使用：
    message.export_messages('/root/_backup/messages')


