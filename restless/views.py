import base64
import binascii
import json
import re
import traceback

from abc import ABC, abstractmethod
from django import VERSION
from django.conf import settings
from django.contrib import auth
from django.core.exceptions import ImproperlyConfigured
from django.core.paginator import Paginator
from django.forms.models import modelform_factory
from django.http import HttpResponse, StreamingHttpResponse
from django.utils.encoding import DjangoUnicodeDecodeError
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View

from .http import Http200, Http201, Http400, Http401, Http403, Http500, HttpError
from .models import serialize

try:
    from django.utils.encoding import smart_str
except ImportError:
    from django.utils.encoding import smart_unicode as smart_str


__all__ = [
    'AbstractAuthMixin',
    'ActionEndpoint',
    'AuthenticateEndpoint',
    'BasicHttpAuthMixin',
    'DetailEndpoint',
    'Endpoint',
    'ListEndpoint',
    'PaginatorMixin',
    'UsernamePasswordAuthMixin',
    'login_required',
]


class PaginatorMixin:
    """
    A simple pagination mixin that can be called simply by self.page(request.page)
    """
    model = ""
    paginate_by = 25

    def _check_for_model(self):
        if not self.model:
            raise ImproperlyConfigured("You must specify a model to use the paginator")
        return True

    def _check_for_pages(self):
        """
        Check for the existence of pages and initialize the Paginator if necessary.

        This function checks if `self.pages` is already set. If not, it initializes the Paginator
        using the specified `model` and `paginate_by` attributes. It returns True if the pages
        exist or have been successfully initialized.

        :return: True if the pages exist or have been successfully initialized.
        :raises ImproperlyConfigured: If `self.model` is not specified.
        :raises Exception: If an error occurs during the initialization of the Paginator.
        """
        if not self.pages:
            self._check_for_model()
            self.pages = Paginator(self.model.objects.all(), self.paginate_by)
            return True

    def page(self, page_num):
        if self._check_for_pages():
            if not isinstance(page_num, int):
                raise ValueError(
                    f"You must specify an integer value for your page number. {page_num} is not a valid number."
                )

            if page_num < 1:
                page_num = 1
            if page_num > self.pages.num_pages:
                page_num = self.pages.num_pages

            return self.pages.page(page_num).object_list


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


def _get_form(form, model):
    if form:
        return form

    if model:
        if VERSION[:2] >= (1, 8):
            return modelform_factory(model, fields='__all__')
        return modelform_factory(model)

    raise NotImplementedError('Form or Model class not specified')


