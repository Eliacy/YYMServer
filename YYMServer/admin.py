# -*- coding: utf-8 -*-

import json
import os.path
import shortuuid

from flask import url_for, redirect, request, flash, escape
from jinja2 import Markup
from sqlalchemy import or_, and_, inspect, orm
from werkzeug import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from wtforms import form, fields, validators

from flask.ext.admin import Admin, AdminIndexView
from flask.ext.admin import form as admin_form
from flask.ext.admin import helpers, expose
from flask.ext.admin.contrib.sqla import ModelView
from flask.ext.admin.contrib.sqla.ajax import QueryAjaxModelLoader
from flask.ext.admin.model.ajax import DEFAULT_PAGE_SIZE
from flask.ext import login

from YYMServer import app, db, file_path, util, message
from YYMServer.models import *


# 完整代码参考：https://github.com/mrjoes/flask-admin/blob/master/examples/auth/app.py
# Define login and registration forms (for flask-login)
# ToDo: 可以考虑利用 Flask-Security 完善后台权限管理及功能！
class LoginForm(form.Form):
    username = fields.TextField(validators=[validators.required()])
    password = fields.PasswordField(validators=[validators.required()])

    def validate_password(self, field):
        ''' 会根据 Form 类的约定参与校验 password 变量。'''
        user = self.get_user()

        if user is None:
            raise validators.ValidationError(u'用户名或密码不正确！')

        # we're comparing the plaintext pw with the the hash from the db
        if not check_password_hash(user.password, self.password.data):
        # to compare plain text passwords use
        # if user.password != self.password.data:
            raise validators.ValidationError(u'用户名或密码不正确！')

    def get_user(self):
        return db.session.query(User).filter(User.valid == True).filter(User.username == self.username.data).first()


# Initialize flask-login
def init_login():
    login_manager = login.LoginManager()
    login_manager.init_app(app)

    # Create user loader function
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.query(User).get(user_id)


# 几个改进类：
class IlikeQueryAjaxModelLoader(QueryAjaxModelLoader):
    ''' 支持大小写不敏感的 ilike 检索方式的 Ajax 外键搜索的后台接口。'''

    def get_list(self, term, offset=0, limit=DEFAULT_PAGE_SIZE):
        # 这个函数直接复制了 https://github.com/mrjoes/flask-admin/blob/master/flask_admin/contrib/sqla/ajax.py 的原始代码，需要定期同步更新！
        query = self.session.query(self.model)

        filters = (field.ilike(u'%%%s%%' % term) for field in self._cached_fields)
        query = query.filter(or_(*filters))

        return query.offset(offset).limit(limit).all()


class ImageUploadInput(admin_form.ImageUploadInput):
    ''' 修改图片资源缩略图的显示方式。'''
    def get_url(self, field):
        return util.url_for_thumb(field.data or '')


class ImageUploadField(admin_form.ImageUploadField):
    ''' 调用能显示云存储缩略图的图片上传组件。'''
    widget = ImageUploadInput()


def _get_model_items(model):
    ''' 把一个数据 model 的值转为字典形式保存，用于后续比较。'''
    dic = {}
    mapper = inspect(model)
    for column in mapper.attrs:
        # ToDo: 下一行的实现存在 bug，因为无法正确保存外键关联的数据。
        value = getattr(model, column.key, None)
        if isinstance(value, (db.Model, orm.query.Query)):     # 不记录关联表的实体
            continue
        if type(value) == datetime.datetime:    # 不比较时间戳
            continue
        dic[column.key] = value
    return dic

def _compare_model(before_model, after_model):
    ''' 比较两个不同 model 的内容差别，输出为字典。'''
    before_model = before_model or {}
    after_model = after_model or {}
    keys = ()
    if before_model:
        keys = before_model.keys()
    if after_model:
        keys = after_model.keys()
    diff_before_dic = {}
    diff_after_dic = {}
    for key in keys:
        before = before_model.get(key, None) or None
        after = after_model.get(key, None) or None
        if before != after:
            diff_before_dic[key] = before
            diff_after_dic[key] = after
    return (diff_before_dic, diff_after_dic)

def _create_log(user, model, action, before, after):
    ''' 实际记录用户在后台的操作行为。'''
    log = Log(user=user,
              model = unicode(model.__tablename__),
              model_id = model.id,
              action = unicode(action),
              before = unicode(json.dumps(before, ensure_ascii=False)),
              after = unicode(json.dumps(after, ensure_ascii=False)),
             )
    db.session.add(log)
    db.session.commit()


