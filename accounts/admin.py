from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Student, Parent


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin interface for custom User model"""
    list_display = ('username', 'email', 'user_type', 'is_staff', 'is_active')
    list_filter = ('user_type', 'is_staff', 'is_active')
    fieldsets = BaseUserAdmin.fieldsets + (
        ('User Type', {'fields': ('user_type',)}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('User Type', {'fields': ('user_type',)}),
    )


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    """Admin interface for Student model"""
    list_display = ('user', 'grade_level', 'date_enrolled')
    search_fields = ('user__username', 'user__email')


@admin.register(Parent)
class ParentAdmin(admin.ModelAdmin):
    """Admin interface for Parent model"""
    list_display = ('user', 'phone_number')
    search_fields = ('user__username', 'user__email')
    filter_horizontal = ('students',)
