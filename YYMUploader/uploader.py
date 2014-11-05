# -*- coding: utf-8 -*-

import sys

import qiniu.conf

qiniu.conf.ACCESS_KEY = 'WOc4A537RGp5nKavmURZqF1v86h9zjDBJN8R_gfW'
qiniu.conf.SECRET_KEY = 'D9qkmHQ91RXRmD1tMz6AzyLNMMirsUEsNeKulJSZ'

import qiniu.rs

policy = qiniu.rs.PutPolicy('youyoumm')
policy.callbackUrl = 'http://www.youyoumm.com/rpc/images/call'
callback_dic = {
  'type': '4',
  'user': '321',
  'note': u'中文备注',
  'name': '$(fname)',   # 原始文件名这个不靠谱，最好自己存
  'size': '$(fsize)',
  'mime': '$(mimeType)',
  'width': '$(imageInfo.width)',
  'height': '$(imageInfo.height)',
  'hash': '$(etag)',
}
policy.callbackBody = '&'.join(('='.join((key, value)) for key, value in callback_dic.items()))
print policy.callbackBody
#policy.returnBody = '''{
#  "name": $(fname),
#  "size": $(fsize),
#  "mime": $(mimeType),
#  "width": $(imageInfo.width),
#  "height": $(imageInfo.height),
#  "format": $(imageInfo.format),
#  "hash": $(etag),
#  "color": $(exif.ColorSpace.val)
#}'''
uptoken = policy.token()

import qiniu.io

ret, err = qiniu.io.put_file(uptoken, None, '/Users/elias/WorkNow/KeshaQ/server/YYMServer/YYMServer/files/a4ac1e20-b99d-4919-a3ea-2dbe165382db_thumb.jpg')
if err is not None:
    sys.stderr.write('error: %s ' % err)
else:
    print ret

base_url = qiniu.rs.make_base_url('youyoumm.qiniudn.com', 'Fs3dPulKJHwQkXZTBT5LR97KhdDk')
print base_url
policy = qiniu.rs.GetPolicy()
private_url = policy.make_request(base_url)
print private_url
private_url = policy.make_request(base_url + '?imageView2/1/w/20/h/20')
print private_url



