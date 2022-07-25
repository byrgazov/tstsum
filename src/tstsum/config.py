# -*- coding: utf-8 -*-

import funcy as F
import sys, os
import inspect

import ZEO.ClientStorage
import zodburi


def configure_app(app, noisy=False):
    #{ ZODB

    zodb_factory, zodb_kwargs = zodburi.resolve_uri(
        os.environ.get('ZODB_STORAGE', 'zeo://localhost:8100/?connection_pool_size=10&cache_size=100mb')
    )

    zodb_factory_sig = inspect.signature(zodb_factory)
    zodb_kwargs_clean = F.project(zodb_kwargs, (
        param.name
        for param in zodb_factory_sig.parameters
        if param.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    ))

    if noisy:
        # @xxx: жоп@ этот ваш `zodburi`
        for key in zodb_kwargs.keys():
            if key not in zodb_kwargs_clean:
                print('Unknown ZODB parameter: {}'.format(key), file=sys.stderr)

    zodb_factory_bound = zodb_factory_sig.bind_partial(**zodb_kwargs_clean)
    zodb_factory_bound.apply_defaults()
    zodb_kwargs = zodb_factory_bound.arguments.copy()

    app.config.from_mapping(
        ZODB_STORAGE=F.partial(zodb_factory, **zodb_kwargs_clean),
    )

    #{ Minio

    app.config.from_mapping(
        MINIO_ENDPOINT   =os.environ.get('MINIO_ENDPOINT',   'zb1:9091'),
        MINIO_ACCESS_KEY =os.environ.get('MINIO_ACCESS_KEY', 'minioadmin'),
        MINIO_SECRET_KEY =os.environ.get('MINIO_SECRET_KEY', 'minioadmin'),
        MINIO_SECURE     =False,
        MINIO_REGION     =None,
        MINIO_HTTP_CLIENT=None,
    )

    #{ RabbitMQ

    app.config.from_mapping(
        CONEY_BROKER_URI=os.environ.get('CONEY_BROKER_URI', 'amqp://user:password@zb1/sandbox'),
    )
