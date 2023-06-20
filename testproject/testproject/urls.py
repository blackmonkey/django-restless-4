from django.urls import include, path
import testapp.urls

try:
    from django.conf.urls import patterns
except ImportError:
    def patterns(prefix, *args):
        return args


urlpatterns = patterns('',
    path('', include(testapp.urls)),
)
