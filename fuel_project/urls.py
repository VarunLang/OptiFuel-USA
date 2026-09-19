"""
URL configuration for fuel_project (No Database / No Admin).
"""
from django.urls import path, include

urlpatterns = [
    path('', include('fuel_optimizer.urls')),
]
