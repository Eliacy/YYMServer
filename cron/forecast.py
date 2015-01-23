#!/usr/bin/python
# -*- coding: utf-8 -*-

import sys

# 以下路径通常需要根据服务器实际路径修改：
# 用于 virtualenv 的：
sys.path.insert(0, '/var/www/youyoumm/lib/python2.7/site-packages')
# 用于载入 Application 自身的：
sys.path.insert(0, '/var/www/youyoumm/YYMServer/flask-hmacauth')
sys.path.insert(0, '/var/www/youyoumm/YYMServer')

from YYMServer import forecast

# 建议设定的 cron 执行时间为每小时的第 7 分钟左右：
# 7 * * * *
if __name__ == '__main__':
    forecast.check_update()
    forecast.export_forecasts('/root/_backup/forecasts')


