package com.example.server.learning.progress;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class LearningMemoryRulesTest {
    @Test void acceptsOnlyExplicitMemoryTypes(){
        assertEquals("PREFERENCE",LearningMemoryService.type("PREFERENCE"));
        assertThrows(IllegalArgumentException.class,()->LearningMemoryService.type("COURSE_FACT"));
    }

    @Test void trimsAndBoundsMemoryContent(){
        assertEquals("先举例",LearningMemoryService.content(" 先举例 "));
        assertThrows(IllegalArgumentException.class,()->LearningMemoryService.content(" "));
        assertThrows(IllegalArgumentException.class,()->LearningMemoryService.content("x".repeat(1001)));
    }
}
