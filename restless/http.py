from django import http
from django.core.serializers.json import DjangoJSONEncoder

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
    'Http500'
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
