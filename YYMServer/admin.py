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

from YYMServer import app, db, file_path
from YYMServer.models import *


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
        if form.path.data.filename:
            form.note.data = u'[%s] %s' % (form.path.data.filename, form.note.data or u'')
        return super(ImageView, self).create_model(form)

    def update_model(self, form, model):
        if form.path.data.filename:
            form.note.data = u'[%s] %s' % (form.path.data.filename, form.note.data or u'')
        return super(ImageView, self).update_model(form, model)

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


def _get_image_rule(label, images):
    ''' images: ((id, image_path), ...) '''
    image_code = ''
    for i in images:
        key, image_path = i
        image = (key, url_for('static', filename=image_path), url_for('static', filename=admin_form.thumbgen_filename(image_path)))
        image_code += '''<td  align="center" valign="top">[id: %d]<br/><a href="%s" target="_blank"><img src="%s"/></a></td>\n''' % image
    code = '''
  <div class="control-group">
    <div class="control-label">
      <label for="s2id_autogen2">%s</label>
    </div>
    <div class="controls">
    <div>
      <table cellpadding="5"><tr>
      %s
      </tr></table>
    </div>
    </div>
  </div> ''' % (label, image_code)
    return admin_form.rules.HTML(code)


class SiteView(MyModelView):
    column_searchable_list = ('code', 'name', 'name_orig', 'address', 'address_orig')
    form_create_rules = ('valid', 'order', 'create_time', 'update_time', 'code', 'name', 'name_orig', 
                         'brand', 'logo', 'level', 'stars', 'review_num', 'comments', 'categories', 'environment',
                         'flowrate', 'payment', 'menu', 'ticket', 'booking', 'business_hours',
                         'phone', 'transport', 'description', 'longitude', 'latitude', 'area', 'address',
                         'address_orig', 'keywords', 'top_images', 'gate_images', 'data_source',
                         )

    def get_image_rule(self, label, image_ids):
        ''' 辅助函数。'''
        if image_ids:
            images = []
            for image_id in image_ids:
                image = self.session.query(Image).get(image_id)
                images.append((image_id, '' if not image else image.path))
            return _get_image_rule(u'Top Images', images)
        return None

    def get_one(self, id):
        ''' ToDo：一个脏补丁，用来显示店铺相关的各种图片。但是被迫经常刷新缓存，性能比较差。应该还是通过定制 Form Field 来实现较好。'''
        site = super(SiteView, self).get_one(id)
        columns = []
        for col in self.form_create_rules:
            columns.append(col)
            if col == 'logo':
                if site.logo_id:
                    columns.append(_get_image_rule(u'Logo Image', ((site.logo_id, site.logo.path),)))
            elif col == 'top_images':
                if site.top_images:
                    columns.append(self.get_image_rule(u'Top Images', map(int, site.top_images.split(','))))
            elif col == 'gate_images':
                if site.gate_images:
                    columns.append(self.get_image_rule(u'Top Images', map(int, site.gate_images.split(','))))
        self.form_edit_rules = columns
        self._refresh_cache()
        return site


class ReviewView(MyModelView):
    column_searchable_list = ('keywords',)


class CommentView(MyModelView):
    column_searchable_list = ()


class TagAlikeView(MyModelView):
    column_searchable_list = ('name',)


class BrandView(MyModelView):
    column_searchable_list = ('name', 'name_zh')


class UserView(MyModelView):
    column_searchable_list = ('name', 'username', 'mobile')


# Create admin
admin = Admin(app, 'Admin', index_view=MyAdminIndexView(), base_template='my_master.html')
admin.add_view(SiteView(Site, db.session))
admin.add_view(ReviewView(Review, db.session))
admin.add_view(CommentView(Comment, db.session))
admin.add_view(ImageView(Image, db.session))
admin.add_view(TagAlikeView(Category, db.session))
admin.add_view(BrandView(Brand, db.session))
admin.add_view(TagAlikeView(Country, db.session))
admin.add_view(TagAlikeView(City, db.session))
admin.add_view(TagAlikeView(Area, db.session))
admin.add_view(UserView(User, db.session))


