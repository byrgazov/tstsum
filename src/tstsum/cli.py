# -*- coding: utf-8 -*-

__all__ = ()

import itertools as I
import sys, os, io
import time
import random
import threading
import csv
import secrets

import click
import flask

from . import config
from . import errors
from . import minio
from . import rmq
from . import svcsum
from . import zodb


KB = 1024
MB = 1024 ** 2


@click.group()
def main():
    pass


@main.command()
def init():
    app = flask.Flask('tstsum')
    config.configure_app(app)

    zodb.init_app(app)
    minio.init_app(app)
    rmq.init_app(app)

    with app.app_context():
        zodb.init_storage()
        minio.init_storage()
        rmq.init_schema()

    click.echo('Ok')


@main.command()
def service_sum():
    app = flask.Flask('tstsum')
    config.configure_app(app)

    zodb.init_app(app)
    minio.init_app(app)
    rmq.init_app(app)

    with app.app_context():
        zodb.check_storage()
        minio.check_storage()
        rmq.check_schema()
        svcsum.serve_forever()


@main.command()
@click.option('--columns', type=int, required=True)
@click.option('--rows', type=int, required=True)
def generate_csv(columns, rows):
    filename = secrets.token_urlsafe() + '.csv'
    filepath = '/'.join((filename[:3].lower(), filename))
    filepath_tmp = '.tmp/' + filename
    filesize = None

    app = flask.Flask('tstsum')
    config.configure_app(app)

    with app.app_context():
        minio.remove_tmp()

    if rows and columns:
        print('Generating file "{}" ({}x{})... '.format(filepath, columns, rows), end='')
        sys.stdout.flush()

    iotmp = io.StringIO()
    fdrd, fdwr = os.pipe()
    ford = os.fdopen(fdrd, 'rb')
    fowr = os.fdopen(fdwr, 'w', encoding='utf8', buffering=256 * KB)

    writer = csv.writer(iotmp)
    writer.writerow(I.chain(
        [''],
        map('col{}'.format, range(1, columns + 1))
    ))

    def s3_writer(frd):
        try:
            with app.app_context():
                minio.connection.put_object(
                    'tstsum', filepath_tmp,
                    data     =frd,
                    content_type='text/csv',
                    length   =-1,
                    part_size=10 * MB,
                )
        finally:
            frd.close()

    writer_thread = threading.Thread(target=s3_writer, args=(ford,), name='S3 Writer')
    writer_thread.daemon = True

    if rows and columns:
        writer_thread.start()

    progress_line = ''
    progress_message = ''
    progress_size = 0
    rowno = 0

    def show_progress(message=None):
        nonlocal progress_line
        nonlocal progress_message

        prev_progress_line = progress_line

        print('\x08' * len(progress_line), end='')
        progress_line = '{:d}% ({:.1f}MB)'.format(int(rowno / rows * 100), progress_size / MB)

        if message:
            progress_message = message
            progress_line += ' {}'.format(message)
        elif progress_message:
            progress_line += ' {}'.format(progress_message)

        print(progress_line, end='')

        tail_spaces = ' ' * max(0, len(prev_progress_line) - len(progress_line))
        if tail_spaces:
            print(tail_spaces + '\x08' * len(tail_spaces), end='')

        sys.stdout.flush()

    time1 = time.time()

    try:
        for rowno in range(1, rows + 1):
            time2 = time.time()

            if 0.5 <= time2 - time1:
                time1 = time2
                show_progress()

            writer.writerow(I.chain(
                [time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time2))],
                (random.random() for _ in range(columns))
            ))

            if minio.MAX_PART_SIZE < progress_size + iotmp.tell():
                show_progress('Break')
                break

            fowr.write(iotmp.getvalue())
            progress_size += iotmp.tell()
            iotmp.seek(0)
            iotmp.truncate()
    except Exception:
        show_progress('Error')
        print()
        raise
    except KeyboardInterrupt:
        progress_line += '^C'  # @xxx: ^C
        show_progress('Break')
    finally:
        iotmp.close()
        fowr.close()
        if writer_thread.is_alive():
            writer_thread.join()
        ford.close()

    if rows and columns:
        with app.app_context():
            # @xxx: не особо быстро работает
            # @error: 100x3_000_000 -> [ValueError] sources must be non-empty list or tuple type
            #         `copy_object` -> In this API maximum supported source object size is 5GiB.
            #         `copy_object` -> COPY metadata directive is not applicable to source object size greater than 5 GiB
            show_progress(progress_message or 'Finishing')
            try:
                minio.connection.copy_object(
                    'tstsum', filepath, minio.CopySource('tstsum', filepath_tmp),
                    metadata_directive=minio.COPY,
                    tagging_directive =minio.COPY)
                minio.connection.remove_object('tstsum', filepath_tmp)
            except Exception as exc:
                show_progress('Error')
                print()
                if isinstance(exc, errors.S3Error) and exc.code != 'NoSuchKey':
                    raise
                print(exc, file=sys.stderr)
            else:
                filesize = minio.connection.stat_object('tstsum', filepath).size

    if filesize is not None:
        progress_size = filesize
        show_progress()
