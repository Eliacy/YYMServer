# -*- coding: utf-8 -*-

import codecs
import datetime
import json
import os
import time

import pytz
import requests
from sqlalchemy import func

from YYMServer import app, db, tz_server
from YYMServer.models import City, Forecast

MAX_FORECAST_RECORDS = 3

wu_key = app.config['WEATHER_KEY_WU']

def check_update():
    ''' 本脚本需要每小时定时执行，以便保证数据库中的天气数据能够得到及时更新。'''
    now = tz_server.localize(datetime.datetime.now())
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
                previous_fetch = timezone.normalize(tz_server.localize(forecast.update_time))
                if previous_fetch.date() == dt.date():
                    continue
        # timezone 为空或者通过时间点及数据是否已存在检查时，连网抓取天气预报数据：
        if not city.longitude or not city.latitude:
            continue
        api_url = 'http://api.wunderground.com/api/%s/hourly/forecast10day/lang:CN/q/%f,%f.json' % (wu_key, city.latitude, city.longitude)
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

def export_forecasts(dir_path):
    ''' 清理冗余天气数据，保证数据库体积维持在较小的状态下。'''
    if not os.path.exists(dir_path):
        os.mkdir(dir_path)
    query = db.session.query(Forecast.city_id, func.count(Forecast.id)).group_by(Forecast.city_id)
    for forecast_count in query:
        city_id, num = forecast_count
        print city_id, num
        if num > MAX_FORECAST_RECORDS:
            sub_query = db.session.query(Forecast).filter(Forecast.city_id == city_id).order_by(Forecast.id).limit(num - MAX_FORECAST_RECORDS)
            for forecast_to_export in sub_query:
                print forecast_to_export.city_id, forecast_to_export.update_time
                filename = '%d_%d' % (forecast_to_export.id, int((forecast_to_export.update_time - datetime.datetime(1970, 1, 1)).total_seconds()))
                with codecs.open(os.path.join(dir_path, filename), 'w', 'utf-8') as file:
                    file.write(forecast_to_export.data)
                db.session.delete(forecast_to_export)
                db.session.commit()


