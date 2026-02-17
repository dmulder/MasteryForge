"""
Django management command to load concepts from YAML file
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from mastery.concept_graph import get_concept_graph
import os


class Command(BaseCommand):
    help = 'Load concepts from YAML file into the concept graph'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default='concepts.yaml',
            help='Path to the YAML file containing concepts (default: concepts.yaml in project root)'
        )

    def handle(self, *args, **options):
        yaml_file = options['file']
        
        # If relative path, resolve from project root
        if not os.path.isabs(yaml_file):
            yaml_file = os.path.join(settings.BASE_DIR, yaml_file)
        
        self.stdout.write(f'Loading concepts from: {yaml_file}')
        
        try:
            concept_graph = get_concept_graph()
            concept_graph.load_from_yaml(yaml_file)
            
            concepts = concept_graph.get_all_concepts()
            self.stdout.write(self.style.SUCCESS(
                f'Successfully loaded {len(concepts)} concepts:'
            ))
            
            for concept_id, concept in concepts.items():
                prereqs = ', '.join(concept['prerequisites']) if concept['prerequisites'] else 'None'
                self.stdout.write(f"  - {concept_id} (difficulty: {concept['difficulty']}, prerequisites: {prereqs})")
            
        except FileNotFoundError as e:
            self.stdout.write(self.style.ERROR(f'Error: {e}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error loading concepts: {e}'))
