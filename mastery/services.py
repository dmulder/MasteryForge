"""Session helpers for learning flow."""
from datetime import timedelta

from django.utils import timezone

from .models import LearningSession


SESSION_TIMEOUT_MINUTES = 90


def get_or_start_session(user) -> LearningSession:
    session = (
        LearningSession.objects.filter(user=user, end_time__isnull=True)
        .order_by('-start_time')
        .first()
    )
    if session:
        if timezone.now() - session.start_time > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
            session.end_time = timezone.now()
            session.save(update_fields=['end_time'])
            session = None

    if not session:
        LearningSession.objects.filter(user=user, end_time__isnull=True).update(end_time=timezone.now())
        session = LearningSession.objects.create(user=user)

    return session


def close_session(user) -> None:
    session = (
        LearningSession.objects.filter(user=user, end_time__isnull=True)
        .order_by('-start_time')
        .first()
    )
    if session:
        session.end_time = timezone.now()
        session.save(update_fields=['end_time'])


def record_quiz(session: LearningSession, concept, score_percent: float) -> None:
    session.concepts_covered.add(concept)
    session.total_questions += 1
    if session.total_questions == 1:
        session.average_score = score_percent
    else:
        session.average_score = (
            (session.average_score * (session.total_questions - 1)) + score_percent
        ) / session.total_questions
    session.save(update_fields=['total_questions', 'average_score'])