# Create customized model view class
class MyModelView(ModelView):
    # ToDo: 应该记录用户在后台的全部操作，以追踪误删等可能造成运营风险的行为。
    list_template = 'my_list.html'
    column_default_sort = ('id', True)
    column_display_pk = True

    def is_accessible(self):
        return login.current_user.is_authenticated() and (login.current_user.is_admin() or login.current_user.is_operator())

    def update_model(self, form, model):
        ''' 避免在表单中未显示的字段将数据库 Model 覆盖为空值。'''
        self.before_update_model = _get_model_items(model)
        # 不确定这是不是合适的实现方法。
        if self.form_edit_rules:
            for field in form:
                field_name = field.name
                if field_name not in self.form_edit_rules:
                    form.__delitem__(field_name)
        if hasattr(form, 'update_time'):    # 避免表单中显示的旧 update_time 覆盖数据库 on_update 触发生成的取值。
            form.__delitem__('update_time')
        if hasattr(model, 'update_time'):
            model.update_time = datetime.datetime.now()
        return super(MyModelView, self).update_model(form, model)

    def after_model_change(self, form, model, is_created):
        ''' 比较更新前后的 model 取值，以记录后台更新日志。'''
        if is_created:
            before, after = _compare_model({}, _get_model_items(model))
            _create_log(login.current_user, model, u'create', {}, after)
        else:
            after_update_model = _get_model_items(model)
            before, after = _compare_model(self.before_update_model, after_update_model)
            if before != after:
                _create_log(login.current_user, model, u'edit', before, after)
        return super(MyModelView, self).after_model_change(form, model, is_created)

    def on_model_delete(self, model):
        ''' 记录用户在后台的删除行为。'''
        before, after = _compare_model(_get_model_items(model), {})
        _create_log(login.current_user, model, u'delete', before, {})
        return super(MyModelView, self).on_model_delete(model)


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


def _list_content(view, context, model, name):
    ''' 转换文本标签文章内容到富媒体列表格式，供后台人工检查确认。'''
    output = util.parse_textstyle(util.replace_textlib(model.content))
    markups = []
    for entry in output:
        type = entry['class']
        content = entry['content']
        if type == 'text':
            markups.append(content)
        elif type == 'title':
            markups.append(u'<font color="#00FF00">%s</font>' % content)
        elif type == 'hline':
            markups.append(u'--------')
        elif type == 'image':   # 这里拿到的图片有可能是 None
            markups.append(_get_images_code([content]))
        elif type == 'site':
            markups.append(escape(unicode(content)))
    return Markup(u'''<br/>'''.join(markups))

def uuid_name(obj, file_data):
    parts = os.path.splitext(file_data.filename)
    extension = parts[1].lower()
    extension = '.jpg' if extension == '.jpeg' else extension
    # flask-admin 的文件上传组件似乎总是在实际存储时把文件名弄成小写：
    return secure_filename('%s%s' % (shortuuid.uuid(), extension))

def get_image_size(image_obj):
    if image_obj:
        path = image_obj.path or ''
        if path.startswith('qiniu:'):
            return '%dx%d' % (image_obj.width or 0, image_obj.height or 0)
        full_path = os.path.join(file_path, path)
        size = util.get_image_size(full_path)
        if size:
            return u'【【＝未上传到云存储！＝】】%dx%d' % size
    return '[[==IMAGE DO NOT EXIST!!!==]]'

def check_image_exist(form, field):
    ''' 检查选择的图片是否在数据库记录中真正存在。 '''
    logo_id = field.data or 0
    if not field.data:      # 当文本框为空，覆盖 IntegerField 默认的是否是整数的检查，以允许空值
        field.errors[:] = []
        raise validators.StopValidation()   # Stop further validators running
    if logo_id:
        logo = db.session.query(Image).get(logo_id)
        if not logo:
            raise validators.ValidationError(u'所选定的图片在数据库中不存在！')


class TextLibView(MyModelView):
    column_default_sort = ('update_time', True)
    column_searchable_list = ('note', 'content')
    column_filters = ['id', 'valid', 'create_time', 'update_time', 'create_user_id', 'update_user_id',] + list(column_searchable_list)
    form_ajax_refs = {
        'create_user': {
            'fields': (User.id,)
        },
        'update_user': {
            'fields': (User.id,)
        },
    }

    def create_model(self, form):
        if not form.create_user.data:
            form.create_user.data = login.current_user
        form.update_user.data = login.current_user
        return super(TextLibView, self).create_model(form)

    def update_model(self, form, model):
        if not form.create_user.data:
            form.__delitem__('create_user')
        form.update_user.data = login.current_user
        return super(TextLibView, self).update_model(form, model)


