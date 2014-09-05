# -*- coding: utf-8 -*-

import os.path
import uuid

from flask import url_for, redirect, request
from jinja2 import Markup
from werkzeug import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from wtforms import form, fields, validators

from flask.ext.admin import Admin, AdminIndexView
from flask.ext.admin import form as admin_form
from flask.ext.admin import helpers, expose
from flask.ext.admin.contrib.sqla import ModelView
from flask.ext import login

from KSQServer import app, db, file_path
from KSQServer.models import *


# 假的 user model.
# 完整代码参考：https://github.com/mrjoes/flask-admin/blob/master/examples/auth/auth.py
class User(object):
    id = 1
    username = u'管理员'
    login = 'admin'
    password = generate_password_hash('startat408')

    # Flask-Login integration
    def is_authenticated(self):
        return True

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return self.id

    # Required for administrative interface
    def __unicode__(self):
        return self.username


# Define login and registration forms (for flask-login)
class LoginForm(form.Form):
    login = fields.TextField(validators=[validators.required()])
    password = fields.PasswordField(validators=[validators.required()])

    def validate_login(self, field):
        user = self.get_user()

        if user is None:
            raise validators.ValidationError('Invalid user')

        # we're comparing the plaintext pw with the the hash from the db
        if not check_password_hash(user.password, self.password.data):
        # to compare plain text passwords use
        # if user.password != self.password.data:
            raise validators.ValidationError('Invalid password')

    def get_user(self):
        user = User()
        if self.login.data == user.login:
            return user
        else:
            return None


# Initialize flask-login
def init_login():
    login_manager = login.LoginManager()
    login_manager.init_app(app)

    # Create user loader function
    @login_manager.user_loader
    def load_user(user_id):
        user = User()
        if user_id == user.id:
            return user
        else:
            return None


# Create customized model view class
class MyModelView(ModelView):

    def is_accessible(self):
        return login.current_user.is_authenticated()


# Create customized index view class that handles login & registration
class MyAdminIndexView(AdminIndexView):

    @expose('/')
    def index(self):
        if not login.current_user.is_authenticated():
            return redirect(url_for('.login_view'))
        return super(MyAdminIndexView, self).index()

    @expose('/login/', methods=('GET', 'POST'))
    def login_view(self):
        # handle user login
        form = LoginForm(request.form)
        if helpers.validate_form_on_submit(form):
            user = form.get_user()
            login.login_user(user)

        if login.current_user.is_authenticated():
            return redirect(url_for('.index'))
        self._template_args['form'] = form
        return super(MyAdminIndexView, self).index()

    @expose('/logout/')
    def logout_view(self):
        login.logout_user()
        return redirect(url_for('.index'))


# Initialize flask-login
init_login()


def uuid_name(obj, file_data):
    parts = os.path.splitext(file_data.filename)
    return secure_filename('%s%s' % (uuid.uuid4(), parts[1]))


# 参考：https://github.com/mrjoes/flask-admin/blob/master/examples/forms/simple.py
class ImageView(MyModelView):
    def _list_thumbnail(view, context, model, name):
        if not model.path:
            return ''

        return Markup('<img src="%s">' % url_for('static',
                                                 filename=admin_form.thumbgen_filename(model.path)))

    column_formatters = {
        'path': _list_thumbnail
    }

    # Alternative way to contribute field is to override it completely.
    # In this case, Flask-Admin won't attempt to merge various parameters for the field.
    form_extra_fields = {
        'path': admin_form.ImageUploadField('Image',
                                      base_path=file_path,
                                      thumbnail_size=(100, 100, True),
                                      namegen=uuid_name)
    }

# Create admin
admin = Admin(app, 'Admin', index_view=MyAdminIndexView(), base_template='my_master.html')
admin.add_view(MyModelView(Site, db.session))
admin.add_view(MyModelView(Comment, db.session))
admin.add_view(ImageView(Image, db.session))
admin.add_view(MyModelView(Category, db.session))
admin.add_view(MyModelView(Brand, db.session))
admin.add_view(MyModelView(Country, db.session))
admin.add_view(MyModelView(City, db.session))
admin.add_view(MyModelView(Area, db.session))


