# -*- coding: utf-8 -*-

from flask import request, url_for, escape

from YYMServer import app, db, cache, api, util
from YYMServer.models import *


@app.route('/share/articles/<token>')
def show_shared_articles(token):
    # 显示通过指定 token 共享出来的首页文章：
    article = db.session.query(Article).filter(Article.valid == True).join(ShareRecord, ShareRecord.article_id == Article.id).filter(ShareRecord.token == token).first()
    return escape(unicode(article))

@app.route('/share/sites/<token>')
def show_shared_sites(token):
    # 显示通过指定 token 共享出来的 POI ：
    site = db.session.query(Site).filter(Site.valid == True).join(ShareRecord, ShareRecord.site_id == Site.id).filter(ShareRecord.token == token).first()
    return escape(unicode(site))

@app.route('/share/reviews/<token>')
def show_shared_reviews(token):
    # 显示通过指定 token 共享出来的 晒单评论：
    review = db.session.query(Review).filter(Review.valid == True).join(ShareRecord, ShareRecord.review_id == Review.id).filter(ShareRecord.token == token).first()
    return escape(unicode(review))


