from django.db import models


class Course(models.Model):
    name = models.CharField(max_length=200)
    khan_slug = models.CharField(
        max_length=255,
        blank=True,
        help_text="Khan Academy course slug, e.g. math/algebra-basics",
    )
    grade_level = models.IntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['grade_level', 'name']

    def __str__(self):
        return f"{self.name} (Grade {self.grade_level})"


class Concept(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='concepts')
    external_id = models.CharField(max_length=120, null=True, blank=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    difficulty = models.IntegerField(default=1)
    khan_slug = models.CharField(max_length=255, blank=True, help_text="Full Khan Academy URL path")
    quiz_slug = models.CharField(max_length=255, blank=True, help_text="Optional Khan quiz URL path")
    order_index = models.IntegerField(default=0)
    prerequisites = models.ManyToManyField(
        'self',
        symmetrical=False,
        blank=True,
        related_name='dependent_concepts',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order_index', 'title']
        unique_together = ('course', 'khan_slug')

    def __str__(self):
        return f"{self.course.name}: {self.title}"


class KhanLessonCache(models.Model):
    khan_slug = models.CharField(max_length=255, unique=True)
    youtube_id = models.CharField(max_length=32, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Khan cache: {self.khan_slug}"
