"""
Concept graph loader and manager for MasteryForge
"""
import yaml
from pathlib import Path
from typing import Dict, List, Optional


class ConceptGraph:
    """Manages the concept graph loaded from YAML"""
    
    def __init__(self):
        self.concepts = {}
        self.graph = {}  # concept_id -> list of prerequisite concept_ids
        
    def load_from_yaml(self, yaml_path: str) -> None:
        """Load concepts from a YAML file"""
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"YAML file not found: {yaml_path}")
        
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        
        if not data or 'concepts' not in data:
            raise ValueError("YAML file must contain a 'concepts' key")
        
        for concept in data['concepts']:
            concept_id = concept['id']
            self.concepts[concept_id] = {
                'id': concept_id,
                'title': concept.get('title', concept_id),
                'description': concept.get('description', ''),
                'prerequisites': concept.get('prerequisites', []),
                'difficulty': concept.get('difficulty', 1)
            }
            self.graph[concept_id] = concept.get('prerequisites', [])
    
    def get_concept(self, concept_id: str) -> Optional[Dict]:
        """Get concept details by ID"""
        return self.concepts.get(concept_id)
    
    def get_prerequisites(self, concept_id: str) -> List[str]:
        """Get list of prerequisite concept IDs"""
        return self.graph.get(concept_id, [])
    
    def get_all_concepts(self) -> Dict[str, Dict]:
        """Get all concepts"""
        return self.concepts
    
    def has_prerequisites_met(self, concept_id: str, mastered_concepts: List[str]) -> bool:
        """Check if all prerequisites for a concept are mastered"""
        prerequisites = self.get_prerequisites(concept_id)
        return all(prereq in mastered_concepts for prereq in prerequisites)


# Global instance
_concept_graph = None


def get_concept_graph() -> ConceptGraph:
    """Get the global concept graph instance"""
    global _concept_graph
    if _concept_graph is None:
        _concept_graph = ConceptGraph()
    return _concept_graph
