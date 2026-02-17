from django.contrib import admin
from .models import ParentStudentConfig


@admin.register(ParentStudentConfig)
class ParentStudentConfigAdmin(admin.ModelAdmin):
    list_display = ('parent', 'student', 'grade_level', 'override_starting_point')
    list_filter = ('grade_level', 'override_starting_point')
    search_fields = ('parent__username', 'student__username')
    filter_horizontal = ('courses',)
