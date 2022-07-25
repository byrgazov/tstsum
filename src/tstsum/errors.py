# -*- coding: utf-8 -*-

__all__ = ('MinioException', 'S3Error', 'S3SchemaError', 'ZODBSchemaError', 'RMQSchemaError')

import minio.error


S3_SETUP_ERROR = 5
ZODB_SETUP_ERROR = 6
RMQ_SETUP_ERROR = 7


MinioException = minio.error.MinioException
S3Error = minio.error.S3Error


class S3SchemaError(MinioException):
    pass


class ZODBSchemaError(Exception):
    pass


class RMQSchemaError(Exception):
    def __str__(self):
        return ' '.join(map(str, self.args))  # @todo: `safestr`