# 参考：https://github.com/mrjoes/flask-admin/blob/master/examples/forms/simple.py
class ImageView(MyModelView):
    column_default_sort = ('create_time', True)
    column_searchable_list = ('path', 'note', 'name')
    column_filters = ['id', 'valid', 'type', 'create_time', 'user_id', 'size', 'mime', 'width', 'height'] + list(column_searchable_list)
    form_ajax_refs = {
        'user': {
            'fields': (User.id,)
        },
    }

    def after_model_change(self, form, model, is_created):
        '''如果上传了新图片，则迁移图片文件到七牛云存储上。'''
        if form.path.data:
            full_path = os.path.join(file_path, model.path)
            ret, err = util.upload_image(full_path, model.id, model.type, model.user_id, model.note, model.name)
            if err is not None:
                flash(u'QiNiu uploading failed! %s' % unicode(err))
        else:
            pass
        return super(ImageView, self).after_model_change(form, model, is_created)

    def create_model(self, form):
        if form.path.data.filename:
            form.name.data = form.path.data.filename
        if not form.user.data:
            form.user.data = login.current_user
        return super(ImageView, self).create_model(form)

    def update_model(self, form, model):
        if not form.user.data:
            form.__delitem__('user')
        if form.path.data.filename:
            form.name.data = form.path.data.filename
        return super(ImageView, self).update_model(form, model)

    def _list_thumbnail(view, context, model, name):
        if not model.path:
            return ''
        return Markup('%d, (%s)<br/>%s<br/><a href="%s" target="_blank"><img src="%s"></a>' % 
                         (model.id,
                          get_image_size(model),
                          model.path, 
                          util.url_for(model.path),
                          util.url_for_thumb(model.path),
                          ))

    column_formatters = {
        'path': _list_thumbnail
    }

    # Alternative way to contribute field is to override it completely.
    # In this case, Flask-Admin won't attempt to merge various parameters for the field.
    form_extra_fields = {
        'path': ImageUploadField('Image',
                                      base_path=file_path,
                                      thumbnail_size=(100, 100, True),
                                      namegen=uuid_name)
    }


