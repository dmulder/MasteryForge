from django.contrib import admin
from .models import MasteryState


@admin.register(MasteryState)
class MasteryStateAdmin(admin.ModelAdmin):
    """Admin interface for MasteryState model"""
    list_display = ('user', 'concept_id', 'mastery_score', 'frustration_score', 'attempts', 'last_attempted')
    list_filter = ('last_attempted', 'created_at')
    search_fields = ('user__username', 'concept_id')
    readonly_fields = ('created_at', 'last_attempted')
