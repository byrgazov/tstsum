# -*- coding: utf-8 -*-

__all__ = ()

import funcy as F
import datetime

import flask
import werkzeug.local
import minio
import minio.commonconfig
import minio.helpers

from . import errors


MB = 1024 ** 2

DEFAULTS = F.walk_keys(str.lower, {
    'ENDPOINT'   : 'play.minio.io:9000',
    'ACCESS_KEY' : 'Q3AM3UQ867SPQQA43P2F',
    'SECRET_KEY' : 'zuf+tfteSlswRu7BJ86wekitnifILbZam1KYY3TG',
    'SECURE'     : True,
    'REGION'     : None,
    'HTTP_CLIENT': None,
})


CopySource    = minio.commonconfig.CopySource
COPY          = minio.commonconfig.COPY
MAX_PART_SIZE = minio.helpers.MAX_PART_SIZE


def _lookup_minio_connection():
    return flask.current_app.extensions['minio'].connection


connection = werkzeug.local.LocalProxy(_lookup_minio_connection)


def init_app(app):
    assert 'minio' not in app.extensions, \
           'app already initiated for minio'
    app.extensions['minio'] = MinioExtension(app)


def init_storage():
    conn = connection
    if not conn.bucket_exists('tstsum'):
        conn.make_bucket('tstsum')


def check_storage():
    if not connection.bucket_exists('tstsum'):
        raise errors.S3SchemaError('Storage not initialized')


class MinioExtension:
    def __init__(self, app):
        self.config = F.merge(
            DEFAULTS,
            app.config.get_namespace('MINIO_')
        )
        app.teardown_appcontext(self.teardown)

    @property
    def connection(self):
        ctx = flask._app_ctx_stack.top
        if ctx is not None:
            if not hasattr(ctx, 'minio'):
                ctx.minio = self.connect()
            return ctx.minio

    def connect(self):
        return minio.Minio(
            self.config['endpoint'],
            access_key =self.config['access_key'],
            secret_key =self.config['secret_key'],
            secure     =self.config['secure'],
            region     =self.config['region'],
            http_client=self.config['http_client'],
        )

    def teardown(self, exception):
        ctx = flask._app_ctx_stack.top
        if hasattr(ctx, 'minio') and hasattr(ctx.minio, '_http'):
            ctx.minio._http.clear()


def remove_tmp(show_warning=True):
    objects = connection.list_objects('tstsum', '.tmp/')

    now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    expired_after = datetime.timedelta(minutes=60)

    if objects and show_warning:
        print('Warning: directory ".tmp" is not empty')
        for obj in objects:
            print('- [{}] "{}" ({:.1f}MB)'.format(
                obj.last_modified.strftime('%Y-%m-%d %H:%M:%S'),
                obj.object_name,
                obj.size / MB
            ))

    for obj in objects:
        if not obj.is_dir and obj.last_modified + expired_after <= now:
            print('Remove "{}"...'.format(obj.object_name))
            connection.remove_object('tstsum', obj.object_name)
