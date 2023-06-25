import base64
import binascii
import json
import traceback

from abc import ABC, abstractmethod
from django.conf import settings
from django.contrib import auth
from django.http import HttpResponse, StreamingHttpResponse
from django.utils.encoding import DjangoUnicodeDecodeError
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View

from .http import Http200, Http400, Http401, Http403, Http500, HttpError
from .models import serialize

try:
    from django.utils.encoding import smart_str
except ImportError:
    from django.utils.encoding import smart_unicode as smart_str


__all__ = [
    'AbstractAuthMixin',
    'AuthenticateEndpoint',
    'BasicHttpAuthMixin',
    'Endpoint',
    'UsernamePasswordAuthMixin',
    'login_required',
]


def _parse_content_type(content_type):
    if ';' in content_type:
        ct, params = content_type.split(';', 1)
        try:
            params = dict(param.split('=') for param in params.split())
        except ValueError:
            params = {}
    else:
        ct = content_type
        params = {}
    return ct, params


class AbstractAuthMixin(ABC):
    """
    AbstractAuthMixin is an abstract class that defines the interface for authentication mixins.
    Subclasses should implement the authenticate(request) method to provide authentication functionality.
    """

    @abstractmethod
    def authenticate(self, request):
        """
        Authenticates the given request.

        This method should be implemented by subclasses to provide authentication functionality.
        It takes a request object as a parameter and performs authentication based on the request data.

        Args:
            request: The request object representing the incoming request.

        Returns:
            A HttpResponse instance or None indicating the authentication was successful, or other value if failed.
        """
        pass


class UsernamePasswordAuthMixin(AbstractAuthMixin):
    """
    :py:class:`restless.views.Endpoint` mixin providing user authentication based on username and password (as
    specified in "username" and "password" request GET params).
    """

    def authenticate(self, request):
        if request.method == 'POST':
            self.username = request.data.get('username')
            self.password = request.data.get('password')
        else:
            self.username = request.params.get('username')
            self.password = request.params.get('password')

        user = auth.authenticate(username=self.username, password=self.password)
        if user is None or not user.is_active:
            return Http401(msg='Invalid credentials')
        auth.login(request, user)


# Taken from Django Rest Framework
class BasicHttpAuthMixin(AbstractAuthMixin):
    """
    :py:class:`restless.views.Endpoint` mixin providing user authentication based on HTTP Basic authentication.
    """

    def authenticate(self, request):
        if 'Authorization' not in request.headers:
            return Http401(realm='Restricted Area')

        authdata = request.headers['Authorization'].split()
        if len(authdata) != 2 or authdata[0].lower() != 'basic':
            return Http401(typ=authdata[0])

        try:
            raw = authdata[1].encode('ascii')
            auth_parts = base64.b64decode(raw).split(b':')
            uname, passwd = (smart_str(auth_parts[0]), smart_str(auth_parts[1]))
        except (binascii.Error, DjangoUnicodeDecodeError, UnicodeError):
            return Http401(msg='Failed to read credentials')

        user = auth.authenticate(username=uname, password=passwd)
        if user is None or not user.is_active:
            return Http401(msg='Invalid credentials')

        # We don't use auth.login(request, user) because may be running without session
        request.user = user


def login_required(fn):
    """
    Decorator for :py:class:`restless.views.Endpoint` methods to require authenticated, active user. If the user isn't
    authenticated, HTTP 403 is returned immediately (HTTP 401 if Basic HTTP authentication is used).
    """

    def wrapper(self, request, *args, **kwargs):
        if request.user is not None and request.user.is_active:
            return fn(self, request, *args, **kwargs)
        return Http403('forbidden')

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


class Endpoint(View):
    """
    Class-based Django view that should be extended to provide an API endpoint (resource). To provide GET, POST, PUT,
    HEAD or DELETE methods, implement the corresponding get(), post(), put(), head() or delete() method, respectively.

    If you also extend AbstractAuthMixin class, the authenticate(request) method will be called before the main method
    to provide authentication, if needed. Auth mixins use this to provide authentication.

    The usual Django "request" object passed to methods is extended with a few more attributes:

      * request.content_type - the content type of the request
      * request.params - a dictionary with GET parameters
      * request.page - an integer representation of the page number
      * request.data - a dictionary with POST/PUT parameters, as parsed from either form submission or submitted
            application/json data payload
      * request.raw_data - string containing raw request body

    The view method should return either a HTTPResponse (for example, a redirect), or something else (usually a
    dictionary or a list). If something other than HTTPResponse is returned, it is first serialized into
    :py:class:`restless.http.JSONResponse` with a status code 200 (OK), then returned.

    The authenticate(request) method should return either a HttpResponse, which will shortcut the rest of the request
    handling (the view method will not be called), or None (the request will be processed normally).

    Both methods can raise a :py:class:`restless.http.HttpError` exception instead of returning a HttpResponse, to
    shortcut the request handling and immediately return the error to the client.
    """

    def _parse_body(self, request):
        if request.method not in ['POST', 'PUT', 'PATCH']:
            return

        ct, ct_params = _parse_content_type(request.content_type)
        if ct == 'application/json':
            charset = ct_params.get('charset', 'utf-8')
            try:
                request.data = json.loads(request.body.decode(charset))
            except Exception as ex:
                raise HttpError(400, 'invalid JSON payload: %s' % ex)
        elif (ct == 'application/x-www-form-urlencoded') or (ct.startswith('multipart/form-data')):
            request.data = dict((k, v) for (k, v) in request.POST.items())
        else:
            request.data = request.body

    def _process_authenticate(self, request):
        if isinstance(self, AbstractAuthMixin):
            auth_response = self.authenticate(request)
            if isinstance(auth_response, HttpResponse):
                return auth_response
            if auth_response is not None:
                raise TypeError('authenticate method must return HttpResponse instance or None')

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        if not hasattr(request, 'content_type'):
            request.content_type = request.headers.get('content-type', 'text/plain')
        request.params = dict((k, v) for (k, v) in request.GET.items())
        request.data = None
        request.raw_data = request.body

        if 'page' in request.params:
            page = request.params.get('page')
            try:
                request.page = int(page)
            except ValueError:
                return Http400(f"{page} is not a valid page number. Please only use an integer value only.")

        try:
            self._parse_body(request)
            authentication_required = self._process_authenticate(request)
            if authentication_required:
                return authentication_required

            response = super(Endpoint, self).dispatch(request, *args, **kwargs)
        except HttpError as err:
            response = err.response
        except Exception as ex:
            if settings.DEBUG:
                response = Http500(str(ex), traceback=traceback.format_exc())
            else:
                raise

        if isinstance(response, (HttpResponse, StreamingHttpResponse)):
            return response
        return Http200(response)


class AuthenticateEndpoint(Endpoint, UsernamePasswordAuthMixin):
    """
    Session-based authentication API endpoint. Provides GET and POST method for authenticating the user based on
    passed-in "username" and "password" request params. On successful authentication, the method returns authenticated
    user details.

    Uses :py:class:`UsernamePasswordAuthMixin` to actually implement the Authentication API endpoint.

    On success, the user will get a response with their serialized User object, containing id, username, first_name,
    last_name and email fields.
    """

    user_fields = ('id', 'username', 'first_name', 'last_name', 'email')

    @login_required
    def get(self, request):
        return Http200(serialize(request.user, fields=self.user_fields))

    @login_required
    def post(self, request):
        return Http200(serialize(request.user, fields=self.user_fields))
