"""MasteryEngine - deterministic, frustration-aware logic."""
from dataclasses import dataclass
from typing import Optional, List, Dict
import logging

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
        self.logger = logging.getLogger(__name__)

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

    def recommend_next_concept_after_quiz(
        self,
        concept: Concept,
        score_percent: float,
    ) -> Optional[Concept]:
        course = concept.course
        course_concepts = list(
            Concept.objects.filter(course=course, is_active=True).order_by('order_index', 'id')
        )
        if not course_concepts:
            return None

        mastery_states = {
            str(state.concept_id): {
                'mastery_score': state.mastery_score,
                'confidence_score': state.confidence_score,
                'frustration_score': state.frustration_score,
                'attempts': state.attempts,
            }
            for state in MasteryState.objects.filter(user=self.user, concept__course=course)
        }

        history = [
            {
                'concept_id': str(attempt.concept_id),
                'concept_title': attempt.concept.title,
                'score_percent': attempt.score_percent,
                'created_at': attempt.created_at.isoformat(),
            }
            for attempt in QuizAttempt.objects.filter(user=self.user, concept__course=course)
            .select_related('concept')
            .order_by('created_at')
        ]

        context = {
            'subject_just_studied': {
                'concept_id': str(concept.id),
                'title': concept.title,
                'course': course.name,
            },
            'recent_score_percent': score_percent,
            'course_subjects': [
                {
                    'concept_id': str(item.id),
                    'title': item.title,
                    'order_index': item.order_index,
                    'prerequisite_ids': [str(pr.id) for pr in item.prerequisites.all()],
                }
                for item in course_concepts
            ],
            'course_subject_titles': [item.title for item in course_concepts],
            'practice_history': history,
            'mastery_states': mastery_states,
            'guidance': {
                'avoid_repeating_high_scores': True,
                'allow_reinforcement_for_low_scores': True,
                'pivot_on_frustration_or_repeated_poor_performance': True,
            },
        }

        recommendation = get_ai_provider().recommend_next_lesson(context)
        next_concept = None
        if recommendation:
            next_id = str(recommendation.get('next_concept_id', '')).strip()
            if next_id:
                self.logger.debug("AI next_concept_id=%s (current=%s)", next_id, concept.id)
                next_concept = next(
                    (item for item in course_concepts if str(item.id) == next_id),
                    None,
                )
                if next_concept and next_concept.id == concept.id and score_percent >= 80:
                    self.logger.debug("AI suggested current concept after high score; ignoring.")
                    next_concept = None
            else:
                self.logger.debug("AI recommendation missing next_concept_id.")
        else:
            self.logger.debug("AI did not return a recommendation; using fallback.")

        if next_concept:
            return next_concept

        return self._fallback_next_concept_after_quiz(concept, score_percent, course_concepts, mastery_states)

    def _fallback_next_concept_after_quiz(
        self,
        concept: Concept,
        score_percent: float,
        course_concepts: List[Concept],
        mastery_states: Dict[str, dict],
    ) -> Optional[Concept]:
        state = MasteryState.objects.filter(user=self.user, concept=concept).first()

        if score_percent >= 80:
            for candidate in course_concepts:
                if candidate.order_index > concept.order_index:
                    return candidate
            return None

        def mastery_for(item: Concept) -> float:
            state_data = mastery_states.get(str(item.id))
            return state_data.get('mastery_score', 0.0) if state_data else 0.0

        if state and (state.frustration_score > 0.7 or score_percent < 50):
            prereqs = list(concept.prerequisites.all())
            if prereqs:
                return sorted(prereqs, key=mastery_for)[0]

        alternatives = [item for item in course_concepts if item.id != concept.id]
        if alternatives:
            return sorted(alternatives, key=mastery_for)[0]

        return None
