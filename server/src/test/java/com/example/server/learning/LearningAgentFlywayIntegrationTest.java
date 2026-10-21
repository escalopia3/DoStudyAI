package com.example.server.learning;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

import static org.junit.jupiter.api.Assertions.assertEquals;

/** Explicit local integration check; never touches a database during the default test suite. */
@EnabledIfEnvironmentVariable(named = "RUN_LEARNING_AGENT_DB_MIGRATION", matches = "true")
class LearningAgentFlywayIntegrationTest {
    @Test
    void migratesLearningBusinessTablesToVersionTwelve() {
        String url = System.getenv().getOrDefault("DB_URL",
            "jdbc:mysql://127.0.0.1:3307/media_db?useSSL=false&serverTimezone=Asia/Shanghai&characterEncoding=utf-8&allowPublicKeyRetrieval=true");
        Flyway flyway = Flyway.configure()
            .dataSource(url, required("DB_USERNAME"), required("DB_PASSWORD"))
            .locations("classpath:db/migration")
            .baselineOnMigrate(true)
            .baselineVersion("0")
            .load();
        flyway.migrate();
        assertEquals("12", flyway.info().current().getVersion().getVersion());
    }

    private static String required(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) throw new IllegalStateException(name + " is required");
        return value;
    }
}
