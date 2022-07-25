# -*- coding: utf-8 -*-

__all__ = ()

import uuid
import flask

from . import api
from . import zodb


blueprint = flask.Blueprint('web', 'tstsum')


@blueprint.route('/', methods=['GET'])
def index():
    return flask.make_response(
        '/api/list_files\n'   \
        '/api/schedule_work\n'\
        '/api/list_works\n'   \
        '/api/work_result',
        {'Content-Type': 'text/plain'})
