# -*- coding: utf-8 -*-

import sys
import os.path

sys.path.insert(0, os.path.join(os.path.split(os.path.realpath(__file__))[0], 'flask-hmacauth'))

from YYMServer import app
app.run(host='0.0.0.0', threaded=True, debug=True)