class ListEndpoint(Endpoint):
    """
    List :py:class:`restless.views.Endpoint` supporting getting a list of objects and creating a new one. The endpoint
    exports two view methods by default: get (for getting the list of objects) and post (for creating a new object).

    The only required configuration for the endpoint is the `model` class attribute, which should be set to the model
    you want to have a list (and/or create) endpoints for.

    You can also provide a `form` class attribute, which should be the model form that's used for creating the model.
    If not provided, the default model class for the model will be created automatically.

    You can restrict the HTTP methods available by specifying the `methods` class variable.
    """

    model = None
    form = None
    methods = ['GET', 'POST']
    fields = None
    extra_fields = None

    def get_query_set(self, request, *args, **kwargs):
        """
        Return a QuerySet that this endpoint represents.

        If `model` class attribute is set, this method returns the `all()` queryset for the model. You can override the
        method to provide custom behaviour. The `args` and `kwargs` parameters are passed in directly from the URL
        pattern match.

        If the method raises a :py:class:`restless.http.HttpError` exception, the rest of the request processing is
        terminated and the error is immediately returned to the client.
        """

        if self.model:
            return self.model.objects.all()

        raise HttpError(404, 'Resource Not Found')

    def serialize(self, objs, *args, **kwargs):
        """
        Serialize the objects in the response.

        By default, the method uses the :py:func:`restless.models.serialize` function to serialize the objects with
        default behaviour. Override the method to customize the serialization.
        """

        return serialize(objs, fields=self.fields, include=self.extra_fields, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        """Return a serialized list of objects in this endpoint."""

        if 'GET' not in self.methods:
            raise HttpError(405, 'Method Not Allowed')

        qs = self.get_query_set(request, *args, **kwargs)
        return self.serialize(qs)

    def post(self, request, *args, **kwargs):
        """Create a new object."""

        if 'POST' not in self.methods:
            raise HttpError(405, 'Method Not Allowed')

        form_cls = _get_form(self.form, self.model)
        form = form_cls(request.data or None, request.FILES)
        if form.is_valid():
            obj = form.save()
            return Http201(self.serialize(obj))

        raise HttpError(400, 'Invalid Data', errors=form.errors)


class DetailEndpoint(Endpoint):
    """
    Detail :py:class:`restless.views.Endpoint` supports getting a single object from the database (HTTP GET), updating
    it (HTTP PUT) and deleting it (HTTP DELETE).

    The only required configuration for the endpoint is the `model` class attribute, which should be set to the model
    you want to have the detail endpoints for.

    You can also provide a `form` class attribute, which should be the model form that's used for updating the model.
    If not provided, the default model class for the model will be created automatically.

    You can restrict the HTTP methods available by specifying the `methods` class variable.
    """

    model = None
    form = None
    lookup_field = 'pk'
    fields = None
    extra_fields = None
    methods = ['GET', 'PUT', 'PATCH', 'DELETE']

    def get_instance(self, request, *args, **kwargs):
        """
        Return a model instance represented by this endpoint.

        If `model` is set and the primary key keyword argument is present, the method attempts to get the model with
        the primary key equal to the url argument.

        By default, the primary key keyword argument name is `pk`. This can be overridden by setting the `lookup_field`
        class attribute.

        You can override the method to provide custom behaviour. The `args` and `kwargs` parameters are passed in
        directly from the URL pattern match.

        If the method raises a :py:class:`restless.http.HttpError` exception, the rest of the request processing is
        terminated and the error is immediately returned to the client.
        """

        if self.model and self.lookup_field in kwargs:
            try:
                return self.model.objects.get(**{self.lookup_field: kwargs.get(self.lookup_field)})
            except self.model.DoesNotExist:
                raise HttpError(404, 'Resource Not Found')
        else:
            raise HttpError(404, 'Resource Not Found')

    def get_instance_as_queryset(self, request, *args, **kwargs):
        if self.model and self.lookup_field in kwargs:
            lookup_value = kwargs.get(self.lookup_field)
            result = self.model.objects.filter(**{self.lookup_field: lookup_value})

            count = result.count()
            if count == 0:
                raise HttpError(404, 'Resource Not Found')

            assert count == 1, f'{self.model.__class__.__name__}: {self.lookup_field}:{lookup_value}'
            return result

    def serialize(self, obj):
        """
        Serialize the object in the response.

        By default, the method uses the :py:func:`restless.models.serialize` function to serialize the object with
        default behaviour. Override the method to customize the serialization.
        """

        return serialize(obj, fields=self.fields, include=self.extra_fields)

    def get(self, request, *args, **kwargs):
        """Return the serialized object represented by this endpoint."""

        if 'GET' not in self.methods:
            raise HttpError(405, 'Method Not Allowed')

        return self.serialize(self.get_instance(request, *args, **kwargs))

    def patch(self, request, *args, **kwargs):
        """Update the object represented by this endpoint."""

        if 'PATCH' not in self.methods:
            raise HttpError(405, 'Method Not Allowed')

        queryset = self.get_instance_as_queryset(request, *args, **kwargs)
        values = {}
        fields_names = self.get_fields_names()
        for key, value in request.data.items():
            clean_key = key
            if key.endswith('_id'):
                clean_key = re.sub('_id$', '', key)

            if key in fields_names or clean_key in fields_names:
                values[key] = value

        instance = self.get_instance(request, *args, **kwargs)
        for key, value in values.items():
            setattr(instance, key, value)

        queryset.update(**values)

        return Http200(self.serialize(instance))

    def get_foreign_keys(self):
        fields = []
        for field in self.model._meta.fields:
            class_name = field.__class__.__name__
            if class_name == 'ForeignKey':
                fields.append(field.name)
        return fields

    def get_fields_names(self):
        fields = []
        for field in self.model._meta.fields:
            fields.append(field.name)
        return fields

    def put(self, request, *args, **kwargs):
        """Update the object represented by this endpoint."""

        if 'PUT' not in self.methods:
            raise HttpError(405, 'Method Not Allowed')

        pk = kwargs[self.lookup_field] if self.lookup_field in kwargs else None

        for fk_field in self.get_foreign_keys():
            id_field = f'{fk_field}_id'
            if id_field in request.data:
                request.data[fk_field] = request.data.pop(id_field)

        form_cls = _get_form(self.form, self.model)
        instance = self.get_instance(request, *args, **kwargs)
        form = form_cls(request.data or None, request.FILES, instance=instance)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.pk = pk
            obj.save()
            form.save_m2m()

            if instance:
                return Http200(self.serialize(obj))
            return Http201(self.serialize(obj))

        raise HttpError(400, 'Invalid data', errors=form.errors)

    def delete(self, request, *args, **kwargs):
        """Delete the object represented by this endpoint."""

        if 'DELETE' not in self.methods:
            raise HttpError(405, 'Method Not Allowed')

        instance = self.get_instance(request, *args, **kwargs)
        instance.delete()
        return {}


class ActionEndpoint(DetailEndpoint):
    """
    A variant of :py:class:`DetailEndpoint` for supporting a RPC-style action on a resource. All the documentation for
    DetailEndpoint applies, but only the `POST` HTTP method is allowed by default, and it invokes the
    :py:meth:`ActionEndpoint.action` method to do the actual work.

    If you want to support any of the other HTTP methods with their default behaviour as in DetailEndpoint, just modify
    the `methods` list to include the methods you need.
    """
    methods = ['POST']

    def post(self, request, *args, **kwargs):
        if 'POST' not in self.methods:
            raise HttpError(405, 'Method Not Allowed')

        instance = self.get_instance(request, *args, **kwargs)
        return self.action(request, instance, *args, **kwargs)

    def action(self, request, obj, *args, **kwargs):
        raise HttpError(405, 'Method Not Allowed')
