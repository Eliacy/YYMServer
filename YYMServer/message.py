# -*- coding: utf-8 -*-

import shortuuid

from YYMServer import app, easemob


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


em = EaseMob()

def prepare_msg_account():
    ''' 辅助函数：尝试注册环信用户，如果成功则返回环信用户名和密码。'''
    i = 0
    while i < 3:
        i += 1
        username = shortuuid.uuid()
        password = shortuuid.uuid()
        success, result = em.register_new_user(username, password)
        if success:
            return (success, result, username, password)

if __name__ == '__main__':
    em = EaseMob()
    success, result = em.register_new_user('test', 'test')
    print success
    print result


