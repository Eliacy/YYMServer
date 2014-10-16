# -*- coding: utf-8 -*-

import os.path
import uuid

import PIL

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

from YYMServer import app, db, file_path, util
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
    list_template = 'my_list.html'
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
    extension = parts[1].lower()
    extension = '.jpg' if extension == '.jpeg' else extension
    # flask-admin 的文件上传组件似乎总是在实际存储时把文件名弄成小写：
    return secure_filename('%s%s' % (uuid.uuid4(), extension))

def get_image_size(path):
    full_path = os.path.join(file_path, path)
    if path and os.path.exists(full_path):
        im = PIL.Image.open(full_path)
        return '%dx%d' % (im.size)
    else:
        return '[[==IMAGE DO NOT EXIST!!!==]]'


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
        return Markup('%d, (%s)<br/>%s<br/><a href="%s" target="_blank"><img src="%s"></a>' % 
                         (model.id,
                          get_image_size(model.path),
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
    image_code = u''
    for image in images:
        image = (image.id, 
                 get_image_size(image.path), 
                 util.strip_image_note(image.note),
                 url_for('static', filename=image.path), 
                 url_for('static', filename=admin_form.thumbgen_filename(image.path)),
                 )
        image_code += u'''<td  align="center" valign="top">[id: %d]<br/>(%s)<br/>～%s～<br/><a href="%s" target="_blank"><img src="%s"/></a></td>\n''' % image
    code = u'''
    <div>
      <table width="%d" cellpadding="5"><tr>
      %s
      </tr></table>
    </div> ''' % (120 * len(images), image_code)
    return code

def _get_image_rule(label, images):
    ''' images: ((id, image_path), ...) '''
    images_code = _get_images_code(images)
    code = u'''
  <div class="control-group">
    <div class="control-label">
      <label for="s2id_autogen2">%s</label>
    </div>
    <div class="controls">
      %s
    </div>
  </div> ''' % (label, images_code)
    return admin_form.rules.HTML(code)


class SiteView(MyModelView):
    column_default_sort = ('update_time', True)
    column_searchable_list = ('code', 'name', 'name_orig', 'address', 'address_orig')
    column_filters = ['id', 'valid', 'order', 'create_time', 'create_user_id', 'update_user_id', 'brand_id', 
                      'logo_id', 'level', 'stars', 'popular',
                      'review_num', 'environment', 'flowrate', 'payment', 'menu', 'ticket', 'booking', 'business_hours',
                      'phone', 'transport', 'description', 'area_id', 'keywords', 'images_num',
                      ] + list(column_searchable_list)
    form_create_rules = ('valid', 'order', 'create_time', 'update_time', 'create_user', 'update_user', 'code', 'name', 'name_orig', 
                         'brand', 'logo_id', 'level', 'stars', 'popular', 'review_num', 'reviews', 'categories',
                         'environment', 'flowrate', 'payment', 'menu', 'ticket', 'booking', 'business_hours',
                         'phone', 'transport', 'description', 'longitude', 'latitude', 'area', 'address',
                         'address_orig', 'keywords', 'top_images', 'images_num', 'gate_images', 'data_source',
                         )
    column_list = ('id', 
                   'valid', 'order', 'create_time', 'update_time', 'create_user', 'update_user', 'code', 'name', 'name_orig', 
                   'brand', 'logo', 'level', 'stars', 'popular', 'review_num', 'categories',
                   'environment', 'flowrate', 'payment', 'menu', 'ticket', 'booking', 'business_hours',
                   'phone', 'transport', 'description', 'longitude', 'latitude', 
                   'country', 'city', 'area', 'address',
                   'address_orig', 'keywords', 'top_images', 'images_num', 'gate_images', 'data_source',
                   )

    def _replace_full_width_chars(self, text):
        ''' 辅助函数，替换 ：、空格、－、（、）到英文半角版本。'''
        if type(text) == unicode:
            return text.translate({ord(u'：'):u':',
                                   ord(u'　'):u' ',
                                   ord(u'－'):u'-',
                                   ord(u'（'):u'(',
                                   ord(u'）'):u')',
                                   })
        return text

    def _extend_code(self, code_orig):
        ''' 辅助函数，自动补全 POI 编号。 '''
        if code_orig and len(code_orig) == 6:
            try:
                site_largest_code = db.session.query(Site).filter(Site.code.ilike(u'{}%'.format(code_orig))).order_by(Site.id.desc()).first()
                if not site_largest_code:
                    largest_code = 0
                else:
                    largest_code = int(site_largest_code.code[6:])
                return code_orig[:6] + '{:0>4d}'.format(largest_code + 1)
            except:
                pass
        return code_orig

    def create_model(self, form):
        if not form.create_user.data:
            form.create_user.data = login.current_user
        form.update_user.data = login.current_user
        form.code.data = self._extend_code(form.code.data)
        form.business_hours.data = self._replace_full_width_chars(form.business_hours.data)
        form.phone.data = self._replace_full_width_chars(form.phone.data)
        if form.brand.data:
            form.level.data = form.brand.data.level
        return super(SiteView, self).create_model(form)

    def update_model(self, form, model):
        form.update_user.data = login.current_user
        form.code.data = self._extend_code(form.code.data)
        form.business_hours.data = self._replace_full_width_chars(form.business_hours.data)
        form.phone.data = self._replace_full_width_chars(form.phone.data)
        if form.brand.data:
            form.level.data = form.brand.data.level
        return super(SiteView, self).update_model(form, model)

    def get_one(self, id):
        ''' ToDo：一个脏补丁，用来显示店铺相关的各种图片。但是被迫经常刷新缓存，性能比较差。应该还是通过定制 Form Field 来实现较好。'''
        site = super(SiteView, self).get_one(id)
        columns = []
        for col in self.form_create_rules:
            columns.append(col)
            if col == 'logo_id':
                if site.logo_id:
                    columns.append(_get_image_rule(u'Logo Image', (site.logo, )))
            elif col == 'top_images':
                if site.top_images:
                    columns.append(_get_image_rule(u'Top Images', 
                                                   util.get_images(site.top_images, valid_only=False)
                                                   ))
            elif col == 'gate_images':
                if site.gate_images:
                    columns.append(_get_image_rule(u'Gate Images', 
                                                   util.get_images(site.gate_images, valid_only=False)
                                                   ))
        self.form_edit_rules = columns
        self._refresh_cache()
        return site

    def _list_thumbnail_logo(view, context, model, name):
        if not model.logo_id:
            return ''
        return Markup(_get_images_code((model.logo, )))

    def _list_thumbnail_top_images(view, context, model, name):
        if not model.top_images:
            return ''
        return Markup(_get_images_code(util.get_images(model.top_images, valid_only=False)))

    def _list_thumbnail_gate_images(view, context, model, name):
        if not model.gate_images:
            return ''
        return Markup(_get_images_code(util.get_images(model.gate_images, valid_only=False)))

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

    def _list_address_orig(view, context, model, name):
        if not model.latitude or not model.longitude:
            return model.address_orig
        address_orig = model.address_orig or u''
        return Markup(u'''<a href="%s" target="_blank">查地图</a><br/>''' %
                (u'''http://www.latlong.net/c/?lat=%f&long=%f''' % (model.latitude, model.longitude))
                + address_orig)

    def _list_data_source(view, context, model, name):
        data_source = model.data_source or u''
        if not data_source.startswith('http://') and not data_source.startswith('https://'):
            data_source = 'http://' + data_source
        return Markup(u'''<a href="%s" target="_blank">%s</a><br/>''' %
                (data_source, data_source))

    column_formatters = {
        'logo': _list_thumbnail_logo,
        'top_images':_list_thumbnail_top_images,
        'gate_images':_list_thumbnail_gate_images,
        'country':_list_country,
        'city':_list_city,
        'address_orig':_list_address_orig,
        'data_source':_list_data_source,
    }

    def check_logo(form, field):
        ''' 检查选择的 logo 图是否在数据库记录中真正存在。 '''
        logo_id = field.data or 0
        if not field.data:      # 当文本框为空，覆盖 IntegerField 默认的是否是整数的检查，以允许空值
            field.errors[:] = []
            raise validators.StopValidation()   # Stop further validators running
        if logo_id:
            logo = db.session.query(Image).get(logo_id)
            if not logo:
                raise validators.ValidationError(u'所选定的 logo 图片在数据库中不存在！')

    def check_code(form, field):
        ''' 检查 POI Code 编码是否符合规范的要求。 '''
        code = field.data or ''
        if len(code) < 6:
            raise validators.ValidationError(u'编号至少需要填写前6位的类别、国家、城市代码')
        if not code[0] in 'SAREHU':
            raise validators.ValidationError(u'编号首字母必须以"S A R E H U"其中一个之一！')
        if not code[1:3].isalpha():
            raise validators.ValidationError(u'编号第2、3位的国家标识必须都是字母！')
        if not code[3:6].isalpha():
            raise validators.ValidationError(u'编号第4～6位的城市标识必须都是字母！')
        if not len(code) in (6, 10):
            raise validators.ValidationError(u'编号应该刚好是6位或10位！')
        if len(code) > 6 and not code[6:].isdigit():
            raise validators.ValidationError(u'编号最后4位的 POI 编号必须都是数字！')
        query = db.session.query(Site).filter(Site.code == code)
        id = request.args.get('id')
        if id:
            query = query.filter(Site.id != id)
        if query.first():
            raise validators.ValidationError(u'此编号已经被使用，请更新其中的序号以避免重复！')

    form_extra_fields = {
        'logo_id': fields.IntegerField('Logo id', validators=[check_logo]),
    }
    form_args = dict(
        code=dict(validators=[check_code]),
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

    def create_model(self, form):
        if form.sites.data:
            for site in form.sites.data:
                site.level = form.level.data
        return super(BrandView, self).create_model(form)

    def update_model(self, form, model):
        if form.sites.data:
            for site in form.sites.data:
                site.level = form.level.data
        return super(BrandView, self).update_model(form, model)

    def check_name(form, field):
        ''' 检查以避免创建重复品牌，主要的依据是根据 name 的取值。'''
        name = field.data or ''
        name = name.strip()
        if name:
            query = db.session.query(Brand).filter(Brand.name.ilike(name))
            id = request.args.get('id')
            if id:
                query = query.filter(Brand.id != id)
            same_brand = query.first()
            if same_brand:
                raise validators.ValidationError(u'存在同名品牌 id {}: “{}”，建议检查当前品牌是否与之重复！'.format(same_brand.id, same_brand.name))

    form_args = dict(
        name=dict(validators=[check_name]),
    )


class RoleView(MyModelView):
    column_default_sort = None
    column_searchable_list = ('name',)
    column_filters = ['id'] + list(column_searchable_list)

    def is_accessible(self):
        return super(RoleView, self).is_accessible() and login.current_user.is_admin()


class UserView(MyModelView):
    form_excluded_columns = ('images', 'created_sites', 'updated_sites', 'share_records', 'reviews', 'comments', 'articles', 'tips', 'read_records', 'sent_messages', 'messages')       # 出于性能考虑，禁止显示这些涉及大数据量外键的字段。
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


