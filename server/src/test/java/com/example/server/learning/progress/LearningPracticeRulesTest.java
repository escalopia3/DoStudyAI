package com.example.server.learning.progress;

import org.junit.jupiter.api.Test;
import java.util.*;

import static org.junit.jupiter.api.Assertions.*;

class LearningPracticeRulesTest {
    @Test void objectiveAnswersAreOrderIndependentAndExact(){
        var question=new HashMap<String,Object>();
        question.put("question_type","SINGLE_CHOICE");question.put("points",4);question.put("correct_answers_json","[\"B\"]");
        var correct=LearningPracticeService.grade(question,List.of("B"));
        var wrong=LearningPracticeService.grade(question,List.of("A"));
        assertTrue(correct.correct());assertEquals(4,correct.score());assertFalse(wrong.correct());assertEquals(0,wrong.score());
    }

    @Test void shortAnswerUsesTransparentKeywordCoverage(){
        var question=new HashMap<String,Object>();
        question.put("question_type","SHORT_ANSWER");question.put("points",10);
        question.put("correct_answers_json","[\"参考答案\"]");question.put("rubric_keywords_json","[\"扇出\",\"磁盘访问\"]");
        var partial=LearningPracticeService.grade(question,"高扇出可以降低树高");
        assertFalse(partial.correct());assertEquals(5,partial.score());assertTrue(partial.feedback().contains("1/2"));
    }

    @Test void answerNormalizationRemovesDuplicatesAndBlanks(){
        assertEquals(List.of("A","B"),LearningPracticeService.normalizeAnswers(List.of(" B ","A","A","")));
    }
}
