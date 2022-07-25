# -*- coding: utf-8 -*-

__all__ = ()

import funcy as F
import datetime

import flask
import werkzeug.local
import transaction as _transaction
import ZODB
import ZODB.POSException
import BTrees.OOBTree
import persistent

try:
    import zodburi
except ImportError:
    zodburi = None

from . import errors


def _lookup_zodb_root():
    return flask.current_app.extensions['zodb'].root

def _lookup_zodb_connection():
    return flask.current_app.extensions['zodb'].connection


root = werkzeug.local.LocalProxy(_lookup_zodb_root)
connection = werkzeug.local.LocalProxy(_lookup_zodb_connection)


def transaction():
    return flask.current_app.extensions['zodb'].db.transaction()


def init_app(app):
    assert 'zodb' not in app.extensions, \
           'app already initiated for zodb'
    app.extensions['zodb'] = ZODBExtension(app)


def init_storage():
    app = flask.current_app

    with app.extensions['zodb'].db.transaction() as conn:
        if 'works' not in conn.root():
            conn.root()['works'] = BTrees.OOBTree.OOBTree()


def check_storage():
    app = flask.current_app

    with app.extensions['zodb'].db.transaction() as conn:
        if 'works' not in conn.root():
            raise errors.ZODBSchemaError('Storage not initialized')


class ZODBExtension:
    def __init__(self, app):
        assert 'ZODB_STORAGE' in app.config, 'ZODB_STORAGE not configured'

        storage = app.config['ZODB_STORAGE']

        if isinstance(storage, str):
            if zodburi is None:
                raise ModuleNotFoundError('No module named \'zodburi\'')
            factory, dbargs = zodburi.resolve_uri(storage)
        elif isinstance(storage, tuple):
            factory, dbargs = storage
        else:
            factory, dbargs = storage, {}

        self.db = ZODB.DB(factory(), **dbargs)

        app.teardown_request(self.teardown)

    @property
    def is_connected(self):
        return flask.has_request_context() \
           and hasattr(flask._request_ctx_stack.top, 'zodb_connection')

    @property
    def connection(self):
        assert flask.has_request_context(), 'tried to connect zodb outside request'

        if not self.is_connected:
            flask._request_ctx_stack.top.zodb_connection = self.db.open()
            _transaction.begin()

        return flask._request_ctx_stack.top.zodb_connection

    @property
    def root(self):
        return self.connection.root()

    def teardown(self, exception):
        if self.is_connected:
            if exception is None and not _transaction.isDoomed():
                _transaction.commit()
            else:
                _transaction.abort()
            self.connection.close()


class WorkHolder(persistent.Persistent):
    rows    = None
    columns = None  # ('', 'col1', 'col2', ...)
    results = None  # [None | float] * len(columns)

    def __init__(self, uid, obj):
        self.uid = uid
        self.bucket = obj.bucket_name
        self.filepath = obj.object_name
        self.status = 'new'
        self.ctime = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
        self.mtime = self.ctime

    def touch(self):
        self.mtime = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

    def _p_resolveConflict(self, state0, state1, state2):
        state = F.merge(
            F.project(state0, 'uuid bucket filepath ctime columns'.split()),
            F.project(state1, 'uuid bucket filepath ctime columns'.split()),
            F.project(state2, 'uuid bucket filepath ctime columns'.split()),
        )

        if state1['status'] != state2['status']:
            if state1['status'] != state0['status']:
                state['status'] = state1['status']
            else:
                state['status'] = state2['status']
        else:
            state['status'] = state1['status']

        state['mtime'] = max(state1['mtime'], state2['mtime'])

        if state1.get('rows') is not None:
            if state2.get('rows') is not None:
                state['rows'] = max(state1['rows'], state2['rows'])
            else:
                state['rows'] = state1['rows']
        elif 'rows' in state2:
            state['rows'] = state2['rows']

        if state1.get('results') is not None:
            if state2.get('results') is not None:
                results1 = state1['results'][:]
                results2 = state2['results'][:]

                if len(results1) < len(results2):
                    results1 += [None] * (len(results2) - len(results1))
                if len(results2) < len(results1):
                    results2 += [None] * (len(results1) - len(results2))

                results = [None] * len(results1)

                for idx, (value1, value2) in enumerate(zip(results1, results2)):
                    if value1 is not None:
                        value = value2 if value2 is not None else value1
                    else:
                        value = value2
                    results[idx] = value

                state['results'] = results
            else:
                state['results'] = state1['results']
        elif 'results' in state2:
            state['results'] = state2['results']

        return state
