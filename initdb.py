# -*- coding: utf-8 -*-

from YYMServer import db
db.create_all()

from YYMServer.models import Category
if db.session.query(Category).count() == 0:
    shop = Category(name=u'商店')
    restaurant = Category(name=u'餐馆')
    spot = Category(name=u'景点')
    db.session.add(shop)
    db.session.add(restaurant)
    db.session.add(spot)
    db.session.commit()

from YYMServer.models import Role
if db.session.query(Role).count() == 0:
    admin = Role(name=u'系统管理员')
    operator = Role(name=u'运营人员')
    db.session.add(admin)
    db.session.add(operator)
    db.session.commit()

from YYMServer.models import User
from werkzeug.security import generate_password_hash
if db.session.query(User).count() == 0:
    admin = User(name=u'系统管理员', username='admin', password=generate_password_hash('startat408'))
    pm = User(name=u'产品经理', username='pm', password=generate_password_hash('pmDoesEverything'))
    operator = User(name=u'运营经理', username='operator', password=generate_password_hash('operatorRocks'))
    admin.roles.append(db.session.query(Role).filter(Role.id==7)[0])
    operator.roles.append(db.session.query(Role).filter(Role.id==8)[0])
    db.session.add(admin)
    db.session.add(pm)
    db.session.add(operator)
    db.session.commit()

