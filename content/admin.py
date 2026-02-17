from django.contrib import admin
from .models import Course, Concept, KhanLessonCache


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('name', 'grade_level', 'khan_slug', 'is_active')
    list_filter = ('grade_level', 'is_active')
    search_fields = ('name', 'khan_slug')


@admin.register(Concept)
class ConceptAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'order_index', 'khan_slug', 'is_active')
    list_filter = ('course', 'is_active')
    search_fields = ('title', 'khan_slug')
    filter_horizontal = ('prerequisites',)


@admin.register(KhanLessonCache)
class KhanLessonCacheAdmin(admin.ModelAdmin):
    list_display = ('khan_slug', 'youtube_id', 'fetched_at')
    search_fields = ('khan_slug', 'youtube_id')
    readonly_fields = ('fetched_at',)
