# -*- coding: utf-8 -*-

from flask import request, url_for, escape, render_template

from YYMServer import app, db, cache, api, util, rpc
from YYMServer.models import *


@app.route('/share/articles/<token>')
def show_shared_articles(token):
    # 显示通过指定 token 共享出来的首页文章：
    article = db.session.query(Article).filter(Article.valid == True).join(ShareRecord, ShareRecord.article_id == Article.id).filter(ShareRecord.token == token).first()
    return escape(unicode(article))

@cache.memoize()
def _get_shared_site_id(token):
    ''' 本函数封装数据库查询给出的基础结果，在客户端频繁访问时减少数据库查询次数。'''
    result = db.session.query(Site.id).filter(Site.valid == True).join(ShareRecord, ShareRecord.site_id == Site.id).filter(ShareRecord.token == token).first()
    site_id = None if result is None else result[0]
    return site_id

@app.route('/share/sites/<token>')
def show_shared_sites(token):
    # 显示通过指定 token 共享出来的 POI ：
    site_id = _get_shared_site_id(token)
    site = util.get_info_site(site_id)
    if site is None:
        return escape(u'系统中不存在您指定的共享信息。')
    reviews_id = rpc.get_reviews_id(None, True, 0l, site_id, 0l, 0l, 0l)
    reviews = rpc.get_info_reviews(reviews_id, valid_only = True, brief = True, token = None)
    return render_template('share/site.html', site=site, reviews=reviews, util=util)

@app.route('/share/reviews/<token>')
def show_shared_reviews(token):
    # 显示通过指定 token 共享出来的 晒单评论：
    review = db.session.query(Review).filter(Review.valid == True).join(ShareRecord, ShareRecord.review_id == Review.id).filter(ShareRecord.token == token).first()
    return escape(unicode(review))


