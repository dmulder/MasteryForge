"""
AI Provider for KinderForge - OpenAI integration
"""
import json
import os
import urllib.error
import urllib.request
import logging
from typing import Optional, Dict, List, Any


logger = logging.getLogger(__name__)


class AIProvider:
    """
    Stub implementation of AI provider using OpenAI API
    
    This class provides AI-powered features like:
    - Generating personalized hints
    - Creating practice problems
    - Providing explanations
    - Analyzing student responses
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        azure_resource_name: Optional[str] = None,
        azure_api_key: Optional[str] = None,
        azure_deployment: Optional[str] = None,
        azure_api_version: Optional[str] = None,
        azure_model: Optional[str] = None,
    ):
        """
        Initialize the AI provider
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            azure_resource_name: Azure OpenAI resource name
            azure_api_key: Azure OpenAI API key
            azure_deployment: Azure OpenAI deployment name
            azure_api_version: Azure OpenAI API version
            azure_model: Model name to include in request (optional)
        """
        self.api_key = api_key or os.environ.get('OPENAI_API_KEY')
        self.model = os.environ.get('OPENAI_MODEL', 'gpt-4')
        self.azure_resource_name = azure_resource_name or os.environ.get('AZURE_OPENAI_RESOURCE_NAME')
        self.azure_api_key = azure_api_key or os.environ.get('AZURE_OPENAI_API_KEY')
        self.azure_deployment = (
            azure_deployment
            or os.environ.get('AZURE_OPENAI_DEPLOYMENT')
            or os.environ.get('AZURE_OPENAI_MODEL')
            or 'gpt-5.2-codex'
        )
        self.azure_api_version = azure_api_version or os.environ.get('AZURE_OPENAI_API_VERSION', '2024-02-15-preview')
        self.azure_responses_api_version = os.environ.get('AZURE_OPENAI_RESPONSES_API_VERSION') or self.azure_api_version
        self.azure_use_responses = os.environ.get('AZURE_OPENAI_USE_RESPONSES', '').lower() in {'1', 'true', 'yes', 'on'}
        self.azure_use_v1 = os.environ.get('AZURE_OPENAI_USE_V1', '').lower() in {'1', 'true', 'yes', 'on'}
        self.azure_base_url = os.environ.get('AZURE_OPENAI_BASE_URL')
        self.azure_responses_endpoint = os.environ.get('AZURE_OPENAI_RESPONSES_ENDPOINT')
        self._force_responses = False
        self.azure_model = azure_model or os.environ.get('AZURE_OPENAI_MODEL')
        self.use_azure = bool(self.azure_resource_name and self.azure_api_key)
        logger.debug(
            "AI provider init: use_azure=%s resource_name=%s deployment=%s api_version=%s model=%s",
            self.use_azure,
            self.azure_resource_name or "(missing)",
            self.azure_deployment,
            self.azure_api_version,
            self.azure_model or "(none)",
        )

    def _azure_chat_completion(self, messages: List[Dict[str, str]], temperature: float = 0.2, max_tokens: int = 400) -> Optional[str]:
        if not self.use_azure:
            logger.debug("Azure AI disabled (missing resource name or API key).")
            return None
        if self._should_use_responses():
            return self._azure_responses(messages, temperature=temperature, max_tokens=max_tokens)

        url = (
            f"https://{self.azure_resource_name}.openai.azure.com/openai/deployments/"
            f"{self.azure_deployment}/chat/completions?api-version={self.azure_api_version}"
        )
        logger.debug(
            "Azure AI request: deployment=%s api_version=%s model=%s message_count=%s",
            self.azure_deployment,
            self.azure_api_version,
            self.azure_model or "(none)",
            len(messages),
        )
        payload: Dict[str, Any] = {
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
        }
        if self.azure_model:
            payload['model'] = self.azure_model

        data = json.dumps(payload).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'api-key': self.azure_api_key,
        }

        request = urllib.request.Request(url, data=data, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                logger.debug("Azure AI response: status=%s", response.status)
                body = response.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode('utf-8')
            except Exception:
                logger.debug("Azure AI error: HTTP %s (no body)", exc.code)
                return None
            logger.debug("Azure AI error: HTTP %s body=%s", exc.code, body)
            self._set_last_azure_error(body)
        except Exception as exc:
            logger.debug("Azure AI error: request failed (%s)", exc)
            return None

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            logger.debug("Azure AI error: invalid JSON response")
            return None

        choices = payload.get('choices', [])
        if not choices:
            logger.debug("Azure AI error: no choices in response")
            return None
        message = choices[0].get('message', {})
        return message.get('content')

    def _azure_responses(self, messages: List[Dict[str, str]], temperature: float = 0.2, max_tokens: int = 400) -> Optional[str]:
        if self.azure_responses_endpoint:
            url = self.azure_responses_endpoint
        elif self.azure_use_v1 or self.azure_base_url:
            base_url = self.azure_base_url or f"https://{self.azure_resource_name}.openai.azure.com/openai/v1"
            url = f"{base_url.rstrip('/')}/responses"
        else:
            url = (
                f"https://{self.azure_resource_name}.openai.azure.com/openai/deployments/"
                f"{self.azure_deployment}/responses?api-version={self.azure_responses_api_version}"
            )
        instructions, input_messages = self._split_instructions(messages)
        payload: Dict[str, Any] = {
            'input': input_messages,
            'max_output_tokens': max_tokens,
        }
        if self._responses_supports_temperature():
            payload['temperature'] = temperature
        if instructions:
            payload['instructions'] = instructions
        if self.azure_model:
            payload['model'] = self.azure_model

        data = json.dumps(payload).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'api-key': self.azure_api_key,
        }
        logger.debug(
            "Azure AI responses request: deployment=%s api_version=%s model=%s input_messages=%s v1=%s endpoint=%s",
            self.azure_deployment,
            self.azure_responses_api_version,
            self.azure_model or "(none)",
            len(input_messages),
            self.azure_use_v1 or bool(self.azure_base_url),
            "custom" if self.azure_responses_endpoint else "default",
        )
        request = urllib.request.Request(url, data=data, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                logger.debug("Azure AI responses: status=%s", response.status)
                body = response.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode('utf-8')
            except Exception:
                logger.debug("Azure AI responses error: HTTP %s (no body)", exc.code)
                return None
            logger.debug("Azure AI responses error: HTTP %s body=%s", exc.code, body)
            if self._should_retry_without_temperature(body, payload):
                return self._retry_responses_without_temperature(
                    url,
                    payload,
                    headers,
                )
            self._set_last_azure_error(body)
            return None
        except Exception as exc:
            logger.debug("Azure AI responses error: request failed (%s)", exc)
            return None

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            logger.debug("Azure AI responses error: invalid JSON response")
            return None

        content = self._extract_responses_text(payload)
        if not content:
            logger.debug("Azure AI responses error: empty output_text")
        return content

    def _retry_responses_without_temperature(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> Optional[str]:
        payload = dict(payload)
        payload.pop('temperature', None)
        data = json.dumps(payload).encode('utf-8')
        request = urllib.request.Request(url, data=data, headers=headers, method='POST')
        logger.debug("Azure AI responses retry without temperature.")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                logger.debug("Azure AI responses retry: status=%s", response.status)
                body = response.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode('utf-8')
            except Exception:
                logger.debug("Azure AI responses retry error: HTTP %s (no body)", exc.code)
                return None
            logger.debug("Azure AI responses retry error: HTTP %s body=%s", exc.code, body)
            self._set_last_azure_error(body)
            return None
        except Exception as exc:
            logger.debug("Azure AI responses retry error: request failed (%s)", exc)
            return None

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            logger.debug("Azure AI responses retry error: invalid JSON response")
            return None
        content = self._extract_responses_text(payload)
        if not content:
            logger.debug("Azure AI responses retry error: empty output_text")
        return content

    def _extract_responses_text(self, payload: Dict[str, Any]) -> Optional[str]:
        output_text = payload.get('output_text')
        if isinstance(output_text, str) and output_text.strip():
            return output_text
        output = payload.get('output', [])
        texts: List[str] = []
        for item in output:
            if item.get('type') != 'message':
                continue
            for content in item.get('content', []):
                if content.get('type') == 'output_text' and content.get('text'):
                    texts.append(content['text'])
        if texts:
            return "\n".join(texts)
        return None

    def _split_instructions(self, messages: List[Dict[str, str]]) -> tuple[str, List[Dict[str, str]]]:
        instructions_parts: List[str] = []
        input_messages: List[Dict[str, str]] = []
        for message in messages:
            role = message.get('role')
            content = message.get('content', '')
            if role == 'system' and content:
                instructions_parts.append(str(content))
            else:
                input_messages.append({'role': role, 'content': content})
        instructions = "\n\n".join(instructions_parts).strip()
        return instructions, input_messages

    def _set_last_azure_error(self, body: str) -> None:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return
        error = payload.get('error', {})
        code = error.get('code')
        if code == 'OperationNotSupported':
            self._force_responses = True
            logger.debug("Azure AI: OperationNotSupported, forcing responses endpoint.")

    def _should_use_responses(self) -> bool:
        if self._force_responses or self.azure_use_responses:
            return True
        deployment = (self.azure_deployment or '').lower()
        model = (self.azure_model or '').lower()
        if deployment.startswith('gpt-5') or model.startswith('gpt-5'):
            return True
        return False

    def _responses_supports_temperature(self) -> bool:
        model = (self.azure_model or '').lower()
        deployment = (self.azure_deployment or '').lower()
        if model.startswith('gpt-5') or deployment.startswith('gpt-5'):
            return False
        return True

    def _should_retry_without_temperature(self, body: str, payload: Dict[str, Any]) -> bool:
        if 'temperature' not in payload:
            return False
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return False
        error = parsed.get('error', {})
        return error.get('param') == 'temperature'

    def _try_parse_json(self, content: str) -> Optional[Dict[str, Any]]:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
        return None

    def _try_parse_json_value(self, content: str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None
    
    def generate_hint(self, concept_id: str, user_context: Dict) -> str:
        """
        Generate a personalized hint for a concept
        
        Args:
            concept_id: The concept ID
            user_context: Dictionary with user's mastery state, previous attempts, etc.
        
        Returns:
            A personalized hint string
        """
        mastery_score = user_context.get('mastery_score', 0.0)
        frustration_score = user_context.get('frustration_score', 0.0)

        if self.use_azure:
            content = self._azure_chat_completion(
                messages=[
                    {
                        'role': 'system',
                        'content': 'You are a supportive tutor. Keep hints short and encouraging.',
                    },
                    {
                        'role': 'user',
                        'content': (
                            'Generate a hint for concept: {concept_id}. '
                            'User mastery score: {mastery_score}. Frustration score: {frustration_score}.'
                        ).format(
                            concept_id=concept_id,
                            mastery_score=mastery_score,
                            frustration_score=frustration_score,
                        ),
                    },
                ],
                max_tokens=120,
            )
            if content:
                return content.strip()

        if frustration_score > 0.7:
            return f"Let's take a step back and review the basics of {concept_id}. You're doing great - this is challenging material!"
        if mastery_score < 0.3:
            return f"For {concept_id}, start with the foundational concepts. Break it down into smaller steps."
        return f"You're making good progress on {concept_id}! Try approaching it from a different angle."

    def explain(self, concept, question: str, answer: str) -> str:
        """Provide an explanation after a failed quiz."""
        concept_title = getattr(concept, 'title', str(concept))

        if self.use_azure:
            content = self._azure_chat_completion(
                messages=[
                    {
                        'role': 'system',
                        'content': 'You explain mistakes kindly and clearly in 3-5 sentences.',
                    },
                    {
                        'role': 'user',
                        'content': (
                            'Explain why the answer might be wrong for concept: {concept}. '
                            'Question: {question} Answer: {answer}. '
                            'Keep it encouraging.'
                        ).format(concept=concept_title, question=question, answer=answer),
                    },
                ],
                max_tokens=200,
            )
            if content:
                return content.strip()

        return (
            f"Let's revisit {concept_title}. Review the key steps and try a simpler example first. "
            "You're making progress, and this concept can take a few tries."
        )

    def recommend_concepts(self, user, concepts: List[Dict], mastery_states: Dict) -> List[str]:
        """Suggest concepts to review based on confidence signals."""
        if self.use_azure:
            content = self._azure_chat_completion(
                messages=[
                    {
                        'role': 'system',
                        'content': 'Return JSON array of concept ids to review. Use provided mastery states.',
                    },
                    {
                        'role': 'user',
                        'content': json.dumps({
                            'concepts': concepts,
                            'mastery_states': mastery_states,
                        }),
                    },
                ],
                max_tokens=200,
            )
            if content:
                parsed = self._try_parse_json_value(content)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]

        scored = []
        for concept in concepts:
            state = mastery_states.get(str(concept.get('id')))
            confidence = state.get('confidence_score', 0.0) if state else 0.0
            mastery = state.get('mastery_score', 0.0) if state else 0.0
            scored.append((concept.get('id'), confidence, mastery))

        scored.sort(key=lambda item: (item[1], item[2]))
        return [str(item[0]) for item in scored[:3] if item[0]]

    def recommend_next_lesson(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Recommend the next lesson to study based on recent performance and course structure.

        Returns JSON with keys: next_concept_id (string), reason (string), repeat (boolean).
        """
        if not self.use_azure:
            logger.debug("Azure AI recommend_next_lesson: skipped (Azure not configured).")
            return None

        content = self._azure_chat_completion(
            messages=[
                {
                    'role': 'system',
                    'content': (
                        "You are an expert learning coach. Choose the next lesson id that best helps the student "
                        "succeed while minimizing frustration. Prefer the next lesson in sequence when performance "
                        "is solid. Avoid repeating lessons with high scores. Repeat or reinforce lessons with low "
                        "scores when needed. If performance is repeatedly poor or frustration is high, you may pivot "
                        "to a prerequisite or a nearby topic and return later. Respond with JSON only."
                    ),
                },
                {
                    'role': 'user',
                    'content': json.dumps(context),
                },
            ],
            max_tokens=220,
        )
        if not content:
            logger.debug("Azure AI recommend_next_lesson: empty response")
            return None

        parsed = self._try_parse_json(content)
        if not parsed:
            logger.debug("Azure AI recommend_next_lesson: invalid JSON response")
            return None
        if 'next_concept_id' not in parsed:
            logger.debug("Azure AI recommend_next_lesson: missing next_concept_id")
            return None
        logger.debug(
            "Azure AI recommend_next_lesson: next_concept_id=%s reason=%s repeat=%s",
            parsed.get('next_concept_id'),
            parsed.get('reason'),
            parsed.get('repeat'),
        )
        return parsed

    def encourage(self, user) -> str:
        """Provide encouragement when frustration is high."""
        name = getattr(user, 'first_name', '') or getattr(user, 'username', 'there')

        if self.use_azure:
            content = self._azure_chat_completion(
                messages=[
                    {
                        'role': 'system',
                        'content': 'You are a supportive coach. Keep encouragement short and warm.',
                    },
                    {
                        'role': 'user',
                        'content': f"Encourage {name} to keep going with their learning session.",
                    },
                ],
                max_tokens=100,
            )
            if content:
                return content.strip()

        return f"You're doing great, {name}. Let's take a small step and keep the momentum going."
    
    def generate_problem(self, concept_id: str, difficulty: int = 1) -> Dict:
        """
        Generate a practice problem for a concept
        
        Args:
            concept_id: The concept ID
            difficulty: Difficulty level (1-5)
        
        Returns:
            Dictionary with 'question', 'answer', and 'explanation' keys
        """
        if self.use_azure:
            content = self._azure_chat_completion(
                messages=[
                    {
                        'role': 'system',
                        'content': 'You generate practice problems as JSON only.',
                    },
                    {
                        'role': 'user',
                        'content': (
                            'Create a practice problem for concept "{concept_id}" at difficulty {difficulty}. '
                            'Return JSON with keys: question, answer, explanation.'
                        ).format(concept_id=concept_id, difficulty=difficulty),
                    },
                ],
                max_tokens=350,
            )
            if content:
                parsed = self._try_parse_json(content)
                if parsed and {'question', 'answer', 'explanation'}.issubset(parsed.keys()):
                    parsed['concept_id'] = concept_id
                    parsed['difficulty'] = difficulty
                    return parsed

        return {
            'question': f"Sample problem for concept {concept_id} at difficulty level {difficulty}",
            'answer': "Sample answer",
            'explanation': "This is a stub explanation. In production, this would be generated by the AI model.",
            'concept_id': concept_id,
            'difficulty': difficulty,
        }
    
    def explain_concept(self, concept_id: str, level: str = "basic") -> str:
        """
        Generate an explanation for a concept
        
        Args:
            concept_id: The concept ID
            level: Explanation level ('basic', 'intermediate', 'advanced')
        
        Returns:
            Explanation text
        """
        if self.use_azure:
            content = self._azure_chat_completion(
                messages=[
                    {
                        'role': 'system',
                        'content': 'You explain concepts clearly and concisely.',
                    },
                    {
                        'role': 'user',
                        'content': f"Explain concept {concept_id} at a {level} level.",
                    },
                ],
                max_tokens=300,
            )
            if content:
                return content.strip()

        return f"Explanation for {concept_id} at {level} level. This is a stub implementation that would use OpenAI API in production."
    
    def analyze_response(self, concept_id: str, question: str, user_answer: str, correct_answer: str) -> Dict:
        """
        Analyze a user's response to provide feedback
        
        Args:
            concept_id: The concept ID
            question: The question text
            user_answer: User's answer
            correct_answer: The correct answer
        
        Returns:
            Dictionary with 'is_correct', 'feedback', and 'suggestions' keys
        """
        is_correct = user_answer.strip().lower() == correct_answer.strip().lower()

        if self.use_azure:
            content = self._azure_chat_completion(
                messages=[
                    {
                        'role': 'system',
                        'content': 'You analyze answers and respond as JSON only.',
                    },
                    {
                        'role': 'user',
                        'content': (
                            'Evaluate the user answer for concept "{concept_id}". '
                            'Question: {question} '
                            'User answer: {user_answer} '
                            'Correct answer: {correct_answer} '
                            'Return JSON with keys: is_correct (boolean), feedback (string), suggestions (array of strings).'
                        ).format(
                            concept_id=concept_id,
                            question=question,
                            user_answer=user_answer,
                            correct_answer=correct_answer,
                        ),
                    },
                ],
                max_tokens=300,
            )
            if content:
                parsed = self._try_parse_json(content)
                if parsed and {'is_correct', 'feedback', 'suggestions'}.issubset(parsed.keys()):
                    return parsed

        feedback = {
            'is_correct': is_correct,
            'feedback': "Correct!" if is_correct else "Not quite right. Let's review this concept.",
            'suggestions': [] if is_correct else [
                f"Review the basics of {concept_id}",
                "Try breaking down the problem into smaller steps",
                "Check your understanding of prerequisite concepts",
            ],
        }

        return feedback
    
    def get_personalized_learning_path(self, user, current_concepts: List[str], mastery_states: Dict) -> List[str]:
        """
        Generate a personalized learning path
        
        Args:
            user: User object
            current_concepts: List of available concept IDs
            mastery_states: Dictionary of concept_id -> mastery state
        
        Returns:
            Ordered list of concept IDs forming a learning path
        """
        # Stub implementation - simple ordering by difficulty and prerequisites
        # In production, this would use AI to personalize based on learning style, pace, etc.
        return current_concepts[:5] if len(current_concepts) > 5 else current_concepts


# Global instance
_ai_provider = None


def get_ai_provider() -> AIProvider:
    """Get the global AI provider instance"""
    global _ai_provider
    if _ai_provider is None:
        _ai_provider = AIProvider()
        logger.debug("AI provider initialized (use_azure=%s).", _ai_provider.use_azure)
    return _ai_provider
