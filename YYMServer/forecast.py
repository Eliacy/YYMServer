# -*- coding: utf-8 -*-

import datetime
import json
import time

import pytz
import requests

from YYMServer import app, db
from YYMServer.models import City, Forecast

wu_key = app.config['WEATHER_KEY_WU']

def check_update():
    ''' 本脚本需要每小时定时执行，以便保证数据库中的天气数据能够得到及时更新。'''
    tz_cn = pytz.timezone('Asia/Shanghai')
    now = tz_cn.localize(datetime.datetime.now())
    today = now.date()
    for city in db.session.query(City).all():
        if city.timezone:
            timezone = pytz.timezone(city.timezone)
            dt = timezone.normalize(now)
            if dt.hour < 5 or dt.hour > 17:     # 只在当地时间 5点～17点之间更新数据
                continue
            # 检查是否已经抓取过“今天”的数据：
            forecast = db.session.query(Forecast).filter(Forecast.city_id == city.id).order_by(Forecast.id.desc()).first()
            if forecast:
                previous_fetch = timezone.normalize(tz_cn.localize(forecast.update_time))
                if previous_fetch.date() == dt.date():
                    continue
        # timezone 为空或者通过时间点及数据是否已存在检查时，连网抓取天气预报数据：
        if not city.longitude or not city.latitude:
            continue
        api_url = 'http://api.wunderground.com/api/%s/forecast10day/lang:CN/q/%f,%f.json' % (wu_key, city.latitude, city.longitude)
        try:
            resp = requests.get(api_url)
            resp.encoding = 'utf-8'
            if resp.status_code != 200:
                continue
            forecast = Forecast(city_id = city.id,
                                data = resp.text,
                               )
            db.session.add(forecast)
            db.session.commit()
            if not city.timezone:
                resp_dic = json.loads(resp.text)
                city.timezone = resp_dic['forecast']['simpleforecast']['forecastday'][0]['date']['tz_long']
                db.session.commit()
        except Exception, e:
            print e
            # ToDo: 应该对出错做一个通知机制，告诉管理员处理。
        time.sleep(6)   # 为了满足 WU 天气接口 api 访问频次的限制（10次/分钟），进行休眠等待。


