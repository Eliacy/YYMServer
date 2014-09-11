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


# 完整代码参考：https://github.com/mrjoes/flask-admin/blob/master/examples/auth/auth.py


# Define login and registration forms (for flask-login)
class LoginForm(form.Form):
    username = fields.TextField(validators=[validators.required()])
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
        return db.session.query(User).filter_by(username=self.username.data).first()


# Initialize flask-login
def init_login():
    login_manager = login.LoginManager()
    login_manager.init_app(app)

    # Create user loader function
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.query(User).get(user_id)


# Create customized model view class
class MyModelView(ModelView):

    def is_accessible(self):
        return login.current_user.is_authenticated() and login.current_user.is_admin()


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
    column_searchable_list = ('path', 'note')

    def create_model(self, form):
        form.note.data = form.note.data if form.note.data != None else u''
        form.note.data = u'；'.join((form.path.data.filename, form.note.data))
        return super(ImageView, self).create_model(form)

    def _list_thumbnail(view, context, model, name):
        if not model.path:
            return ''
        return Markup('%d, %s<br/><img src="%s">' % (model.id, model.path, url_for('static',
                                                 filename=admin_form.thumbgen_filename(model.path))))

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


class SiteView(MyModelView):
    column_searchable_list = ('code', 'name', 'name_orig', 'address', 'address_orig')
    form_create_rules = ('valid', 'create_time', 'update_time', 'code', 'name', 'name_orig', 
                         'brand', 'logo', 'level', 'stars', 'comments', 'categories', 'environment',
                         'flowrate', 'payment', 'menu', 'ticket', 'booking', 'business_hours',
                         'phone', 'description', 'longitude', 'latitude', 'area', 'address',
                         'address_orig', 'keywords', 'top_images', 'gate_images', 'data_source',
                         )

    def get_one(self, id):
        ''' 一个脏补丁，用来显示店铺相关的各种图片。'''
        site = super(SiteView, self).get_one(id)
        columns = []
        for col in self.form_create_rules:
            columns.append(col)
            if col == 'logo':
                if site.logo_id:
                    columns.append(admin_form.rules.HTML('''
  <div class="control-group">
    <div class="control-label">
      <label for="s2id_autogen2">Logo Image</label>
    </div>
    <div class="controls">
    <div>
      <a href="%s" target="_blank"><img src="%s"/></a>
    </div>
    </div>
  </div> ''' % (url_for('static', filename=site.logo.path), 
                url_for('static', filename=admin_form.thumbgen_filename(site.logo.path)))))
        self.form_edit_rules = columns
        self._refresh_cache()
        return site


# Create admin
admin = Admin(app, 'Admin', index_view=MyAdminIndexView(), base_template='my_master.html')
admin.add_view(SiteView(Site, db.session))
admin.add_view(MyModelView(Comment, db.session))
admin.add_view(ImageView(Image, db.session))
admin.add_view(MyModelView(Category, db.session))
admin.add_view(MyModelView(Brand, db.session))
admin.add_view(MyModelView(Country, db.session))
admin.add_view(MyModelView(City, db.session))
admin.add_view(MyModelView(Area, db.session))
admin.add_view(MyModelView(User, db.session))


