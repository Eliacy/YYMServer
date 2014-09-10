# -*- coding: utf-8 -*-

from KSQServer import db
db.create_all()

from KSQServer.models import Category
if db.session.query(Category).count() == 0:
    shop = Category(name=u'商店')
    restaurant = Category(name=u'餐馆')
    spot = Category(name=u'景点')
    db.session.add(shop)
    db.session.add(restaurant)
    db.session.add(spot)
    db.session.commit()

from KSQServer.models import User
from werkzeug.security import generate_password_hash
if db.session.query(User).count() == 0:
    admin = User(name=u'系统管理员', username='admin', password=generate_password_hash('startat408'))
    pm = User(name=u'产品经理', username='pm', password=generate_password_hash('pmDoesEverything'))
    operator = User(name=u'运营经理', username='operator', password=generate_password_hash('operatorRocks'))
    db.session.add(admin)
    db.session.add(pm)
    db.session.add(operator)
    db.session.commit()

