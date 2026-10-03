import importlib.util
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('football_todo_update',Path(__file__).parents[1]/'scripts'/'update-football-hub-todo.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class FootballTodoTests(unittest.TestCase):
    def project(self):
        return {'id':'football-hub','bucket':'projects','description':'Original',
                'subtasks':[{'id':f'football-hub-st-{i}','title':str(i),'done':False,'description':'User note'} for i in range(1,23) if i!=21]}

    def test_only_reviewed_project_is_updated_and_ids_preserved(self):
        project=self.project()
        other={'id':'oscar','subtasks':[{'done':False}], 'nested':{'value':1}}
        result=module.update([project,other],12345)
        self.assertEqual(result[1],other)
        self.assertEqual(sum(t['done'] for t in result[0]['subtasks']),19)
        self.assertEqual([t['id'] for t in result[0]['subtasks']],[t['id'] for t in project['subtasks']])
        self.assertFalse(any(t['done'] for t in project['subtasks']))
        self.assertTrue(result[0]['description'].startswith('Original'))

    def test_unknown_subtask_list_requires_review(self):
        project=self.project();project['subtasks'].pop()
        with self.assertRaises(ValueError):module.update([project],1)

    def test_repeated_update_does_not_duplicate_notes(self):
        result=module.update(module.update([self.project()],1),2)[0]
        self.assertEqual(result['description'].count('[Football Hub audit]'),1)
        self.assertTrue(result['subtasks'][9]['description'].startswith('User note'))
        self.assertEqual(result['subtasks'][9]['description'].count('[Football Hub audit]'),1)
