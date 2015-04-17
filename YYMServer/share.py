# -*- coding: utf-8 -*-

from flask import request, url_for, escape, render_template

from YYMServer import app, db, cache, api, util, rpc
from YYMServer.models import *


@cache.memoize()
def _get_shared_article_id(token):
    ''' 本函数封装数据库查询给出的基础结果，在客户端频繁访问时减少数据库查询次数。'''
    result = db.session.query(Article.id).filter(Article.valid == True).join(ShareRecord, ShareRecord.article_id == Article.id).filter(ShareRecord.token == token).first()
    article_id = None if result is None else result[0]
    return article_id

@app.route('/share/articles/<token>')
def show_shared_articles(token):
    # 显示通过指定 token 共享出来的首页文章：
    article_id = _get_shared_article_id(token)
    article = rpc.get_info_article(article_id)
    if article is None:
        return escape(u'系统中不存在您指定的共享信息。')
    comment_ids = rpc.get_comments_id(0l, article_id, 0l)
    comments = rpc.get_info_comments(comment_ids, valid_only = True)
    return render_template('share/article.html', article=article, comments=comments, util=util)

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
    review_ids = rpc.get_reviews_id(None, True, 0l, site_id, 0l, 0l, 0l)
    reviews = rpc.get_info_reviews(review_ids, valid_only = True, brief = True, token = None)
    return render_template('share/site.html', site=site, reviews=reviews, util=util)

@cache.memoize()
def _get_shared_review_id(token):
    ''' 本函数封装数据库查询给出的基础结果，在客户端频繁访问时减少数据库查询次数。'''
    result = db.session.query(Review.id).filter(Review.valid == True).join(ShareRecord, ShareRecord.review_id == Review.id).filter(ShareRecord.token == token).first()
    review_id = None if result is None else result[0]
    return review_id

@app.route('/share/reviews/<token>')
def show_shared_reviews(token):
    # 显示通过指定 token 共享出来的 晒单评论：
    review_id = _get_shared_review_id(token)
    review = rpc.get_info_review(review_id)
    if review is None:
        return escape(u'系统中不存在您指定的共享信息。')
    comment_ids = rpc.get_comments_id(0l, 0l, review_id)
    comments = rpc.get_info_comments(comment_ids, valid_only = True)
    return render_template('share/review.html', review=review, comments=comments, util=util)


