from django.urls import include, path
import testapp.urls


urlpatterns = [
    path('', include(testapp.urls)),
]
