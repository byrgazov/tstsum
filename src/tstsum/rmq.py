# -*- coding: utf-8 -*-

__all__ = ()

import flask
import flask_coney
import werkzeug.local
import pika.exceptions

from . import errors


MESSAGE_TTL = 5 * 60


def _lookup_coney():
    return flask.current_app.extensions['coney'].coney

coney = werkzeug.local.LocalProxy(_lookup_coney)


def init_app(app):
    flask_coney.Coney(app)


def init_schema():
    with coney.channel() as channel:
        channel.queue_declare(
            queue    ='sum_csv_10',
            arguments={'x-message-ttl': MESSAGE_TTL * 1000},
        )

        """
        channel.exchange_declare(
            exchange     ='sum_csv_10',
            exchange_type='direct',
        )

        channel.exchange_declare(
            exchange     ='sum_csv_10.delayed',
            exchange_type='fanout',
        )

        channel.queue_declare(
            queue    ='sum_csv_10.works',
            arguments={'x-message-ttl': 1000,
                       'x-delivery-count': 100,
                       'x-dead-letter-exchange'   : 'sum_csv_10.delayed',
                       'x-dead-letter-routing-key': 'sum_csv_10.works-delayed'},
#           arguments={'x-message-ttl': MESSAGE_TTL * 1000},
        )

        channel.queue_declare(
            queue    ='sum_csv_10.works-delayed',
            arguments={'x-message-ttl': 5000,
                       'x-dead-letter-exchange'   : 'sum_csv_10',
                       'x-dead-letter-routing-key': 'sum_csv_10.works'},
        )

        channel.queue_bind(
            exchange='sum_csv_10',
            queue   ='sum_csv_10.works',
            routing_key='sum_csv_10.works',
        )

        channel.queue_bind(
            exchange='sum_csv_10.delayed',
            queue   ='sum_csv_10.works-delayed',
            routing_key='sum_csv_10.works-delayed',
        )
        """


def check_schema():
    with coney.channel() as channel:
        try:
            for _ in channel.consume(queue='sum_csv_10', inactivity_timeout=0.02):
                break
        except pika.exceptions.ChannelClosedByBroker as exc:
            raise errors.RMQSchemaError(*exc.args)


def publish(body, routing_key, exchange_name='', durable=False, properties=None):
    coney.publish(
        body         =body,
        routing_key  =routing_key,
        exchange_name=exchange_name,
        durable      =durable,
        properties   =properties,
    )
