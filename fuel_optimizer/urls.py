from django.urls import path
from .views import RouteOptimizerAPIView, RouteMapView, DashboardView

urlpatterns = [
    path('', DashboardView.as_view(), name='dashboard'),
    path('api/route/', RouteOptimizerAPIView.as_view(), name='api-route'),
    path('api/route/map/', RouteMapView.as_view(), name='api-route-map'),
]
