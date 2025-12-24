"""URL configuration for QueryPilot project."""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('query_manager.urls')),
]
