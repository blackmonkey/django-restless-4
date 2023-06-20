from django.urls import path, re_path

try:
    from django.conf.urls import patterns
except ImportError:
    def patterns(prefix, *args):
        return args

from .views import *

urlpatterns = patterns('',
    path('authors/', AuthorList.as_view(),
        name='author_list'),
    path('authors/<int:author_id>', AuthorDetail.as_view(),
        name='author_detail'),

    path('fail-view/', FailsIntentionally.as_view(),
        name='fail_view'),
    path('login-view/', TestLogin.as_view(),
        name='login_view'),
    path('basic-auth-view/', TestBasicAuth.as_view(),
        name='basic_auth_view'),
    path('custom-auth/', TestCustomAuthMethod.as_view(),
        name='custom_auth_method'),
    path('echo-view/', EchoView.as_view(),
        name='echo_view'),
    path('error-raising-view/', ErrorRaisingView.as_view(),
        name='error_raising_view'),

    path('publishers/', PublisherAutoList.as_view(),
        name='publisher_list'),
    path('publishers-ready-only/', ReadOnlyPublisherAutoList.as_view(),
        name='readonly_publisher_list'),
    path('publishers/<int:pk>', PublisherAutoDetail.as_view(),
        name='publisher_detail'),
    path('publishers/<int:pk>/do_something', PublisherAction.as_view(),
        name='publisher_action'),

    path('books/<int:isbn>', BookDetail.as_view(),
        name='book_detail'),

    re_path(r'^.*$', WildcardHandler.as_view()),
)
