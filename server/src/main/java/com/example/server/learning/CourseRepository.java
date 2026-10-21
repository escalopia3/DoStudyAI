package com.example.server.learning;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Repository;
import java.sql.Statement;
import java.util.List;
import java.util.Map;

/** Parameterized SQL only; ownership is enforced by CourseService. */
@Repository
public class CourseRepository {
    private final JdbcTemplate db;
    public CourseRepository(JdbcTemplate db) { this.db = db; }
    public List<Map<String, Object>> rows(String sql, Object... args) {
        return db.queryForList(sql, args);
    }
    public int update(String sql, Object... args) { return db.update(sql, args); }
    public long insert(String sql, Object... args) {
        var keys = new GeneratedKeyHolder();
        db.update(connection -> {
            var statement = connection.prepareStatement(sql, Statement.RETURN_GENERATED_KEYS);
            for (int i = 0; i < args.length; i++) statement.setObject(i + 1, args[i]);
            return statement;
        }, keys);
        if (keys.getKey() == null) throw new IllegalStateException("数据库未返回记录编号");
        return keys.getKey().longValue();
    }
}
