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

# 建议设定的 cron 执行时间为每分钟执行一次：
# 0-59/1 * * * *
if __name__ == '__main__':
    message.check_msg_queue()



