from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .services import get_or_start_session, close_session


@receiver(user_logged_in)
def start_learning_session(sender, user, request, **kwargs):
    if getattr(user, 'user_type', None) == 'student':
        get_or_start_session(user)


@receiver(user_logged_out)
def end_learning_session(sender, user, request, **kwargs):
    if user and getattr(user, 'user_type', None) == 'student':
        close_session(user)
