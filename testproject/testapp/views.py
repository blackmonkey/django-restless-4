import base64

from restless.http import Http201, Http400, Http403, Http404, HttpError
from restless.models import serialize
from restless.views import AbstractAuthMixin, AuthenticateEndpoint, BasicHttpAuthMixin, Endpoint, login_required
from restless.modelviews import ListEndpoint, DetailEndpoint, ActionEndpoint

from .forms import AuthorForm
from .models import Author, Book, Publisher

__all__ = [
    'AuthorList',
    'AuthorDetail',
    'BookDetail',
    'EchoView',
    'ErrorRaisingView',
    'FailsIntentionally',
    'PublisherAction',
    'PublisherAutoDetail',
    'PublisherAutoList',
    'ReadOnlyPublisherAutoList',
    'TestBasicAuth',
    'TestCustomAuthMethod',
    'TestLogin',
    'WildcardHandler',
]


class AuthorList(Endpoint):
    def get(self, request):
        return serialize(Author.objects.all())

    def post(self, request):
        form = AuthorForm(request.data)
        if form.is_valid():
            author = form.save()
            return Http201(serialize(author))
        return Http400(reason='invalid author data', details=form.errors)


class AuthorDetail(Endpoint):
    def get(self, request, author_id=None):
        author_id = int(author_id)
        try:
            return serialize(Author.objects.get(id=author_id))
        except Author.DoesNotExist:
            return Http404(reason='no such author')

    def delete(self, request, author_id=None):
        author_id = int(author_id)
        Author.objects.get(id=author_id).delete()
        return 'ok'

    def put(self, request, author_id=None):
        author_id = int(author_id)
        try:
            author = Author.objects.get(id=author_id)
        except Author.DoesNotExist:
            return Http404(reason='no such author')

        form = AuthorForm(request.data, instance=author)
        if form.is_valid():
            author = form.save()
            return serialize(author)
        return Http400(reason='invalid author data', details=form.errors)


class FailsIntentionally(Endpoint):
    def get(self, request):
        raise Exception("I'm being a bad view")


class TestLogin(AuthenticateEndpoint):
    pass


class TestBasicAuth(Endpoint, BasicHttpAuthMixin):
    @login_required
    def get(self, request):
        return serialize(request.user)


class TestCustomAuthMethod(Endpoint, AbstractAuthMixin):
    def authenticate(self, request):
        user = request.params.get('user')
        if user == 'friend':
            return None
        if user == 'foe':
            return Http403('you shall not pass')
        if user == 'exceptional-foe':
            raise HttpError(403, 'with exception')
        # this is an illegal return value for this function
        return 42

    def get(self, request):
        return 'OK'


class WildcardHandler(Endpoint):
    def dispatch(self, request, *args, **kwargs):
        return Http404('no such resource: %s %s' % (
            request.method, request.path))


class EchoView(Endpoint):
    def post(self, request):
        return {
            'headers': dict((k, str(v)) for k, v in request.META.items()),
            'raw_data': base64.b64encode(request.raw_data).decode('ascii')
        }

    def get(self, request):
        return self.post(request)

    def put(self, request):
        return self.post(request)


class ErrorRaisingView(Endpoint):
    def get(self, request):
        raise HttpError(400, 'raised error', extra_data='foo')


class PublisherAutoList(ListEndpoint):
    model = Publisher


class PublisherAutoDetail(DetailEndpoint):
    model = Publisher


class ReadOnlyPublisherAutoList(ListEndpoint):
    model = Publisher
    methods = ['GET']


class PublisherAction(ActionEndpoint):
    model = Publisher

    def action(self, obj, *args, **kwargs):
        return {'result': 'done'}


class BookDetail(DetailEndpoint):
    model = Book
    lookup_field = 'isbn'
