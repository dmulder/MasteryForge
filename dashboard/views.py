from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.db import models
from mastery.models import MasteryState
from mastery.engine import MasteryEngine
from accounts.models import Student, Parent


def home(request):
    """Home page - redirect based on user type or show landing page"""
    if request.user.is_authenticated:
        if request.user.user_type == 'student':
            return redirect('student_dashboard')
        elif request.user.user_type == 'parent':
            return redirect('parent_dashboard')
    
    return render(request, 'dashboard/home.html')


@login_required
def student_dashboard(request):
    """Student dashboard showing their mastery progress"""
    if request.user.user_type != 'student':
        messages.error(request, "Access denied. Student access only.")
        return redirect('home')
    
    # Get student's mastery states
    mastery_states = MasteryState.objects.filter(user=request.user).order_by('-last_attempted')[:10]
    
    # Use mastery engine to get next concept
    engine = MasteryEngine(request.user)
    next_concept = engine.select_next_concept()
    available_concepts = engine.get_available_concepts()
    mastered_concepts = engine.get_mastered_concepts()
    
    # Calculate overall progress
    total_concepts = len(engine.concept_graph.get_all_concepts())
    mastered_count = len(mastered_concepts)
    progress_percentage = (mastered_count / total_concepts * 100) if total_concepts > 0 else 0
    
    context = {
        'mastery_states': mastery_states,
        'next_concept': next_concept,
        'available_concepts': available_concepts[:5],  # Show top 5
        'mastered_count': mastered_count,
        'total_concepts': total_concepts,
        'progress_percentage': progress_percentage,
    }
    
    return render(request, 'dashboard/student_dashboard.html', context)


@login_required
def parent_dashboard(request):
    """Parent dashboard showing their linked students' progress"""
    if request.user.user_type != 'parent':
        messages.error(request, "Access denied. Parent access only.")
        return redirect('home')
    
    try:
        parent = Parent.objects.get(user=request.user)
        students = parent.students.all()
        
        # Gather progress for each student
        student_progress = []
        for student in students:
            mastery_states = MasteryState.objects.filter(user=student.user)
            engine = MasteryEngine(student.user)
            
            total_concepts = len(engine.concept_graph.get_all_concepts())
            mastered_concepts = engine.get_mastered_concepts()
            mastered_count = len(mastered_concepts)
            progress_percentage = (mastered_count / total_concepts * 100) if total_concepts > 0 else 0
            
            # Calculate average frustration
            avg_frustration = mastery_states.aggregate(
                models.Avg('frustration_score')
            )['frustration_score__avg'] or 0.0
            
            student_progress.append({
                'student': student,
                'mastered_count': mastered_count,
                'total_concepts': total_concepts,
                'progress_percentage': progress_percentage,
                'avg_frustration': avg_frustration,
                'recent_activity': mastery_states.order_by('-last_attempted')[:5]
            })
        
        context = {
            'parent': parent,
            'student_progress': student_progress,
        }
        
    except Parent.DoesNotExist:
        messages.warning(request, "Parent profile not found. Please contact an administrator.")
        context = {'student_progress': []}
    
    return render(request, 'dashboard/parent_dashboard.html', context)


@login_required
def concept_detail(request, concept_id):
    """Detail view for a specific concept"""
    from mastery.concept_graph import get_concept_graph
    
    concept_graph = get_concept_graph()
    concept = concept_graph.get_concept(concept_id)
    
    if not concept:
        messages.error(request, f"Concept '{concept_id}' not found.")
        return redirect('student_dashboard')
    
    # Get user's mastery state for this concept
    try:
        mastery_state = MasteryState.objects.get(user=request.user, concept_id=concept_id)
        mastery_percentage = mastery_state.mastery_score * 100
    except MasteryState.DoesNotExist:
        mastery_state = None
        mastery_percentage = 0
    
    context = {
        'concept': concept,
        'mastery_state': mastery_state,
        'mastery_percentage': mastery_percentage,
        'prerequisites': [concept_graph.get_concept(pid) for pid in concept.get('prerequisites', [])],
    }
    
    return render(request, 'dashboard/concept_detail.html', context)