def _get_images_code(images):
    image_code = u''
    for image in images:
        if image == None:
            image = (0, 
                     u'',
                     get_image_size(image), 
                     u'【【指定图片不存在！】】',
                     'http://', 
                     'http://',
                     )
        else:
            image = (image.id, 
                     u'自有' if image.name and image.name.find('youyoumm') >= 0 else u'',  # 图片文件名带有 youyoumm 字样的，是自己拍摄的有版权图片。
                     get_image_size(image), 
                     util.strip_image_note(image.note),
                     util.url_for(image.path), 
                     util.url_for_thumb(image.path),
                     )
        image_code += u'''<td  align="center" valign="top">[id: %d]，%s<br/>(%s)<br/>～%s～<br/><a href="%s" target="_blank"><img src="%s"/></a></td>\n''' % image
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
    column_searchable_list = ('code', 'name', 'name_orig', 'mark', 'address', 'address_orig', 'gate_images', 'top_images', 'note', 'description')
    column_filters = ['id', 'valid', 'order', 'create_time', 'update_time', 'create_user_id', 'update_user_id', 'brand_id', 
                      'logo_id', 'level', 'stars', 'popular',
                      'review_num', 'environment', 'flowrate', 'payment', 'menu', 'ticket', 'tour', 'booking', 'business_hours',
                      'phone', 'transport', 'area_id', 'keywords', 'images_num',
                      ] + list(column_searchable_list)
    form_create_rules = ('valid', 'order', 'note', 'create_time', 'update_time', 'create_user', 'update_user', 'code', 'name', 'name_orig', 
                         'brand', 'logo', 'level', 'stars', 'popular', 'review_num', 'reviews', 'categories',
                         'environment', 'flowrate', 'payment', 'menu', 'ticket', 'tour', 'booking', 'business_hours',
                         'phone', 'transport', 'description', 'longitude', 'latitude', 'area', 'mark', 'address',
                         'address_orig', 'keywords', 'top_images', 'images_num', 'gate_images', 'data_source',
                         )
    column_list = ('id', 
                   'valid', 'order', 'note', 'create_time', 'update_time', 'create_user', 'update_user', 'code', 'name', 'name_orig', 
                   'brand', 'logo', 'level', 'stars', 'popular', 'review_num', 'category',
                   'environment', 'flowrate', 'payment', 'menu', 'ticket', 'tour', 'booking', 'business_hours',
                   'phone', 'transport', 'description', 'longitude', 'latitude', 
                   'country', 'city', 'area', 'mark', 'address',
                   'address_orig', 'keywords', 'top_images', 'images_num', 'gate_images', 'data_source',
                   )
    form_ajax_refs = {
        'create_user': {
            'fields': (User.id,)
        },
        'update_user': {
            'fields': (User.id,)
        },
        'brand': IlikeQueryAjaxModelLoader('brand', db.session, Brand, 
            fields = [Brand.id, Brand.name,]
        ),
        'logo': {
            'fields': (Image.id,)
        },
        'categories': {
            'fields': (Category.id, Category.name)
        },
        'area': {
            'fields': (Area.id, Area.name)
        },
        'fans': {
            'fields': (User.id,)
        },
        'reviews': {
            'fields': (Review.id,)
        },
    }

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

    def _extend_code(self, code_orig, model = None):
        ''' 辅助函数，自动补全 POI 编号。 '''
        id = None if model == None else model.id
        if code_orig and len(code_orig) == 6:
            try:
                site_largest_code = db.session.query(Site).filter(Site.code.ilike(u'{}%'.format(code_orig))).filter(Site.id != id).order_by(Site.id.desc()).first()
                if not site_largest_code:
                    largest_code = 0
                else:
                    largest_code = int(site_largest_code.code[6:])
                # 有时，id 最大的 POI ，并不一定 code 也是最大的，比如有旧的 POI 在后来修改时重新生成过 code。
                while True:
                    code = code_orig[:6] + '{:0>4d}'.format(largest_code + 1)
                    if db.session.query(Site).filter(Site.code == code).filter(Site.id != id).first() == None:
                        return code
                    else:
                        largest_code += 1
            except Exception, e:
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

    before_update_reviews_ids = []
    before_update_gate_images = ''
    before_update_top_images = ''

    def update_model(self, form, model):
        # 记录 model 修改前的计数相关取值
        self.before_update_reviews_ids = [review.id for review in model.reviews]
        self.before_update_gate_images = model.gate_images
        self.before_update_top_images = model.top_images
        # 运营数据例行修正
        if not form.create_user.data:
            form.__delitem__('create_user')
        form.update_user.data = login.current_user
        form.code.data = self._extend_code(form.code.data, model)
        form.business_hours.data = self._replace_full_width_chars(form.business_hours.data)
        form.phone.data = self._replace_full_width_chars(form.phone.data)
        if form.brand.data:
            form.level.data = form.brand.data.level
        return super(SiteView, self).update_model(form, model)

    def after_model_change(self, form, model, is_created):
        # 监控 reviews 的修改，更新计数：
        after_update_reviews_ids = [review.id for review in model.reviews]
        reviews_ids_diff = util.diff_list(self.before_update_reviews_ids, after_update_reviews_ids)
        if reviews_ids_diff:
            util.count_reviews([], [model])
        # 监控 gate_image, top_images, reviews 的修改，更新图片计数：
        after_update_gate_images = model.gate_images
        after_update_top_images = model.top_images
        if self.before_update_gate_images != after_update_gate_images or self.before_update_top_images != after_update_top_images or reviews_ids_diff:
            util.count_images(model)
        return super(SiteView, self).after_model_change(form, model, is_created)

    def get_one(self, id):
        ''' ToDo: 一个脏补丁，用来显示店铺相关的各种图片。但是被迫经常刷新缓存，性能比较差。应该还是通过定制 Form Field 来实现较好。'''
        site = super(SiteView, self).get_one(id)
        columns = []
        for col in self.form_create_rules:
            columns.append(col)
            if col == 'logo':
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

    def _list_business_hours(view, context, model, name):
        return Markup(u'''<table width="300" cellpadding="5"><tr> </tr></table>''') + util.replace_textlib(model.business_hours)

    def _list_ticket(view, context, model, name):
        return Markup(u'''<table width="300" cellpadding="5"><tr> </tr></table>''') + util.replace_textlib(model.ticket)

    def _list_categories(view, context, model, name):
        category_names = []
        try:
            category_names = [cate.name for cate in model.categories]
        except:
            pass
        return Markup(u'''<br/>'''.join(category_names))

    column_formatters = {
        'logo': _list_thumbnail_logo,
        'top_images':_list_thumbnail_top_images,
        'gate_images':_list_thumbnail_gate_images,
        'country':_list_country,
        'city':_list_city,
        'address_orig':_list_address_orig,
        'data_source':_list_data_source,
        'business_hours':_list_business_hours,
        'ticket':_list_ticket,
        'category':_list_categories,    # 不使用 model 默认的 categories 以避免 InvalidRequestError: 'Site.categories' does not support object population - eager loading cannot be applied. 错误。
    }

    def check_code(form, field):
        ''' 检查 POI Code 编码是否符合规范的要求。 '''
        code = field.data or ''
        if len(code) < 6:
            raise validators.ValidationError(u'编号至少需要填写前6位的类别、国家、城市代码！')
        if not code[0] in 'SAREHUL':
            raise validators.ValidationError(u'编号首字母必须以"S A R E H U L"其中一个之一！')
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
        same_code = query.first()
        if same_code:
            raise validators.ValidationError(u'存在 code 重复的 POI 数据 id {}: “{}”，建议检查确认！'.format(same_code.id, same_code.name))

    def check_payment(form, field):
        ''' 检查 Payment 字段是否有不能识别的支付方式代码。'''
        data = field.data or ''
        code_list = data.split()
        for code in code_list:
            if not payment_types.has_key(code.lower()):
                raise validators.ValidationError(u'支付方式代码 {} 不在支持列表内！'.format(code))

    form_args = dict(
        code=dict(validators=[check_code]),
        payment=dict(validators=[check_payment]),
    )


