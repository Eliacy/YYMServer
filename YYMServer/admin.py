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
# ToDo: 可以考虑利用 Flask-Security 完善后台权限管理及功能！
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
    column_default_sort = ('id', True)
    column_display_pk = True

    def is_accessible(self):
        return login.current_user.is_authenticated() and (login.current_user.is_admin() or login.current_user.is_operator())


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
    column_default_sort = ('create_time', True)
    column_searchable_list = ('path', 'note')
    column_filters = ['id', 'valid', 'type', 'create_time', 'user_id'] + list(column_searchable_list)

    def create_model(self, form):
        if form.path.data.filename:
            form.note.data = u'[%s] %s' % (form.path.data.filename, form.note.data or u'')
        if not form.user.data:
            form.user.data = login.current_user
        return super(ImageView, self).create_model(form)

    def update_model(self, form, model):
        if form.path.data.filename:
            form.note.data = u'[%s] %s' % (form.path.data.filename, form.note.data or u'')
        return super(ImageView, self).update_model(form, model)

    def _list_thumbnail(view, context, model, name):
        if not model.path:
            return ''
        return Markup('%d, %s<br/><a href="%s" target="_blank"><img src="%s"></a>' % 
                         (model.id, 
                          model.path, 
                          url_for('static', filename=model.path),
                          url_for('static', filename=admin_form.thumbgen_filename(model.path)),
                          ))

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


def _get_images_code(images):
    image_code = ''
    for i in images:
        key, image_path = i
        image = (key, url_for('static', filename=image_path), url_for('static', filename=admin_form.thumbgen_filename(image_path)))
        image_code += '''<td  align="center" valign="top">[id: %d]<br/><a href="%s" target="_blank"><img src="%s"/></a></td>\n''' % image
    code = '''
    <div>
      <table width="%d" cellpadding="5"><tr>
      %s
      </tr></table>
    </div> ''' % (120 * len(images), image_code)
    return code

def _get_image_rule(label, images):
    ''' images: ((id, image_path), ...) '''
    images_code = _get_images_code(images)
    code = '''
  <div class="control-group">
    <div class="control-label">
      <label for="s2id_autogen2">%s</label>
    </div>
    <div class="controls">
      %s
    </div>
  </div> ''' % (label, images_code)
    return admin_form.rules.HTML(code)

def _get_images_info(image_ids_str):
    ''' 辅助函数。'''
    image_ids = ()
    try:
        image_ids = map(int, image_ids_str.split(' '))
    except:
        pass
    images = []
    if image_ids:
        for image_id in image_ids:
            image = db.session.query(Image).get(image_id)
            images.append((image_id, '' if not image else image.path))
    return images


class SiteView(MyModelView):
    column_default_sort = ('update_time', True)
    column_searchable_list = ('code', 'name', 'name_orig', 'address', 'address_orig')
    column_filters = ['id', 'valid', 'order', 'create_time', 'user_id', 'brand_id', 'logo_id', 'level', 'stars', 'popular',
                      'review_num', 'environment', 'flowrate', 'payment', 'menu', 'ticket', 'booking', 'business_hours',
                      'phone', 'transport', 'description', 'area_id', 'keywords', 'images_num',
                      ] + list(column_searchable_list)
    form_create_rules = ('valid', 'order', 'create_time', 'update_time', 'user', 'code', 'name', 'name_orig', 
                         'brand', 'logo', 'level', 'stars', 'popular', 'review_num', 'reviews', 'categories',
                         'environment', 'flowrate', 'payment', 'menu', 'ticket', 'booking', 'business_hours',
                         'phone', 'transport', 'description', 'longitude', 'latitude', 'area', 'address',
                         'address_orig', 'keywords', 'top_images', 'images_num', 'gate_images', 'data_source',
                         )
    column_list = ('id', 
                   'valid', 'order', 'create_time', 'update_time', 'user', 'code', 'name', 'name_orig', 
                   'brand', 'logo', 'level', 'stars', 'popular', 'review_num', 'categories',
                   'environment', 'flowrate', 'payment', 'menu', 'ticket', 'booking', 'business_hours',
                   'phone', 'transport', 'description', 'longitude', 'latitude', 
                   'country', 'city', 'area', 'address',
                   'address_orig', 'keywords', 'top_images', 'images_num', 'gate_images', 'data_source',
                   )

    def create_model(self, form):
        if not form.user.data:
            form.user.data = login.current_user
        return super(SiteView, self).create_model(form)

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
                    columns.append(_get_image_rule(u'Top Images', 
                                                   _get_images_info(site.top_images)
                                                   ))
            elif col == 'gate_images':
                if site.gate_images:
                    columns.append(_get_image_rule(u'Gate Images', 
                                                   _get_images_info(site.gate_images)
                                                   ))
        self.form_edit_rules = columns
        self._refresh_cache()
        return site

    def _list_thumbnail_logo(view, context, model, name):
        if not model.logo_id:
            return ''
        return Markup(_get_images_code(((model.logo_id, model.logo.path),)))

    def _list_thumbnail_top_images(view, context, model, name):
        if not model.top_images:
            return ''
        return Markup(_get_images_code(_get_images_info(model.top_images)))

    def _list_thumbnail_gate_images(view, context, model, name):
        if not model.gate_images:
            return ''
        return Markup(_get_images_code(_get_images_info(model.gate_images)))

    def _list_country(view, context, model, name):
        country_name = ''
        try:
            country_name = model.area.city.country.name
        except:
            pass
        return country_name

    def _list_city(view, context, model, name):
        city_name = ''
        try:
            city_name = model.area.city.name
        except:
            pass
        return city_name

    column_formatters = {
        'logo': _list_thumbnail_logo,
        'top_images':_list_thumbnail_top_images,
        'gate_images':_list_thumbnail_gate_images,
        'country':_list_country,
        'city':_list_city,
    }

    # 临时代码：展示表单验证实现方法
    def startswith_s(form, field):
        if not field.data.startswith('S'):
            raise validators.ValidationError(u'本项必须以"S"开头！这是一个演示表单验证功能的示例。')

    form_args = dict(
        code=dict(validators=[startswith_s])
    )


