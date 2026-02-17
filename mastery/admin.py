from django.contrib import admin
from .models import MasteryState, QuizAttempt, ParentStudentLink, LearningSession


@admin.register(MasteryState)
class MasteryStateAdmin(admin.ModelAdmin):
    """Admin interface for MasteryState model"""
    list_display = ('user', 'concept', 'mastery_score', 'confidence_score', 'frustration_score', 'attempts', 'last_seen')
    list_filter = ('last_seen', 'created_at')
    search_fields = ('user__username', 'concept__title')
    readonly_fields = ('created_at', 'last_seen')


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ('user', 'concept', 'score_percent', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'concept__title')
    readonly_fields = ('created_at',)


@admin.register(ParentStudentLink)
class ParentStudentLinkAdmin(admin.ModelAdmin):
    list_display = ('parent', 'student')
    search_fields = ('parent__username', 'student__username')


@admin.register(LearningSession)
class LearningSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'start_time', 'end_time', 'total_questions', 'average_score')
    list_filter = ('start_time', 'end_time')
    search_fields = ('user__username',)
    readonly_fields = ('start_time',)
