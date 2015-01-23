# -*- coding: utf-8 -*-

import codecs
import json
import os
import requests
import time

import flock
import shortuuid

from YYMServer import db, app, easemob, util
from YYMServer.models import Message


org_name = app.config['EASEMOB_ORG']
app_name = app.config['EASEMOB_APP']
client_id = app.config['EASEMOB_CLIENT_ID']
client_secret = app.config['EASEMOB_CLIENT_SECRET']


class EaseMob(object):
    org = org_name
    app = app_name
    client_id = client_id
    client_secret = client_secret
    app_client_auth = easemob.AppClientAuth(org_name, app_name, client_id, client_secret)
    # ToDo: EaseMob 的所有接口，都没有对连接出错的情况下的超时做处理。因此有可能由于超时导致相关调用很久很久很久才有响应！这不是一种友好的 api 设计。

    def register_new_user(self, username, password):
        ''' 使用指定的环信用户名、密码，在环信服务上注册聊天账号。'''
        try:
            success, result = easemob.register_new_user(self.org, self.app, self.app_client_auth, username, password)
        except Exception, e:
            success = False
            result = unicode(e)
        return (success, result)

    def send_message(self, sender, receivers, msg, ext={}):
        '''
        自行封装的环信发送文本消息接口调用，参考文档：http://www.easemob.com/docs/rest/sendmessage/#sendmsg 。
        '''
        source = ''
        target = []
        if sender:
            source = '' if not sender.em_username else sender.em_username
        if receivers:
            for receiver in receivers:
                if receiver.em_username:
                    target.append(receiver.em_username)
        url = easemob.EASEMOB_HOST + ('/%s/%s/messages' % (self.org, self.app))
        payload = {'target_type': 'users',
                   'target': target,
                   'msg': {'type': 'txt',
                           'msg': msg,
                          },
                   'from': source,
                   'ext': ext,
                  }
        try:
            body = json.dumps(payload, ensure_ascii=False).encode('utf8')
            r = requests.post(url, data=body, auth=self.app_client_auth, timeout=5)
            return easemob.http_result(r)
        except Exception, e:
            success = False
            result = unicode(e)
        return (success, result)

    def export_messages(self, limit=100, cursor=None, start_time=None, end_time=None):
        '''
        自行封装的环信历史消息导出接口，参考文档：http://www.easemob.com/docs/rest/chatmessage/ 。
        '''
        url = easemob.EASEMOB_HOST + ('/%s/%s/chatmessages' % (self.org, self.app))
        params = {'limit': limit,}
        if cursor:
            params['cursor'] = cursor
        time_range = []
        if start_time:
            time_range.append('timestamp>%d' % start_time)
        if end_time:
            time_range.append('timestamp<%d' % end_time)
        if time_range:
            params['ql'] = 'select * where %s' % ' and '.join(time_range)
        payload = {}
        try:
            body = json.dumps(payload, ensure_ascii=False).encode('utf8')
            r = requests.get(url, params=params, auth=self.app_client_auth, timeout=5)
            return easemob.http_result(r)
        except Exception, e:
            success = False
            result = unicode(e)
        return (success, result)


em = EaseMob()
_alphabet = shortuuid.get_alphabet()
shortuuid_lowercase = shortuuid.ShortUUID(alphabet=_alphabet.lower())

def prepare_msg_account():
    ''' 辅助函数：尝试注册环信用户，如果成功则返回环信用户名和密码。'''
    i = 0
    while i < 3:
        i += 1
        username = shortuuid_lowercase.uuid()   # 环信在很多接口其实会自动进行小写转换，所以统一使用小写字母更为安全
        password = shortuuid.uuid()
        success, result = em.register_new_user(username, password)
        if success:
            return (success, result, username, password)
    # ToDo: 创建失败应该写日志记录原因
    return (False, u'', u'', u'')

def send_message(sender, receivers, msg, ext={}):
    ''' 辅助函数：发送环信纯文本消息。'''
    i = 0
    while i < 3:
        i += 1
        success, result = em.send_message(sender, receivers, msg, ext)
        if success:
            return (success, result)
    # ToDo: 消息发送失败应该写日志记录原因
    return (False, u'')