class ReviewView(MyModelView):
    column_default_sort = ('update_time', True)
    column_searchable_list = ('keywords', 'content', 'note')
    column_filters = ['id', 'valid', 'selected', 'published', 'publish_time', 'update_time', 'create_user_id', 'update_user_id', 'user_id',
                      'stars', 'total', 'currency', 'site_id', 'like_num', 'comment_num',
                      ] + list(column_searchable_list)
    form_ajax_refs = {
        'fans': {
            'fields': (User.id,)
        },
        'create_user': {
            'fields': (User.id,)
        },
        'update_user': {
            'fields': (User.id,)
        },
        'user': {
            'fields': (User.id,)
        },
        'site': IlikeQueryAjaxModelLoader('site', db.session, Site, 
            fields = [Site.id, Site.code, Site.name, Site.name_orig]
        ),
        'comments': {
            'fields': (Comment.id,)
        },
    }

    before_update_fans_ids = []
    before_update_comments_ids = []

    def update_model(self, form, model):
        if not model.published and form.published.data and not form.publish_time.data:
            form.publish_time.data = datetime.datetime.now()
        if not form.create_user.data:
            form.__delitem__('create_user')
        form.update_user.data = login.current_user
        # 记录 model 修改前的计数相关取值
        self.before_update_fans_ids = [fan.id for fan in model.fans]
        self.before_update_comments_ids = [comment.id for comment in model.comments]
        return super(ReviewView, self).update_model(form, model)

    def after_model_change(self, form, model, is_created):
        # 保证 images 字段不含有多余空格，以便 filter 时以是否是空字符串来判断是否指定了图片：
        images_str = (model.images or '').strip()
        if model.images != images_str:
            model.images = images_str
            db.session.commit()
        # 监控 comments 的修改，更新计数：
        after_update_comments_ids = [comment.id for comment in model.comments]
        comments_ids_diff = util.diff_list(self.before_update_comments_ids, after_update_comments_ids)
        if comments_ids_diff:
            util.count_comments([], [], [model])
        # 监控 reviews 的修改，更新 POI 星级和计数，以及相关用户账号的计数：
        user = model.user
        site = model.site
        util.count_reviews([user] if user else [], [site] if site else [])
        if site:
            util.count_images(site)
        # 监控 like reviews 的修改，更新计数：
        after_update_fans_ids = [fan.id for fan in model.fans]
        fans_ids_diff = util.diff_list(self.before_update_fans_ids, after_update_fans_ids)
        util.count_likes(db.session.query(User).filter(User.id.in_(fans_ids_diff)).all(), [model])
        return super(ReviewView, self).after_model_change(form, model, is_created)

    def on_model_delete(self, model):
        '''监控 reviews 的删除，更新 POI 星级和计数，以及相关用户账号的计数。'''
        model.valid = False
        db.session.commit()
        user = model.user
        site = model.site
        util.count_reviews([user] if user else [], [site] if site else [])
        if site:
            util.count_images(site)
        return super(ReviewView, self).on_model_delete(model)

    def create_model(self, form):
        if form.published.data and not form.publish_time.data:
            form.publish_time.data = datetime.datetime.now()
        if not form.user.data:
            form.user.data = login.current_user
        form.create_user.data = login.current_user
        form.update_user.data = login.current_user
        return super(ReviewView, self).create_model(form)

    def _list_thumbnail_images(view, context, model, name):
        if not model.images:
            return ''
        return Markup(_get_images_code(util.get_images(model.images, valid_only=False)))
    
    def _list_content(view, context, model, name):
        return Markup(u'''<table width="300" cellpadding="5"><tr> </tr></table>''') + model.content

    column_formatters = {
        'images': _list_thumbnail_images,
        'content':_list_content,
    }


class CommentView(MyModelView):
    column_default_sort = ('update_time', True)
    column_searchable_list = ('content', )
    column_filters = ['id', 'valid', 'publish_time', 'update_time', 'review_id', 'article_id', 'user_id',
                      ] + list(column_searchable_list)
    form_ajax_refs = {
        'review': {
            'fields': (Review.id,)
        },
        'article': {
            'fields': (Article.id,)
        },
        'user': {
            'fields': (User.id,)
        },
    }

    def create_model(self, form):
        if not form.user.data:
            form.user.data = login.current_user
        return super(CommentView, self).create_model(form)

    def after_model_change(self, form, model, is_created):
        '''监控 comments 的修改，更新相关 首页文章、晒单评论（用户账号暂不需要）的子评论计数。'''
        user = model.user
        article = model.article
        review = model.review
        util.count_comments([user] if user else [], [article] if article else [], [review] if review else [])
        return super(CommentView, self).after_model_change(form, model, is_created)

    def on_model_delete(self, model):
        '''监控 comments 的删除，更新相关 首页文章、晒单评论（用户账号暂不需要）的子评论计数。'''
        model.valid = False     # 模拟删除后的效果，以支撑更新计数
        db.session.commit()
        user = model.user
        article = model.article
        review = model.review
        util.count_comments([user] if user else [], [article] if article else [], [review] if review else [])
        return super(CommentView, self).on_model_delete(model)

    def _list_site(view, context, model, name):
        site_info = ''
        try:
            site_info = unicode(model.review.site)
        except:
            pass
        return site_info

    column_list = ('article','site', 'review', 'id', 'valid', 'user', 'at_list', 'content', 'publish_time', 'update_time',
                  )

    column_formatters = {
        'site': _list_site,
    }


class TagAlikeView(MyModelView):
    column_searchable_list = ('name',)
    column_filters = ['id', 'valid', 'order',] + list(column_searchable_list)


class CountryView(TagAlikeView):
    column_searchable_list = ('name',)
    column_filters = ['id', 'valid', 'order', 'extend', 'default_city_id',
                      ] + list(column_searchable_list)
    form_ajax_refs = {
        'default_city': {
            'fields': (City.id, City.name,)
        },
        'cities': {
            'fields': (City.id, City.name,)
        },
        'articles': {
            'fields': (Article.id,)
        },
    }


