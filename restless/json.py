import datetime
import six

from decimal import Decimal
from django import http
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils.encoding import force_str


try:
    # json module from python > 2.6
    import json
except ImportError:
    # use packaged django version of simplejson
    from django.utils import simplejson as json

__all__ = [
    'JSONResponse',
    'JSONErrorResponse',
    'HttpError',
    'Http200',
    'Http201',
    'Http400',
    'Http401',
    'Http403',
    'Http404',
    'Http409',
    'Http500',
    'serialize',
    'flatten',
]


class JSONResponse(http.HttpResponse):
    """
    HTTP response with JSON body ("application/json" content type)
    """

    def __init__(self, data, **kwargs):
        """
        Create a new JSONResponse with the provided data (will be serialized to JSON using
        django.core.serializers.json.DjangoJSONEncoder).
        """

        kwargs['content_type'] = 'application/json; charset=utf-8'
        super(JSONResponse, self).__init__(json.dumps(data, cls=DjangoJSONEncoder), **kwargs)


class JSONErrorResponse(JSONResponse):
    """
    HTTP Error response with JSON body ("application/json" content type)
    """

    def __init__(self, reason, **additional_data):
        """
        Create a new JSONErrorResponse with the provided error reason (string) and the optional additional data (will
        be added to the resulting JSON object).
        """
        resp = {'error': reason}
        resp.update(additional_data)
        super(JSONErrorResponse, self).__init__(resp)


class Http200(JSONResponse):
    """HTTP 200 OK"""
    pass


class Http201(JSONResponse):
    """HTTP 201 CREATED"""
    status_code = 201


class Http400(JSONErrorResponse, http.HttpResponseBadRequest):
    """HTTP 400 Bad Request"""
    pass


class Http401(http.HttpResponse):
    """HTTP 401 UNAUTHENTICATED"""
    status_code = 401

    def __init__(self, typ='basic', realm='api', msg='Unauthorized'):
        if typ.lower() != 'basic':
            msg = 'Invalid authorization header'
        super(Http401, self).__init__(msg)
        self['WWW-Authenticate'] = f'{typ.capitalize()} realm="{realm}"'


class Http403(JSONErrorResponse, http.HttpResponseForbidden):
    """HTTP 403 FORBIDDEN"""
    pass


class Http404(JSONErrorResponse, http.HttpResponseNotFound):
    """HTTP 404 Not Found"""
    pass


class Http409(JSONErrorResponse):
    """HTTP 409 Conflict"""
    status_code = 409


class Http500(JSONErrorResponse, http.HttpResponseServerError):
    """HTTP 500 Internal Server Error"""
    pass


class HttpError(Exception):
    """
    Exception that results in returning a JSONErrorResponse to the user.
    """

    def __init__(self, code, reason, **additional_data):
        super(HttpError, self).__init__(self, reason)
        self.response = JSONErrorResponse(reason, **additional_data)
        self.response.status_code = code


def serialize_model(obj, fields=None, include=None, exclude=None, fixup=None):
    include = include or []
    exclude = exclude or []

    fields = list(fields) if fields else [f.name for f in obj._meta.concrete_model._meta.local_fields]
    fields = [f for f in fields if f not in exclude]
    for i in include:
        if isinstance(i, (tuple, six.string_types)):
            fields.append(i)

    # If there are any duplicated items in `fields`, the latter one will override the former one during the following
    # querying of field values.

    data = {}
    for f in fields:
        if isinstance(f, tuple):
            k, v = f
            if callable(v):
                data[k] = v(obj)
            elif isinstance(v, dict):
                data[k] = serialize(getattr(obj, k), **v)
        else:
            v = getattr(obj, f)
            if isinstance(v, (datetime.datetime, datetime.date, datetime.time, Decimal)):
                data[f] = f'{v}'
            else:
                data[f] = force_str(v, strings_only=True)

    if fixup:
        data = fixup(data)

    return data


def serialize(src, fields=None, include=None, exclude=None, fixup=None, query_filter=None):
    """
    Serialize Model or a QuerySet instance to Python primitives.

    By default, all the model fields (and only the model fields) are serialized. If the field is a Python primitive, it
    is serialized as such, otherwise it is converted to string in utf-8 encoding.

    If `fields` is specified, it is a list of attribute descriptions to be serialized, replacing the default (all model
    fields). If `include` is specified, it is a list of attribute descriptions to add to the default list. If `exclude`
    is specified, it is a list of attribute descriptions to remove from the default list.

    Each attribute description can be either:

      * a string - includes a correspondingly named attribute of the object being serialized (eg. `name`, or
        `created_at`); this can be a model field, a property, class variable or anything else that's an attribute on
        the instance

      * a tuple, where the first element is a string key and the second is a function taking one argument - function
        will be run with the object being serialized as the argument, and the function result will be included in the
        result, with the key being the first tuple element

      * a tuple, where the first element is a related model attribute name and the second is a dictionary - related
        model instance(s) will be serialized recursively and added as sub-object(s) to the object being serialized;
        the dictionary may specify `fields`, `include`, `exclude` and `fixup` options for the related models following
        the same semantics as for the object being serialized.

    The `fixup` argument, if defined, is a function taking two arguments, the object being serialized, and the
    serialization result dict, and returning the modified serialization result. It's useful in cases where it's
    necessary to modify the result of the automatic serialization, but its use is discouraged if the same result can
    be obtained through the attribute descriptions.

    Example::

        serialize(obj, fields=[
            'name',   # obj.name
            'dob',    # obj.dob
            ('age', lambda obj: date.today() - obj.dob),
            ('jobs', dict(   # for job in obj.jobs.all()
                fields=[
                    'title',  # job.title
                    'from',   # job.from
                    'to',     # job.to,
                    ('duration', lambda job: job.to - job.from),
                ]
            ))
        ])

    Returns: a dict (if a single model instance was serialized) or a list of dicts (if a QuerySet was serialized) with
    the serialized data. The data returned is suitable for JSON serialization using Django's JSON serializer.
    """

    def subs(subsrc):
        return serialize(subsrc, fields=fields, include=include, exclude=exclude, fixup=fixup,
                         query_filter=query_filter)

    if isinstance(src, (models.Manager, models.query.QuerySet)):
        src = src.filter(query_filter) if query_filter else src.all()
        return [subs(i) for i in src]

    if isinstance(src, (list, set)):
        return [subs(i) for i in src]

    if isinstance(src, dict):
        return {k: subs(v) for k, v in src.items()}

    if isinstance(src, models.Model):
        return serialize_model(src, fields=fields, include=include, exclude=exclude, fixup=fixup)

    return src


def flatten(attname):
    """
    Fixup helper for serialize.

    Given an attribute name, returns a fixup function suitable for serialize() that will pull all items from the
    sub-dict and into the main dict. If any of the keys from the sub-dict already exist in the main dict, they'll
    be overwritten.
    """

    def fixup(data):
        for k, v in data[attname].items():
            data[k] = v
        del data[attname]
        return data

    return fixup
