# -*- coding: utf-8 -*-

from KSQServer import db
db.create_all()

from KSQServer.models import Category
shop = Category(name=u'商店')
restaurant = Category(name=u'餐馆')
spot = Category(name=u'景点')
db.session.add(shop)
db.session.add(restaurant)
db.session.add(spot)
db.session.commit()