class CityView(TagAlikeView):
    column_searchable_list = ('name',)
    column_filters = ['id', 'valid', 'order', 'country_id',
                      ] + list(column_searchable_list)
    form_ajax_refs = {
        'country': {
            'fields': (Country.id, Country.name,)
        },
        'areas': {
            'fields': (Area.id, Area.name,)
        },
        'articles': {
            'fields': (Article.id,)
        },
        'tips': {
            'fields': (Tips.id,)
        },
    }


class AreaView(TagAlikeView):
    column_searchable_list = ('name',)
    column_filters = ['id', 'valid', 'order', 'city_id', 'parent_id',
                      ] + list(column_searchable_list)
    form_create_rules = ('city', 'parent', 'children', 'valid', 'order', 'name', 'longitude', 'latitude', 
                        )
    form_edit_rules = form_create_rules
    form_ajax_refs = {
        'city': {
            'fields': (City.id, City.name,)
        },
        'sites': IlikeQueryAjaxModelLoader('sites', db.session, Site, 
            fields = [Site.id, Site.code, Site.name, Site.name_orig]
        ),
        'parent': {
            'fields': (Area.id, Area.name)
        },
    }


class CategoryView(TagAlikeView):
    column_searchable_list = ('name',)
    column_filters = ['id', 'valid', 'order', 'parent_id',
                      ] + list(column_searchable_list)
    form_create_rules = ('parent', 'children', 'valid', 'order', 'name', 
                        )
    form_edit_rules = form_create_rules
    form_ajax_refs = {
        'parent': {
            'fields': (Category.id, Category.name)
        },
        'sites': IlikeQueryAjaxModelLoader('sites', db.session, Site, 
            fields = [Site.id, Site.code, Site.name, Site.name_orig]
        ),
    }


class BrandView(MyModelView):
    column_searchable_list = ('name', 'name_zh', 'description', 'note')
    column_filters = ['id', 'valid', 'order', 'create_time', 'update_time', 'create_user_id', 'update_user_id', 'source', 'level'] + list(column_searchable_list)
    form_ajax_refs = {
        'create_user': {
            'fields': (User.id,)
        },
        'update_user': {
            'fields': (User.id,)
        },
        'sites': IlikeQueryAjaxModelLoader('sites', db.session, Site, 
            fields = [Site.id, Site.code, Site.name, Site.name_orig]
        ),
    }

    def create_model(self, form):
        if not form.create_user.data:
            form.create_user.data = login.current_user
        form.update_user.data = login.current_user
        if form.sites.data:
            for site in form.sites.data:
                site.level = form.level.data
        return super(BrandView, self).create_model(form)

    def update_model(self, form, model):
        if not form.create_user.data:
            form.__delitem__('create_user')
        form.update_user.data = login.current_user
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
    form_ajax_refs = {
        'users': {
            'fields': (User.id,)
        },
    }

    def is_accessible(self):
        return super(RoleView, self).is_accessible() and login.current_user.is_admin()


