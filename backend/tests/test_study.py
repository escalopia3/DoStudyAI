import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pydantic import ValidationError
from dovideo.agents.study import memory_candidate
from dovideo.routers.agents import AttemptInput, practice_attempt

class StudyTests(unittest.TestCase):
    def test_submit_uses_stored_answer(self):
        question_id=uuid.uuid4()
        with self.assertRaises(ValidationError):
            AttemptInput(question_id=question_id,submitted_answer='B',expected_answer='B')
        session=Mock()
        session.scalar.return_value=SimpleNamespace(
            id=question_id,question='选择正确答案',expected_answer='A',evidence=[{'source_id':'S1'}])
        with patch('dovideo.routers.agents.require_owned_course'):
            result=practice_attempt(uuid.uuid4(),AttemptInput(question_id=question_id,submitted_answer='B'),
                                    session,SimpleNamespace(id=uuid.uuid4()))
        self.assertFalse(result['correct'])
        self.assertEqual(session.add.call_args.args[0].source_ids,['S1'])

    def test_memory_requires_explicit_statement(self):
        self.assertEqual(memory_candidate('我的学习目标是理解递归。'),('goal','理解递归'))
        self.assertIsNone(memory_candidate('什么是递归？'))