def _export_messages(limit=100, cursor=None, start_time=None, end_time=None):
    '''
    辅助函数：导出环信历史数据。封装底层 API 提高健壮性。
    '''
    i = 0
    while i < 3:
        i += 1
        success, result = em.export_messages(limit, cursor, start_time, end_time)
        if success:
            return (success, result)
    # ToDo: 消息发送失败应该写日志记录原因
    return (False, u'')

def export_messages(dir_path):
    '''
    导出环信历史数据到指定目录，以文件名作为上次导出进度的时间戳。
    '''
    if not os.path.exists(dir_path):
        os.mkdir(dir_path)
    last_timestamp = 0
    for filename in os.listdir(dir_path):
        if filename.isdigit():
            timestamp = long(filename)
            if timestamp > last_timestamp:
                last_timestamp = timestamp
    cursor = None
    latest_timestamp = 0
    result_list = []
    while True:
        success, result = _export_messages(cursor = cursor, start_time = last_timestamp)
        if success:
            new_timestamp = result['timestamp']
            if new_timestamp > latest_timestamp:
                latest_timestamp = new_timestamp
            cursor = None if not result.has_key('cursor') else result['cursor']
            count = result['count']
            print '*', count, 'messages downloaded.'
            if count > 0:
                result_list.append(result)
            if cursor == None:
                break
        else:
            break
    if len(result_list) > 0:
        with codecs.open(os.path.join(dir_path, str(latest_timestamp)), 'w', 'utf-8') as file:
            # ToDo: 这里的实现机制是一次备份的数据一次性写入，在消息特别特别多的情况下，有可能造成服务器内存压力。那时可以考虑一天执行多次消息导出脚本，从而降低每次导出的消息数量来缓解内存压力。
            file.write(json.dumps(result_list, ensure_ascii=False))

def group(seq, size):
    ''' 按指定的步长分批读取 seq 中的元素。'''
    def take(seq, n):
        for i in xrange(n):
            yield seq.next()

    if not hasattr(seq, 'next'):
        seq = iter(seq)

    while True:
        x = list(take(seq, size))
        if x:
            yield x
        else:
            break

def check_msg_queue():
    ''' 检查环信消息发送队列，发出待发送的消息。'''
    with open('/tmp/yym_check_msg_queue.lock', 'w') as f:
        blocking_lock = flock.Flock(f, flock.LOCK_EX|flock.LOCK_NB)

        try:
            with blocking_lock:
                print 'Got lock and checking messages queue:'
                announce_id_groups = db.session.query(Message.announce_id, Message.sender_user_id, Message.content, Message.ext).filter(Message.pushed == False).group_by(Message.announce_id, Message.sender_user_id, Message.content, Message.ext).order_by(Message.announce_id.desc()).all()
                for announce_id_group in announce_id_groups:
                    announce_id, sender_user_id, content, ext = announce_id_group
                    query = db.session.query(Message).filter(Message.pushed == False).filter(Message.announce_id == announce_id).filter(Message.sender_user_id == sender_user_id).filter(Message.content == content).filter(Message.ext == ext).order_by(Message.id.desc())
                    messages_groups = group(query, 20)
                    for messages_group in messages_groups:
                        messages = messages_group
                        message = messages[0]
                        sender = util.get_info_user(message.sender_user_id)
                        receivers = util.get_info_users(map(lambda message: message.receiver_user_id, messages))
                        if message.announce_id:
                            announce = util.get_info_announce(message.announce_id)
                            msg = u'' if not announce else announce.content
                        else:
                            msg = message.content
                        ext = json.loads(message.ext)
                        resp = send_message(sender, receivers, msg, ext)
                        # 记录发送状态
                        success, result = resp
                        if success:
                            for message in messages:
                                message.pushed = True
                            db.session.commit()
                            print '* Sent messages:', ' '.join(map(lambda x: str(x.id), messages))
        except IOError, e:
            print 'Checking messages queue job has been under processing!'

if __name__ == '__main__':
    em = EaseMob()
#     success, result = em.register_new_user('test', 'test')
#     print success
#     print result
#     success, result = _export_messages()
#     print success
#     print result
    export_messages('/Users/elias/tmp/FormatterKit-master')


