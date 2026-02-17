from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import models
from django.db.models import Avg

from accounts.models import Student, Parent
from ai.provider import get_ai_provider
from content.khan import fetch_khan_youtube_id, get_khan_classes
from content.models import Course, Concept
from mastery.engine import MasteryEngine
from mastery.models import MasteryState
from mastery.services import get_or_start_session, record_quiz
from dashboard.models import ParentStudentConfig


def home(request):
    """Home page - redirect based on user type or show landing page"""
    if request.user.is_authenticated:
        if request.user.user_type == 'student':
            return redirect('learning_session')
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
    mastery_states = MasteryState.objects.filter(user=request.user).order_by('-last_seen')[:10]
    
    # Use mastery engine to get next concept
    engine = MasteryEngine(request.user)
    next_concept = engine.select_next_concept()

    total_concepts = Concept.objects.filter(is_active=True).count()
    mastered_count = MasteryState.objects.filter(user=request.user, mastery_score__gte=0.7).count()
    progress_percentage = (mastered_count / total_concepts * 100) if total_concepts > 0 else 0
    
    context = {
        'mastery_states': mastery_states,
        'next_concept': next_concept,
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
            mastery_states = MasteryState.objects.filter(user=student.user).select_related('concept')

            total_concepts = Concept.objects.filter(is_active=True).count()
            mastered_count = mastery_states.filter(mastery_score__gte=0.7).count()
            progress_percentage = (mastered_count / total_concepts * 100) if total_concepts > 0 else 0

            avg_frustration = mastery_states.aggregate(Avg('frustration_score'))['frustration_score__avg'] or 0.0
            
            config = ParentStudentConfig.objects.filter(parent=request.user, student=student.user).first()

            heatmap = [
                {
                    'concept': state.concept,
                    'mastery': state.mastery_score,
                    'frustration': state.frustration_score,
                }
                for state in mastery_states.order_by('-mastery_score')
            ]
            frustration_trend = [
                {
                    'last_seen': state.last_seen,
                    'frustration': state.frustration_score,
                }
                for state in mastery_states.order_by('-last_seen')[:10]
            ]
            learning_history = (
                student.user.learning_sessions.order_by('-start_time')[:5]
            )

            student_progress.append({
                'student': student,
                'mastered_count': mastered_count,
                'total_concepts': total_concepts,
                'progress_percentage': progress_percentage,
                'avg_frustration': avg_frustration,
                'recent_activity': mastery_states.order_by('-last_seen')[:5],
                'config': config,
                'heatmap': heatmap,
                'frustration_trend': frustration_trend,
                'learning_history': learning_history,
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
    concept = get_object_or_404(Concept, id=concept_id)

    mastery_state = MasteryState.objects.filter(user=request.user, concept=concept).first()
    mastery_percentage = (mastery_state.mastery_score * 100) if mastery_state else 0

    context = {
        'concept': concept,
        'mastery_state': mastery_state,
        'mastery_percentage': mastery_percentage,
        'prerequisites': concept.prerequisites.all(),
    }

    return render(request, 'dashboard/concept_detail.html', context)


@login_required
def learning_session(request):
    if request.user.user_type != 'student':
        messages.error(request, "Access denied. Student access only.")
        return redirect('home')

    session = get_or_start_session(request.user)
    engine = MasteryEngine(request.user)
    config = ParentStudentConfig.objects.filter(student=request.user).first()
    course = config.courses.first() if config else None

    if config and config.override_starting_point and config.starting_concept:
        concept = config.starting_concept
    else:
        concept = engine.select_next_concept(course=course)

    if not concept:
        messages.info(request, "No eligible concepts found yet.")
        return redirect('student_dashboard')

    mastery_state = MasteryState.objects.filter(user=request.user, concept=concept).first()
    mastery_percentage = (mastery_state.mastery_score * 100) if mastery_state else 0

    youtube_id = fetch_khan_youtube_id(concept.khan_slug) if concept.khan_slug else None

    quiz_url = f"https://www.khanacademy.org/{concept.quiz_slug}" if concept.quiz_slug else None

    encouragement = None
    if mastery_state and mastery_state.frustration_score > 0.7:
        encouragement = get_ai_provider().encourage(request.user)

    context = {
        'concept': concept,
        'youtube_id': youtube_id,
        'quiz_url': quiz_url,
        'mastery_percentage': mastery_percentage,
        'encouragement': encouragement,
        'session': session,
        'hide_nav': True,
    }
    return render(request, 'dashboard/learning_session.html', context)


@login_required
def submit_quiz_result(request):
    if request.user.user_type != 'student':
        messages.error(request, "Access denied. Student access only.")
        return redirect('home')

    if request.method != 'POST':
        messages.error(request, "Invalid request method.")
        return redirect('learning_session')

    concept_id = request.POST.get('concept_id')
    score_percent = request.POST.get('score_percent')

    try:
        score_value = float(score_percent)
    except (TypeError, ValueError):
        messages.error(request, "Invalid quiz score.")
        return redirect('learning_session')

    concept = get_object_or_404(Concept, id=concept_id)

    engine = MasteryEngine(request.user)
    result = engine.update_mastery_after_quiz(concept, score_value)

    session = get_or_start_session(request.user)
    record_quiz(session, concept, score_value)

    explanation = None
    encouragement = None
    if score_value < 50:
        explanation = get_ai_provider().explain(concept, "", "")
    if result.mastery_state.frustration_score > 0.7:
        encouragement = get_ai_provider().encourage(request.user)

    response = render(request, 'dashboard/quiz_feedback.html', {
        'explanation': explanation,
        'encouragement': encouragement,
        'hide_nav': True,
    })
    response['Refresh'] = '2;url=/learn/'
    return response


@login_required
def parent_student_config(request, student_id: int):
    if request.user.user_type != 'parent':
        messages.error(request, "Access denied. Parent access only.")
        return redirect('home')

    student = get_object_or_404(Student, id=student_id)
    if not Parent.objects.filter(user=request.user, students=student).exists():
        messages.error(request, "Student not linked to this parent.")
        return redirect('parent_dashboard')

    config, _ = ParentStudentConfig.objects.get_or_create(
        parent=request.user,
        student=student.user,
    )

    if request.method == 'POST':
        grade_level = request.POST.get('grade_level')
        course_ids = request.POST.getlist('courses')
        khan_classes_raw = request.POST.getlist('khan_classes')
        starting_concept_id = request.POST.get('starting_concept')
        override_start = bool(request.POST.get('override_starting_point'))

        config.grade_level = int(grade_level) if grade_level else None
        config.override_starting_point = override_start
        config.khan_classes = [item.strip() for item in khan_classes_raw if item.strip()]

        if starting_concept_id:
            config.starting_concept = Concept.objects.filter(id=starting_concept_id).first()
        else:
            config.starting_concept = None

        config.save()

        if course_ids:
            config.courses.set(Course.objects.filter(id__in=course_ids))
        else:
            config.courses.clear()

        if config.starting_concept and config.override_starting_point:
            MasteryState.objects.update_or_create(
                user=student.user,
                concept=config.starting_concept,
                defaults={
                    'mastery_score': 0.0,
                    'confidence_score': 0.0,
                    'frustration_score': 0.0,
                    'attempts': 0,
                },
            )

        if hasattr(student.user, 'student_profile') and config.grade_level:
            student.user.student_profile.grade_level = config.grade_level
            student.user.student_profile.save(update_fields=['grade_level'])

        messages.success(request, "Student configuration updated.")
        return redirect('parent_dashboard')

    courses = Course.objects.filter(is_active=True)
    concepts = Concept.objects.filter(is_active=True)
    khan_sync = get_khan_classes()

    context = {
        'student': student,
        'config': config,
        'courses': courses,
        'concepts': concepts,
        'khan_classes': khan_sync.classes,
        'khan_warning': khan_sync.warning,
    }
    return render(request, 'dashboard/parent_student_config.html', context)
