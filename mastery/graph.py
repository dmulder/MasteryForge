"""Concept graph traversal based on database models."""
from typing import List, Optional

from django.utils import timezone

from content.models import Concept, Course
from .models import MasteryState


class ConceptGraph:
    def __init__(self, mastery_threshold: float = 0.6):
        self.mastery_threshold = mastery_threshold

    def _eligible_queryset(self, course: Optional[Course] = None):
        concepts = Concept.objects.filter(is_active=True)
        if course:
            concepts = concepts.filter(course=course)
        return concepts

    def _prereqs_mastered(self, user, concept: Concept) -> bool:
        prereqs = concept.prerequisites.all()
        if not prereqs.exists():
            return True
        mastered = MasteryState.objects.filter(
            user=user,
            concept__in=prereqs,
            mastery_score__gte=self.mastery_threshold,
        ).values_list('concept_id', flat=True)
        return prereqs.count() == len(set(mastered))

    def eligible_concepts(self, user, course: Optional[Course] = None) -> List[Concept]:
        eligible = []
        for concept in self._eligible_queryset(course=course):
            if self._prereqs_mastered(user, concept):
                eligible.append(concept)
        return eligible

    def select_next_concept(self, user, course: Optional[Course] = None) -> Optional[Concept]:
        eligible = self.eligible_concepts(user, course=course)
        current_state = (
            MasteryState.objects.filter(user=user)
            .select_related('concept')
            .order_by('-last_seen')
            .first()
        )

        if current_state and current_state.frustration_score > 0.7:
            pivot = self._pivot_from_frustration(user, current_state, eligible, course=course)
            if pivot:
                return pivot

        if current_state and current_state.mastery_score < 0.4 and current_state.attempts > 3:
            pivot = self._pivot_sideways(user, current_state, eligible)
            if pivot:
                return pivot

        if eligible:
            return self._select_lowest_mastery(user, eligible)

        return self._fallback_prerequisite(user, course=course)

    def _pivot_from_frustration(
        self,
        user,
        current_state: MasteryState,
        eligible: List[Concept],
        course: Optional[Course] = None,
    ) -> Optional[Concept]:
        prereqs = list(current_state.concept.prerequisites.all())
        if prereqs:
            prereq_state = (
                MasteryState.objects.filter(user=user, concept__in=prereqs)
                .order_by('mastery_score')
                .select_related('concept')
                .first()
            )
            if prereq_state:
                return prereq_state.concept

        siblings = [
            concept for concept in eligible
            if concept.course_id == current_state.concept.course_id and concept.id != current_state.concept_id
        ]
        if siblings:
            return self._select_lowest_mastery(user, siblings)

        return self._fallback_prerequisite(user, course=course)

    def _pivot_sideways(
        self,
        user,
        current_state: MasteryState,
        eligible: List[Concept],
    ) -> Optional[Concept]:
        alternatives = [
            concept for concept in eligible if concept.id != current_state.concept_id
        ]
        if not alternatives:
            return None
        return self._select_lowest_mastery(user, alternatives)

    def _select_lowest_mastery(self, user, concepts: List[Concept]) -> Concept:
        concept_ids = [concept.id for concept in concepts]
        states = {
            state.concept_id: state
            for state in MasteryState.objects.filter(user=user, concept_id__in=concept_ids)
        }

        def sort_key(concept: Concept):
            state = states.get(concept.id)
            mastery = state.mastery_score if state else 0.0
            last_seen = state.last_seen if state else timezone.make_aware(timezone.datetime.min)
            return (mastery, last_seen)

        return sorted(concepts, key=sort_key)[0]

    def _fallback_prerequisite(self, user, course: Optional[Course] = None) -> Optional[Concept]:
        concepts = self._eligible_queryset(course=course)
        if not concepts.exists():
            return None

        lowest_mastery = (
            MasteryState.objects.filter(user=user, concept__in=concepts)
            .order_by('mastery_score')
            .select_related('concept')
            .first()
        )
        if lowest_mastery:
            return lowest_mastery.concept

        return concepts.order_by('order_index').first()
