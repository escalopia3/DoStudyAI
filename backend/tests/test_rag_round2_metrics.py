import unittest
from tools.rag_round2_metrics import aggregate


class EvaluationMetricsTests(unittest.TestCase):
    def test_missing_formula_evidence_stays_in_denominator(self):
        cases={'Q1':{'answerable':True},'Q2':{'answerable':True},'Q3':{'answerable':False}}
        results={q:{'status':'SUCCEEDED','elapsed_seconds':1,'usage':{}} for q in cases}
        grade=lambda units,candidates:{'required_unit_count':units,'answer_score':2,'candidates':candidates,
            'returned_unit_ids':[],'sent_unit_ids':[],'claims':[],'citations':[]}
        grades={'Q1':grade(1,[{'candidate_id':'C1','supported_unit_ids':['definition']}]),
                'Q2':grade(1,[]),'Q3':grade(0,[])}
        metrics=aggregate(cases,results,grades)
        self.assertEqual(.5,metrics['hit_at_8'])
        self.assertEqual(.5,metrics['evidence_unit_recall_at_8'])
        self.assertEqual(.5,metrics['mrr_at_8'])
        self.assertEqual(1/16,metrics['precision_at_8'])
        self.assertIsNone(metrics['faithfulness'])
        self.assertIsNone(metrics['evidence_delivery_rate'])
        with self.assertRaisesRegex(ValueError,'INCOMPLETE'):aggregate(cases,{},grades)


if __name__=='__main__':unittest.main()
