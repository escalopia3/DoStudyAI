"""Run tests that do not require local sockets, Docling weights, or external services.

This intentionally does not claim HTTP or live MySQL/MQ/MinIO integration coverage.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
test_temp=root/'.learning-work'/'test-temp'
test_temp.mkdir(parents=True,exist_ok=True)
os.environ['TEMP']=str(test_temp)
os.environ['TMP']=str(test_temp)
tempfile.tempdir=str(test_temp)
from agent_service.tests.test_queue import QueueTests

suite=unittest.TestSuite()
suite.addTests(QueueTests(name) for name in unittest.defaultTestLoader.getTestCaseNames(QueueTests)
               if name != 'test_api_auth_validation_and_cancel')
suite.addTests(unittest.defaultTestLoader.loadTestsFromName('agent_service.tests.test_worker'))
suite.addTests(unittest.defaultTestLoader.loadTestsFromName('agent_service.tests.test_parsing'))
suite.addTests(unittest.defaultTestLoader.loadTestsFromName('agent_service.tests.test_learning_agent'))
suite.addTests(unittest.defaultTestLoader.discover(str(root/'knowledge_service/tests')))
result=unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
