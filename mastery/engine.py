"""MasteryEngine - deterministic, frustration-aware logic."""
from dataclasses import dataclass
from typing import Optional, List

from django.db import transaction
from django.utils import timezone

from content.models import Concept, Course
from ai.provider import get_ai_provider
from .models import MasteryState, QuizAttempt
from .graph import ConceptGraph


@dataclass
class MasteryUpdateResult:
    mastery_state: MasteryState
    quiz_attempt: QuizAttempt
    encouragement: Optional[str] = None
    explanation: Optional[str] = None
    next_concept: Optional[Concept] = None


class MasteryEngine:
    """Engine that determines next concept based on mastery and frustration levels."""

    def __init__(self, user, graph: Optional[ConceptGraph] = None):
        self.user = user
        self.graph = graph or ConceptGraph()

    def _get_mastery_state(self, concept: Concept) -> MasteryState:
        state, _ = MasteryState.objects.get_or_create(
            user=self.user,
            concept=concept,
            defaults={
                'mastery_score': 0.0,
                'confidence_score': 0.0,
                'frustration_score': 0.0,
                'attempts': 0,
            },
        )
        return state

    def update_mastery_after_quiz(self, concept: Concept, score_percent: float) -> MasteryUpdateResult:
        score_percent = max(0.0, min(100.0, score_percent))

        with transaction.atomic():
            state = self._get_mastery_state(concept)
            quiz_attempt = QuizAttempt.objects.create(
                user=self.user,
                concept=concept,
                score_percent=score_percent,
                raw_data={},
            )

            state.attempts += 1
            state.last_seen = timezone.now()

            if score_percent >= 80:
                state.mastery_score += 0.15
                state.frustration_score -= 0.2
                state.confidence_score += 0.1
            elif score_percent >= 50:
                state.mastery_score += 0.05
                state.frustration_score += 0.05
                state.confidence_score += 0.02
            else:
                state.mastery_score += 0.01
                state.frustration_score += 0.2
                state.confidence_score -= 0.05

            state.mastery_score = min(1.0, max(0.0, state.mastery_score))
            state.frustration_score = min(1.0, max(0.0, state.frustration_score))
            state.confidence_score = min(1.0, max(0.0, state.confidence_score))
            state.save(update_fields=[
                'attempts',
                'last_seen',
                'mastery_score',
                'frustration_score',
                'confidence_score',
            ])

        return MasteryUpdateResult(mastery_state=state, quiz_attempt=quiz_attempt)

    def select_next_concept(self, course: Optional[Course] = None) -> Optional[Concept]:
        eligible = self.graph.eligible_concepts(self.user, course=course)
        concepts = eligible if eligible else list(Concept.objects.filter(is_active=True))
        if course:
            concepts = [concept for concept in concepts if concept.course_id == course.id]

        mastery_states = {
            str(state.concept_id): {
                'mastery_score': state.mastery_score,
                'confidence_score': state.confidence_score,
                'frustration_score': state.frustration_score,
                'attempts': state.attempts,
            }
            for state in MasteryState.objects.filter(user=self.user)
        }

        ai_suggestions = get_ai_provider().recommend_concepts(
            self.user,
            [{'id': concept.id, 'title': concept.title} for concept in concepts],
            mastery_states,
        )
        suggestion_ids = {str(item) for item in ai_suggestions}
        ai_candidates = [concept for concept in concepts if str(concept.id) in suggestion_ids]

        if ai_candidates:
            concept = ai_candidates[0]
            state = MasteryState.objects.filter(user=self.user, concept=concept).first()
            if state:
                state.ai_recommended = True
                state.save(update_fields=['ai_recommended'])
            return concept

        return self.graph.select_next_concept(self.user, course=course)
