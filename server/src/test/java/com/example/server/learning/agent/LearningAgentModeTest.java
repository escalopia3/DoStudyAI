package com.example.server.learning.agent;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class LearningAgentModeTest {
    @Test
    void acceptsRevisionAndAssessmentModes() {
        assertEquals("REVIEW", LearningAgentService.normalizeMode("REVIEW"));
        assertEquals("PRACTICE", LearningAgentService.normalizeMode("PRACTICE"));
        assertEquals("MOCK_EXAM", LearningAgentService.normalizeMode("MOCK_EXAM"));
    }

    @Test
    void unknownOrMissingModesFailSafeToQa() {
        assertEquals("QA", LearningAgentService.normalizeMode("UNKNOWN"));
        assertEquals("QA", LearningAgentService.normalizeMode(null));
    }
}
