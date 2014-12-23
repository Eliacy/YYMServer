# -*- coding: utf-8 -*-

import json

import flock

from YYMServer import db, app, util
from YYMServer.models import *


def transfer_actions():
    ''' 处理合并用户行为的任务，同时只允许一个实例运行，防止重复处理同一个任务。'''
    with open('/tmp/yym_task_transfer_actions.lock', 'w') as f:
        blocking_lock = flock.Flock(f, flock.LOCK_EX|flock.LOCK_NB)

        try:
            with blocking_lock:
                print 'Got lock and processing transferring actions tasks:'
                for task in db.session.query(Task).filter(Task.processed == False).filter(Task.type == u'transfer_actions').order_by(Task.id):
                    print '* Processing task', task.id, task.type, task.data, ':'
                    data = json.loads(task.data)
                    from_user_id = data.get('from', None)
                    to_user_id = data.get('to', None)
                    if not from_user_id or not to_user_id:
                        continue
                    from_user = db.session.query(User).filter(User.id == from_user_id).first()
                    to_user = db.session.query(User).filter(User.id == to_user_id).first()
                    if not from_user or not to_user:
                        continue
                    # ToDo: 这里的替换有可能出现同一个用户多次 follow 一个账号等情况，不确定这是否会影响用户体验和统计数据。
                    # Comment.user_id :
                    db.session.query(Comment).filter(Comment.user_id == from_user_id).update({'user_id': to_user_id})
                    db.session.commit()
                    # Comment.at_list:
                    for comment in db.session.query(Comment).filter(Comment.at_list.ilike('%{}%'.format(from_user_id))):
                        at_list = util.get_ids_from_str(comment.at_list)
                        at_list_modified = map(lambda x: to_user_id if x == from_user_id else x, at_list)
                        if at_list != at_list_modified:
                            comment.at_list = ' '.join(map(str, at_list_modified))
                            db.session.commit()
                    # Review.user_id :
                    db.session.query(Review).filter(Review.user_id == from_user_id).update({'user_id': to_user_id})
                    db.session.commit()
                    util.count_reviews([from_user, to_user], [])
                    # Review.at_list:
                    for review in db.session.query(Review).filter(Review.at_list.ilike('%{}%'.format(from_user_id))):
                        at_list = util.get_ids_from_str(review.at_list)
                        at_list_modified = map(lambda x: to_user_id if x == from_user_id else x, at_list)
                        if at_list != at_list_modified:
                            review.at_list = ' '.join(map(str, at_list_modified))
                            db.session.commit()
                    # fans.user_id & fans.fan_id:
                    to_user.fans.extend(from_user.fans)
                    from_user.fans = []
                    to_user.follows.extend(from_user.follows)
                    from_user.follows = []
                    util.count_follow_fans([from_user, to_user], [from_user, to_user])
                    # favorites.user_id:
                    to_user.favorites.extend(from_user.favorites)
                    from_user.favorites = []
                    util.count_favorites([from_user, to_user], [])
                    # likes.user_id:
                    to_user.likes.extend(from_user.likes)
                    from_user.likes = []
                    util.count_likes([from_user, to_user], [])
                    # share_record.user_id:
                    to_user.share_records.extend(from_user.share_records)
                    from_user.share_records = []
                    util.count_shares([from_user, to_user], [], [], [])
                    db.session.commit()
                    # message 表没有做迁移。假定消息都能够被及时发出。
                    # token 表不迁移，保留原始登陆数据。
                    task.processed = True
                    db.session.commit()
        except IOError, e:
            print 'Transferring actions tasks have been under processing!'


if __name__ == '__main__':
    transfer_actions()


