from django.db import models
from django.conf import settings


class MasteryState(models.Model):
    """Tracks student's mastery progress for each concept"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mastery_states')
    concept = models.ForeignKey('content.Concept', on_delete=models.CASCADE, related_name='mastery_states')
    ai_recommended = models.BooleanField(default=False)
    mastery_score = models.FloatField(default=0.0, help_text="Score from 0.0 to 1.0 indicating mastery level")
    confidence_score = models.FloatField(default=0.0, help_text="Score from 0.0 to 1.0 indicating confidence level")
    frustration_score = models.FloatField(default=0.0, help_text="Score from 0.0 to 1.0 indicating frustration level")
    attempts = models.IntegerField(default=0, help_text="Number of attempts on this concept")
    last_seen = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'concept')
        ordering = ['-last_seen']

    def __str__(self):
        return f"{self.user.username} - {self.concept.title} (Mastery: {self.mastery_score:.2f}, Frustration: {self.frustration_score:.2f})"



class QuizAttempt(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='quiz_attempts')
    concept = models.ForeignKey('content.Concept', on_delete=models.CASCADE, related_name='quiz_attempts')
    score_percent = models.FloatField()
    raw_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.concept.title} ({self.score_percent:.1f}%)"


class ParentStudentLink(models.Model):
    parent = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='parent_links')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='student_links')

    class Meta:
        unique_together = ('parent', 'student')

    def __str__(self):
        return f"{self.parent.username} -> {self.student.username}"


class LearningSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='learning_sessions')
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    concepts_covered = models.ManyToManyField('content.Concept', blank=True, related_name='learning_sessions')
    total_questions = models.IntegerField(default=0)
    average_score = models.FloatField(default=0.0)

    class Meta:
        ordering = ['-start_time']

    def __str__(self):
        return f"Session for {self.user.username} at {self.start_time:%Y-%m-%d %H:%M}"
