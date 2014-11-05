# -*- coding: utf-8 -*-

import os.path

from YYMServer import db, util, file_path
from YYMServer.models import Image

for image in db.session.query(Image).filter(~Image.path.ilike('qiniu:%')).all():
    full_path = os.path.join(file_path, image.path)
    if image.path and os.path.exists(full_path):
        note = image.note or u''
        if ('[' not in note) or (']' not in note):
            name = image.path
        else:
            leading = u''
            if '[' in note:
                leading = note.split('[')[0]
            ending = u''
            if ']' in note:
                ending = note.split(']')[-1]
            note = leading + ending
            note = note.strip()
            if image.name:
                name = image.name
            else:
                name = image.note or u''
            if '[' in name:
                name = name.split('[')[1]
            if ']' in name:
                name = name.split(']')[0]
        result = util.upload_image(full_path, image.id, image.type, image.user_id or 0, note, name, use_flash=False)
        if type(result) == dict:
            print image.id, result
        else:
            print image.id, result.decode('utf-8')
#        print image.id, image.path, name, note, full_path


