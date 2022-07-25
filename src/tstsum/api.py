# -*- coding: utf-8 -*-

__all__ = ()

import funcy    as F
import operator as O
import uuid
import datetime

import flask

from . import errors
from . import minio
from . import rmq
from . import zodb


blueprint = flask.Blueprint('api', 'tstsum')


@blueprint.route('/list_files', methods=['GET'])
def list_files():
    files = []

    for dirobj in minio.connection.list_objects('tstsum', ''):
        if not dirobj.is_dir or dirobj.object_name == '.tmp/':
            continue

        for fileobj in minio.connection.list_objects('tstsum', dirobj.object_name):
            if fileobj.is_dir:
                continue

            files.append({
                'path': fileobj.object_name,
                'time': int(fileobj.last_modified.timestamp()),
                'size': fileobj.size,
            })

    return {'files': files}


@blueprint.route('/estimate_file/<path:filepath>', methods=['GET'])
def estimate_file(filepath):
    columns = ()
    rows_cnt = 0

    response = minio.connection.get_object(
        'tstsum', filepath,
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

    return {'columns_num': len(columns), 'rows_num': rows_cnt}


@blueprint.route('/schedule_work', methods=['POST'])
def schedule_work():
    if flask.request.mimetype == 'application/json':
        filepath = flask.request.json.get('filepath')
    else:
        # multipart/form-data
        # application/x-url-encoded
        # application/x-www-form-urlencoded
        filepath = flask.request.form.get('filepath')

    if filepath is None:
        return {'status': 'error',
                'message': '`filepath` required'}

    try:
        obj = minio.connection.stat_object('tstsum', filepath)
    except errors.S3Error as exc:
        return {'status' : 'error',
                'code'   : exc.code,
                'message': str(exc)}

    work_id = uuid.uuid4().hex
    zodb.root['works'][work_id] = work = zodb.WorkHolder(work_id, obj)
    ctime = work.ctime.timestamp()

    zodb.connection.onCloseCallback(F.partial(
        rmq.publish,
            exchange_name='',
            routing_key  ='sum_csv_10',
            body={
                'work_id' : work_id,
                'filepath': filepath,
                'ctime'   : ctime,
            },
    ))

    import time
    time.sleep(0.2)

    return {'work_id': work_id}


@blueprint.route('/list_works', methods=['GET'])
def list_works():
    works = [{
        'work_id' : getattr(work, 'uid', None),
        'filepath': getattr(work, 'filepath', None),
        'mtime'   : work.mtime.isoformat(),
    } for work in sorted(zodb.root['works'].itervalues(), key=O.attrgetter('mtime'))]
    return {'works': works}


@blueprint.route('/clean_works', methods=['POST'])
def clean_works():
    max_age = 20 * 60
    request = flask.request

    if request.mimetype == 'application/json':
        if 'max_age' in request.json:
            max_age = int(request.json.get('max_age', max_age))
        else:
            max_age = int(request.json.get('max-age', max_age))
    else:
        if 'max_age' in request.form:
            max_age = int(request.form.get('max_age', max_age))
        else:
            max_age = int(request.form.get('max-age', max_age))

    now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    expired_after = datetime.timedelta(seconds=max_age)

    works = zodb.root['works']
    remove_ids = []

    for work in works.itervalues():
        if work.mtime + expired_after <= now:
            remove_ids.append(work.uid)

    for work_id in remove_ids:
        del works[work_id]

    return {'removed': len(remove_ids)}


@blueprint.route('/get_result/<work_id>', methods=['GET'])
def get_result(work_id):
    work = zodb.root['works'].get(work_id)

    if work is None:
        return {'status' : 'error',
                'message': 'unknown `work_id`'}

    return {
        'bucket'  : work.bucket,
        'filepath': work.filepath,
        'status'  : work.status,
        'ctime'   : work.ctime.isoformat(),
        'mtime'   : work.mtime.isoformat(),
        'rows'    : work.rows,
        'columns' : work.columns,
        'results' : [str(value) if isinstance(value, BaseException) else value for value in work.results],
    }
