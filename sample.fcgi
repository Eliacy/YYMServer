#!/usr/bin/python
import sys
# 以下路径通常需要根据服务器实际路径修改：
# 用于 virtualenv 的：
sys.path.insert(0, '/var/www/youyoumm/lib/python2.7/site-packages')
# 用于载入 Application 自身的：
sys.path.insert(0, '/var/www/youyoumm/YYMServer/flask-hmacauth')
sys.path.insert(0, '/var/www/youyoumm/YYMServer')

from flup.server.fcgi import WSGIServer
from YYMServer import app

# 注意：需要给这个 fcgi 文件用 chmod +x 指令赋予可执行权限！
if __name__ == '__main__':
    WSGIServer(app).run()

