"""
URL configuration for dashboard app
"""
from django.urls import path
from . import views

urlpatterns = [
    path('student/', views.student_dashboard, name='student_dashboard'),
    path('parent/', views.parent_dashboard, name='parent_dashboard'),
    path('concept/<str:concept_id>/', views.concept_detail, name='concept_detail'),
]