class UserView(MyModelView):
#    form_excluded_columns = ('icon', 'images', 'created_sites', 'updated_sites', 'created_brands', 'updated_brands', 'share_records', 'reviews', 'comments', 'articles', 'tips', 'read_records', 'sent_messages', 'messages', 'created_textlibs', 'updated_textlibs')       # 出于性能考虑，禁止显示这些涉及大数据量外键的字段。
    form_create_rules = ('valid', 'create_time', 'update_time', 'name', 'username', 'mobile', 'password', 'icon', 
                         'gender', 'level', 'exp', 'follow_num', 'fans_num', 'fans', 'follows', 'like_num',
                         'likes', 'share_num', 'review_num', 'favorite_num', 'favorites', 'badges', 'roles',
                         )
    column_default_sort = None
    column_searchable_list = ('name', 'username', 'mobile')
    column_filters = ['id', 'valid', 'create_time', 'update_time', 'icon_id', 'gender', 'level', 'exp', 'follow_num',
                      'fans_num', 'like_num', 'share_num', 'review_num', 'favorite_num', 'badges',
                      ] + list(column_searchable_list)
    form_ajax_refs = {
        'icon': {
            'fields': (Image.id,)
        },
        'fans': {
            'fields': (User.id,)
        },
        'follows': {
            'fields': (User.id,)
        },
        'likes': {
            'fields': (Review.id,)
        },
        'favorites': IlikeQueryAjaxModelLoader('favorites', db.session, Site, 
            fields = [Site.id, Site.code, Site.name, Site.name_orig]
        ),
        'roles': {
            'fields': (Role.id, Role.name,)
        },
        'images': {
            'fields': (Image.id,)
        },
        'reviews': {
            'fields': (Review.id,)
        },
        'comments': {
            'fields': (Comment.id,)
        },
        'articles': {
            'fields': (Article.id,)
        },
        'tips': {
            'fields': (Tips.id,)
        },
        'sent_announces': {
            'fields': (Announce.id,)
        },
    }

    def is_accessible(self):
        return super(UserView, self).is_accessible() and login.current_user.is_admin()

    before_update_fans_ids = []
    before_update_follows_ids = []
    before_update_likes_ids = []
    before_update_favorites_ids = []
    before_update_badges = []

    def on_model_change(self, form, model, is_created):
        '''
            创建新用户时建立对应的环信账号。
        '''
        if not model.em_username or not model.em_password:
            success, result, username, password = message.prepare_msg_account()
            if not success:
                # ToDo: 这不是一个好的界面设计，最好还是能通过 flash 函数提示用户出错信息，并将用户跳转到信息提交前的界面。
                raise validators.ValidationError(U'Registration on EaseMob failed! %s' % unicode(result))
                return False
            else:
                model.em_username = username
                model.em_password = password
        return super(UserView, self).on_model_change(form, model, is_created)

    def update_model(self, form, model):
        # 记录 model 修改前的计数相关取值
        self.before_update_follows_ids = [follow.id for follow in model.follows]
        self.before_update_fans_ids = [fan.id for fan in model.fans]
        self.before_update_likes_ids = [review.id for review in model.likes]
        self.before_update_favorites_ids = [site.id for site in model.favorites]
        self.before_update_badges = () if not model.badges else model.badges.strip().split()
        return super(UserView, self).update_model(form, model)

    def after_model_change(self, form, model, is_created):
        # 监控 follows 的修改，更新计数：
        after_update_follows_ids = [follow.id for follow in model.follows]
        follows_ids_diff = util.diff_list(self.before_update_follows_ids, after_update_follows_ids)
        follows = []
        fans = []
        if follows_ids_diff:
            follows = [model]
            fans.append(model)
            follows.extend(db.session.query(User).filter(User.id.in_(follows_ids_diff)).all())
        # 监控 fans 的修改，更新计数：
        after_update_fans_ids = [fan.id for fan in model.fans]
        fans_ids_diff = util.diff_list(self.before_update_fans_ids, after_update_fans_ids)
        if fans_ids_diff:
            fans = [model]
            follows.append(model)
            fans.extend(db.session.query(User).filter(User.id.in_(fans_ids_diff)).all())
        util.count_follow_fans(follows, fans)
        # 监控 like reviews 的修改，更新计数：
        after_update_likes_ids = [review.id for review in model.likes]
        likes_ids_diff = util.diff_list(self.before_update_likes_ids, after_update_likes_ids)
        util.count_likes([model], db.session.query(Review).filter(Review.id.in_(likes_ids_diff)))
        # 监控 favorite sites 的修改，更新计数：
        after_update_favorites_ids = [site.id for site in model.favorites]
        favorites_ids_diff = util.diff_list(self.before_update_favorites_ids, after_update_favorites_ids)
        util.count_favorites([model], db.session.query(Site).filter(Site.id.in_(favorites_ids_diff)))
        # 监控 badges 的修改，向用户发送通知：
        after_update_badges = () if not model.badges else model.badges.strip().split()
        badges_diff = util.diff_list_added(self.before_update_badges, after_update_badges)
        for badge in badges_diff:
            util.send_message(323,      # 以运营经理名义发送
                              model.id, 
                              None, 
                              u'由于您在社区中的贡献，授予您勋章“%s”。新的勋章将显示在您的“个人主页”里～' % badge,
                              {'user': model.id,}
                             )
        return super(UserView, self).after_model_change(form, model, is_created)

    def get_one(self, id):
        ''' ToDo: 一个脏补丁，用来显示各种图片。但是被迫经常刷新缓存，性能比较差。应该还是通过定制 Form Field 来实现较好。'''
        user = super(UserView, self).get_one(id)
        columns = []
        for col in self.form_create_rules:
            columns.append(col)
            if col == 'icon':
                if user.icon_id:
                    columns.append(_get_image_rule(u'Icon Image', (user.icon, )))
        self.form_edit_rules = columns
        self._refresh_cache()
        return user


class ShareRecordView(MyModelView):
    column_searchable_list = ('target', )
    column_filters = ['user_id', 'site_id', 'review_id', 'action_time'] + list(column_searchable_list)
    form_ajax_refs = {
        'user': {
            'fields': (User.id,)
        },
        'site': IlikeQueryAjaxModelLoader('site', db.session, Site, 
            fields = [Site.id, Site.code, Site.name, Site.name_orig]
        ),
        'review': {
            'fields': (Review.id,)
        },
        'article': {
            'fields': (Article.id,)
        },
    }

    def is_accessible(self):
        return super(ShareRecordView, self).is_accessible() and login.current_user.is_admin()


class TipsView(MyModelView):
    column_default_sort = ('update_time', True)
    column_searchable_list = ('title', 'content', )
    column_filters = ['id', 'valid', 'default', 'create_time', 'update_time', 'user_id', 'city_id', 'title'] + list(column_searchable_list)
    form_ajax_refs = {
        'user': {
            'fields': (User.id,)
        },
        'city': {
            'fields': (City.id, City.name,)
        },
    }
    column_formatters = {
        'content': _list_content,
    }

    def create_model(self, form):
        if not form.user.data:
            form.user.data = login.current_user
        return super(TipsView, self).create_model(form)


