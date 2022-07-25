# -*- coding: utf-8 -*-

__all__ = ('make_app',)

import sys

import flask
import werkzeug.middleware.proxy_fix

from . import api
from . import config
from . import errors
from . import minio
from . import rmq
from . import web
from . import zodb


def make_wsgi():
    app = make_app()
    app.wsgi_app = werkzeug.middleware.proxy_fix.ProxyFix(
        app.wsgi_app,
        x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1
    )
    return app


def make_app():
    app = flask.Flask('tstsum')
    config.configure_app(app)

    app.register_blueprint(web.blueprint)
    app.register_blueprint(api.blueprint, url_prefix='/api')

    try:
        zodb.init_app(app)
        with app.app_context():
            zodb.check_storage()
    except errors.ZODBSchemaError as exc:
        app.logger.error('ZODB: %s', exc)
        sys.exit(errors.ZODB_SETUP_ERROR)

    try:
        minio.init_app(app)
        with app.app_context():
            minio.check_storage()
    except errors.MinioException as exc:
        app.logger.error('Minio: %s', exc)
        sys.exit(errors.S3_SETUP_ERROR)

    try:
        rmq.init_app(app)
        with app.app_context():
            rmq.check_schema()
    except errors.RMQSchemaError as exc:
        app.logger.error('RabbitMQ: %s', exc)
        sys.exit(errors.RMQ_SETUP_ERROR)

    return app