class ReviewView(MyModelView):
    column_default_sort = ('update_time', True)
    column_searchable_list = ('keywords',)
    column_filters = ['id', 'valid', 'selected', 'published', 'publish_time', 'update_time', 'user_id',
                      'stars', 'content', 'total', 'currency', 'site_id', 'like_num', 'comment_num',
                      ] + list(column_searchable_list)

    def create_model(self, form):
        if not form.user.data:
            form.user.data = login.current_user
        return super(ReviewView, self).create_model(form)


class CommentView(MyModelView):
    column_default_sort = ('update_time', True)
    column_searchable_list = ()
    column_filters = ['id', 'valid', 'publish_time', 'update_time', 'review_id', 'article_id', 'user_id', 'content'
                      ] + list(column_searchable_list)

    def create_model(self, form):
        if not form.user.data:
            form.user.data = login.current_user
        return super(CommentView, self).create_model(form)


class TagAlikeView(MyModelView):
    column_searchable_list = ('name',)
    column_filters = ['id', 'valid', 'order',] + list(column_searchable_list)


class BrandView(MyModelView):
    column_searchable_list = ('name', 'name_zh', 'description')
    column_filters = ['id', 'valid', 'order', 'source', 'level'] + list(column_searchable_list)


class RoleView(MyModelView):
    column_default_sort = None
    column_searchable_list = ('name',)
    column_filters = ['id'] + list(column_searchable_list)

    def is_accessible(self):
        return super(RoleView, self).is_accessible() and login.current_user.is_admin()


class UserView(MyModelView):
    column_default_sort = None
    column_searchable_list = ('name', 'username', 'mobile')
    column_filters = ['id', 'create_time', 'update_time', 'icon_id', 'gender', 'level', 'exp', 'follow_num',
                      'fans_num', 'like_num', 'share_num', 'review_num', 'favorite_num', 'badges',
                      ] + list(column_searchable_list)

    def is_accessible(self):
        return super(UserView, self).is_accessible() and login.current_user.is_admin()


class ShareRecordView(MyModelView):
    column_searchable_list = ('target', )
    column_filters = ['user_id', 'site_id', 'review_id', 'action_time'] + list(column_searchable_list)

    def is_accessible(self):
        return super(ShareRecordView, self).is_accessible() and login.current_user.is_admin()


class TipsView(MyModelView):
    column_default_sort = ('update_time', True)
    column_searchable_list = ('content', )
    column_filters = ['id', 'valid', 'create_time', 'update_time', 'user_id', 'city_id'] + list(column_searchable_list)

    def create_model(self, form):
        if not form.user.data:
            form.user.data = login.current_user
        return super(TipsView, self).create_model(form)


class ArticleView(MyModelView):
    column_default_sort = ('update_time', True)
    column_searchable_list = ('title', 'keywords', 'content')
    column_filters = ['id', 'valid', 'order', 'create_time', 'update_time', 'user_id', 'comment_num'] + list(column_searchable_list)

    def create_model(self, form):
        if not form.user.data:
            form.user.data = login.current_user
        return super(ArticleView, self).create_model(form)


class MessageView(MyModelView):
    column_default_sort = ('create_time', True)
    column_searchable_list = ('content', 'group_key')
    column_filters = ['id', 'valid', 'create_time', 'sender_user_id'] + list(column_searchable_list)


# Create admin
admin = Admin(app, 'Admin', index_view=MyAdminIndexView(), base_template='my_master.html')
admin.add_view(TipsView(Tips, db.session))
admin.add_view(ArticleView(Article, db.session))
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
admin.add_view(RoleView(Role, db.session))
admin.add_view(ShareRecordView(ShareRecord, db.session))
admin.add_view(MessageView(Message, db.session))


