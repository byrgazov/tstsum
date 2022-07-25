    # -*- coding: utf-8 -*-

__all__ = ()

import funcy as F
import sys
import time
import json
import csv
import traceback

import pika
import urllib3.exceptions

from . import minio
from . import rmq
from . import zodb


COLUMN_STEP = 10
FAILS_LIMIT = 20
BAD_MSG_TTL = 30


def serve_forever():
    print('Running at {}'.format(time.asctime()))

    fails = []

    def fail_message(delivery_tag, body, message):
        work_id = body['work_id']
        fails.append(work_id)

        print('Fail work `{}`: {} ({}/{})'.format(
            work_id, message, len(fails), FAILS_LIMIT
        ), file=sys.stderr)

        if body.get('ctime', 0) + BAD_MSG_TTL <= time.time():
            fails.remove(work_id)

            print('Work `{}` is too old (ttl {}s)'.format(
                work_id,
                BAD_MSG_TTL,
            ), file=sys.stderr)

            channel.basic_reject(delivery_tag, requeue=False)
        else:
            channel.basic_reject(delivery_tag, requeue=True)
            time.sleep(0.02 * len(fails))

        return len(fails) < FAILS_LIMIT

    while True:
        with rmq.coney.channel() as channel:
            channel.basic_qos(prefetch_count=1)

            for method, props, body in channel.consume(queue='sum_csv_10', inactivity_timeout=5):
                # [pika.exceptions.ChannelClosedByBroker]
                # (406, 'PRECONDITION_FAILED - delivery acknowledgement on channel 1 timed out.
                #        Timeout value used: 1800000 ms. This timeout value can be configured,
                #        see consumers doc guide to learn more')
                if method is None:
                    continue

                assert props.content_type == 'application/json', props.content_type

                body = json.loads(body)
                work_id = body['work_id']

                with zodb.transaction() as conn:
                    work = conn.root()['works'].get(work_id)

                    if work is None:
                        if not fail_message(method.delivery_tag, body, 'not found'):
                            break
                        continue

                    if work.status == 'new':
                        print('New work `{}` (filepath "{}")'.format(work.uid, work.filepath))

                        work.status = 'running'
                        init_work(work)
                        work.touch()

                        conn.onCloseCallback(F.partial(
                            schedule_work_parts,
                            channel    =channel,
                            work_id    =work.uid,
                            columns_num=len(work.columns),
                        ))

                    elif work.status == 'running' and 'column_no' in body:
                        # @xxx: это лучше делать за пределами ZODB-соединения, что бы минимизировать конфликты
                        # @see: L{.zodb.WorkHolder._p_resolveConflict}
                        column_no = body['column_no']
                        try:
                            print('Process column #{} of "{}"'.format(column_no, work.filepath))
                            process_work_column(work, column_no)
                        except urllib3.exceptions.HTTPError as exc:
                            if not fail_message(method.delivery_tag, body, str(exc)):
                                break
                            continue
                        except Exception as exc:
                            traceback.print_exc()
                            if type(work.results) is list and column_no < len(work.results):
                                work.results[column_no] = exc
                        work.touch()

                    else:
                        if not fail_message(method.delivery_tag, body,
                                            'unknown state: status={} body={}'\
                                            .format(work.status, body)):
                            break
                        continue

                if 'column_no' in body:
                    with zodb.transaction() as conn:
                        work = conn.root()['works'].get(work_id)

                        if work.status == 'running':
                            if is_work_done(work):
                                work.status = 'errors' if work_has_errors(work) else 'ok'
                                work.touch()

                channel.basic_ack(method.delivery_tag)
                # [pika.exceptions.ConnectionWrongStateError]
                # BlockingConnection.close(200, 'Normal shutdown') called on closed connection.

        if FAILS_LIMIT <= len(fails):
            sys.exit(1)

        time.sleep(0.333)


def init_work(work):
    offset = 0
    csvbuf = b''
    chunk_size = 8192

    while work.columns is None:
        response = minio.connection.get_object(
            work.bucket, work.filepath,
            offset=offset,
            length=chunk_size,
        )

        try:
            chunk   = response.read()
            csvbuf += chunk
            offset += len(chunk)

            if b'\n' in chunk or len(chunk) < chunk_size:
                csvbuf = csvbuf.split(b'\n', 1)[0].decode()
                csvrow = F.first(csv.reader([csvbuf]))
                work.columns = tuple(csvrow)
        finally:
            response.close()

    assert work.results is None, work.results
    work.results = [None] * len(work.columns)


def schedule_work_parts(channel, work_id, columns_num):
    # @note: первый столбец (column_no=0) пропускается

    ctime = time.time()

    for column_no in range(1, columns_num, COLUMN_STEP):
        channel.basic_publish(
            exchange   ='',
            routing_key='sum_csv_10',
            body=json.dumps({
                'work_id'  : work_id,
                'column_no': column_no,
                'ctime'    : ctime,
            }),
            properties=pika.BasicProperties(content_type='application/json'),
        )


def process_work_column(work, column_no):
    if work.results[column_no] is None:
        data = b''
        chunk_size = 8192
        rows_cnt = 0
        skip_rows = 1
        result = 0.0

        response = minio.connection.get_object(work.bucket, work.filepath)
        try:
            while True:
                chunk = response.read(chunk_size)
                data += chunk

                if b'\n' in chunk or len(chunk) < chunk_size:
                    *rows, tail = data.split(b'\n')

                    if len(chunk) < chunk_size and tail:
                        rows.append(tail)
                    else:
                        data = tail

                    for row in csv.reader(map(bytes.decode, rows)):
                        rows_cnt += 1
                        if 0 < skip_rows:
                            skip_rows -= 1
                            continue
                        result += float(row[column_no])

                if len(chunk) < chunk_size:
                    break
        finally:
            response.close()

        if work.rows is None:
            work.rows = rows_cnt
        work.results[column_no] = result


def is_work_done(work):
    for column_no in range(1, len(work.columns), COLUMN_STEP):
        if work.results[column_no] is None:
            return False
    return True


def work_has_errors(work):
    for column_no in range(1, len(work.columns), COLUMN_STEP):
        value = work.results[column_no]
        if value is not None and not isinstance(value, (int, float)):
            return True
    return False