class ArticleView(MyModelView):
    form_create_rules = ('valid', 'order', 'create_time', 'update_time', 'user', 'cities', 'countries', 
                         'title', 'caption', 'content', 'keywords', 'comment_num', 'comments',
                         )
    column_default_sort = ('update_time', True)
    column_searchable_list = ('title', 'keywords', 'content')
    column_filters = ['id', 'valid', 'order', 'create_time', 'update_time', 'user_id', 'caption_id', 'comment_num'] + list(column_searchable_list)
    form_ajax_refs = {
        'user': {
            'fields': (User.id,)
        },
        'cities': {
            'fields': (City.id, City.name,)
        },
        'countries': {
            'fields': (Country.id, Country.name,)
        },
        'caption': {
            'fields': (Image.id,)
        },
        'comments': {
            'fields': (Comment.id,)
        },
    }
    column_formatters = {
        'content': _list_content,
    }

    def create_model(self, form):
        if not form.user.data:
            form.user.data = login.current_user
        return super(ArticleView, self).create_model(form)

    before_update_comments_ids = []

    def update_model(self, form, model):
        # 记录 model 修改前的计数相关取值
        self.before_update_comments_ids = [comment.id for comment in model.comments]
        return super(ArticleView, self).update_model(form, model)

    def after_model_change(self, form, model, is_created):
        # 监控 comments 的修改，更新计数：
        after_update_comments_ids = [comment.id for comment in model.comments]
        comments_ids_diff = util.diff_list(self.before_update_comments_ids, after_update_comments_ids)
        if comments_ids_diff:
            util.count_comments([], [model], [])
        return super(ArticleView, self).after_model_change(form, model, is_created)

    def get_one(self, id):
        ''' ToDo: 一个脏补丁，用来显示各种图片。但是被迫经常刷新缓存，性能比较差。应该还是通过定制 Form Field 来实现较好。'''
        article = super(ArticleView, self).get_one(id)
        columns = []
        for col in self.form_create_rules:
            columns.append(col)
            if col == 'caption':
                if article.caption_id:
                    columns.append(_get_image_rule(u'Caption Image', (article.caption, )))
        self.form_edit_rules = columns
        self._refresh_cache()
        return article


class AnnounceView(MyModelView):
    form_create_rules = ('valid', 'at_once', 'at_login', 'create_time', 'sender_user', 'content',
                         )
    column_default_sort = ('create_time', True)
    column_searchable_list = ('content', )
    column_filters = ['id', 'valid', 'at_once', 'at_login', 'create_time', 'sender_user_id'] + list(column_searchable_list)
    form_ajax_refs = {
        'sender_user': {
            'fields': (User.id,)
        },
    }

    def create_model(self, form):
        if not form.sender_user.data:
            form.sender_user.data = login.current_user
        return super(AnnounceView, self).create_model(form)

    def update_model(self, form, model):
        if not form.sender_user.data:
            form.sender_user.data = login.current_user
        return super(AnnounceView, self).update_model(form, model)

    def after_model_change(self, form, model, is_created):
        # 对 at_once == True 的通知，通知当前还没通知到的用户：
        if model.valid and model.at_once:
            # 下面这个查询性能可能比 select * from  B where (select count(1) as num from A where A.ID = B.ID) = 0 要稍差一点：
            unsent_users = db.session.query(User.id).filter(User.valid == True).outerjoin(Message, and_(User.id == Message.receiver_user_id, Message.announce_id == model.id)).filter(Message.id == None)
            for unsent_user in unsent_users:
                receiver_user_id = unsent_user[0]
                util.send_message(323, receiver_user_id, model.id)  # 以运营经理名义发送
        return super(AnnounceView, self).after_model_change(form, model, is_created)


class LogView(ModelView):
    can_create = False
    can_edit = False
    can_delete = False
    column_display_pk = True
    column_default_sort = ('id', True)
    column_searchable_list = ('before', 'after', 'action', 'model')
    column_filters = ['id', 'action_time', 'user_id', 'model_id',] + list(column_searchable_list)
    form_ajax_refs = {
        'user': {
            'fields': (User.id,)
        },
    }
    
    def is_accessible(self):
        return login.current_user.is_authenticated() and login.current_user.is_admin()


# Create admin
admin = Admin(app, 'Admin', index_view=MyAdminIndexView(), base_template='my_master.html')
admin.add_view(TextLibView(TextLib, db.session))
admin.add_view(TipsView(Tips, db.session))
admin.add_view(ArticleView(Article, db.session))
admin.add_view(SiteView(Site, db.session))
admin.add_view(ReviewView(Review, db.session))
admin.add_view(CommentView(Comment, db.session))
admin.add_view(ImageView(Image, db.session))
admin.add_view(CategoryView(Category, db.session))
admin.add_view(BrandView(Brand, db.session))
admin.add_view(CountryView(Country, db.session))
admin.add_view(CityView(City, db.session))
admin.add_view(AreaView(Area, db.session))
admin.add_view(UserView(User, db.session))
admin.add_view(RoleView(Role, db.session))
admin.add_view(ShareRecordView(ShareRecord, db.session))
admin.add_view(AnnounceView(Announce, db.session))
admin.add_view(LogView(Log, db.session))


