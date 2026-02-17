"""
MasteryEngine - Frustration-aware adaptive learning logic
"""
from typing import Optional, List, Dict
from django.db.models import Q
from .models import MasteryState
from .concept_graph import get_concept_graph


class MasteryEngine:
    """
    Engine that determines next concept based on mastery and frustration levels
    """
    
    MASTERY_THRESHOLD = 0.7
    FRUSTRATION_THRESHOLD = 0.6
    HIGH_FRUSTRATION = 0.8
    
    def __init__(self, user):
        self.user = user
        self.concept_graph = get_concept_graph()
    
    def get_mastered_concepts(self) -> List[str]:
        """Get list of concept IDs that the user has mastered"""
        mastered = MasteryState.objects.filter(
            user=self.user,
            mastery_score__gte=self.MASTERY_THRESHOLD
        ).values_list('concept_id', flat=True)
        return list(mastered)
    
    def get_mastery_state(self, concept_id: str) -> Optional[MasteryState]:
        """Get the mastery state for a specific concept"""
        try:
            return MasteryState.objects.get(user=self.user, concept_id=concept_id)
        except MasteryState.DoesNotExist:
            return None
    
    def get_frustration_score(self, concept_id: str) -> float:
        """Get the frustration score for a concept (0.0 if not attempted)"""
        state = self.get_mastery_state(concept_id)
        return state.frustration_score if state else 0.0
    
    def get_available_concepts(self) -> List[str]:
        """Get concepts that have prerequisites met but are not yet mastered"""
        mastered = self.get_mastered_concepts()
        all_concepts = self.concept_graph.get_all_concepts()
        
        available = []
        for concept_id in all_concepts:
            # Skip if already mastered
            if concept_id in mastered:
                continue
            
            # Check if prerequisites are met
            if self.concept_graph.has_prerequisites_met(concept_id, mastered):
                available.append(concept_id)
        
        return available
    
    def select_next_concept(self) -> Optional[str]:
        """
        Select the next concept using frustration-aware logic
        
        Logic:
        1. Get all available concepts (prerequisites met, not mastered)
        2. If user has high frustration on current concept, suggest easier alternative
        3. Otherwise, prioritize concepts with lower frustration and higher readiness
        """
        available = self.get_available_concepts()
        
        if not available:
            return None
        
        # Score each available concept
        scored_concepts = []
        for concept_id in available:
            concept = self.concept_graph.get_concept(concept_id)
            state = self.get_mastery_state(concept_id)
            
            # Calculate readiness score
            frustration = state.frustration_score if state else 0.0
            mastery = state.mastery_score if state else 0.0
            difficulty = concept.get('difficulty', 1)
            attempts = state.attempts if state else 0
            
            # Score calculation (higher is better)
            # - Penalize high frustration
            # - Prefer some progress (mastery > 0) but not too high
            # - Adjust for difficulty
            # - Slight preference for concepts with some attempts (engagement)
            score = (1.0 - frustration) * 2.0  # Frustration heavily weighted
            score += mastery * 0.5  # Some progress is good
            score -= (difficulty - 1) * 0.2  # Slightly prefer easier concepts
            score += min(attempts, 3) * 0.1  # Slight bonus for engagement (capped)
            
            scored_concepts.append((concept_id, score, frustration))
        
        # Sort by score (descending)
        scored_concepts.sort(key=lambda x: x[1], reverse=True)
        
        # Check if we should switch due to high frustration
        # If top concept has high frustration, try to find an alternative
        if scored_concepts[0][2] >= self.HIGH_FRUSTRATION and len(scored_concepts) > 1:
            # Find concept with lower frustration
            for concept_id, score, frustration in scored_concepts[1:]:
                if frustration < self.FRUSTRATION_THRESHOLD:
                    return concept_id
        
        # Return highest scoring concept
        return scored_concepts[0][0]
    
    def update_mastery_state(self, concept_id: str, correct: bool, time_spent: Optional[float] = None) -> MasteryState:
        """
        Update mastery and frustration scores based on attempt
        
        Args:
            concept_id: The concept being attempted
            correct: Whether the attempt was correct
            time_spent: Optional time spent on the attempt (for frustration calculation)
        """
        state, created = MasteryState.objects.get_or_create(
            user=self.user,
            concept_id=concept_id,
            defaults={'mastery_score': 0.0, 'frustration_score': 0.0, 'attempts': 0}
        )
        
        # Update attempts
        state.attempts += 1
        
        # Update mastery score (exponential moving average)
        alpha = 0.3  # Learning rate
        if correct:
            state.mastery_score = state.mastery_score + alpha * (1.0 - state.mastery_score)
            # Reduce frustration on success
            state.frustration_score = max(0.0, state.frustration_score - 0.1)
        else:
            state.mastery_score = max(0.0, state.mastery_score - alpha * 0.5)
            # Increase frustration on failure
            state.frustration_score = min(1.0, state.frustration_score + 0.15)
        
        # Additional frustration factors
        if time_spent and time_spent > 120:  # More than 2 minutes
            state.frustration_score = min(1.0, state.frustration_score + 0.05)
        
        # Consecutive failures increase frustration more
        if not correct and state.attempts > 3:
            recent_failures = state.attempts - 3
            state.frustration_score = min(1.0, state.frustration_score + recent_failures * 0.02)
        
        state.save()
        return state
