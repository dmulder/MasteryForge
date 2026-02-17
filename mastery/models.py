from django.db import models
from django.conf import settings


class MasteryState(models.Model):
    """Tracks student's mastery progress for each concept"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mastery_states')
    concept_id = models.CharField(max_length=100, help_text="Unique identifier for the concept")
    mastery_score = models.FloatField(default=0.0, help_text="Score from 0.0 to 1.0 indicating mastery level")
    frustration_score = models.FloatField(default=0.0, help_text="Score from 0.0 to 1.0 indicating frustration level")
    attempts = models.IntegerField(default=0, help_text="Number of attempts on this concept")
    last_attempted = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('user', 'concept_id')
        ordering = ['-last_attempted']
    
    def __str__(self):
        return f"{self.user.username} - {self.concept_id} (Mastery: {self.mastery_score:.2f}, Frustration: {self.frustration_score:.2f})"
