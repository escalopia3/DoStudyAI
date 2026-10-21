package com.example.server.learning;

import com.example.server.common.ErrorCode;
import com.example.server.exception.BusinessException;
import com.example.server.service.MediaService;
import com.example.server.utils.MinioUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.multipart.MultipartFile;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

@Service
public class CourseService {
    private static final Logger log = LoggerFactory.getLogger(CourseService.class);
    private final CourseRepository db;
    private final MediaService media;
    private final MinioUtils storage;
    private final TransactionTemplate tx;
    public CourseService(CourseRepository db, MediaService media, MinioUtils storage, TransactionTemplate tx) {
        this.db = db; this.media = media; this.storage = storage; this.tx = tx;
    }
    private static String text(String value, int limit, boolean required) {
        String clean = value == null ? "" : value.trim();
        if ((required && clean.isEmpty()) || clean.length() > limit)
            throw new IllegalArgumentException("名称或描述为空或超出长度限制");
        return clean;
    }
    public Map<String, Object> requireCourse(long user, long course) {
        var rows = db.rows("SELECT * FROM courses WHERE id=? AND user_id=?", course, user);
        if (rows.isEmpty()) throw new NoSuchElementException("课程不存在");
        return rows.getFirst();
    }
    private void chapter(long course, Long chapter) {
        if (chapter != null && db.rows("SELECT id FROM course_chapters WHERE id=? AND course_id=?", chapter, course).isEmpty())
            throw new IllegalArgumentException("章节不属于当前课程");
    }
    public Map<String, Object> courses(long user, int page, int size) {
        if (page < 1 || page > 100000 || size < 1 || size > 100) throw new IllegalArgumentException("分页参数无效");
        var items = db.rows("SELECT c.*, (SELECT COUNT(*) FROM course_resources cr JOIN learning_resources r ON r.id=cr.resource_id LEFT JOIN media_files m ON m.id=r.media_id AND m.user_id=r.user_id WHERE cr.course_id=c.id AND (r.media_id IS NULL OR m.id IS NOT NULL)) AS resource_count FROM courses c WHERE c.user_id=? ORDER BY c.id DESC LIMIT ? OFFSET ?", user, size, (page-1)*size);
        long total = ((Number) db.rows("SELECT COUNT(*) AS total FROM courses WHERE user_id=?", user).getFirst().get("total")).longValue();
        return Map.of("items", items.stream().map(CourseService::courseDto).toList(), "total", total, "page", page, "size", size);
    }
    public Map<String, Object> create(long user, String name, String semester, String description) {
        long id = db.insert("INSERT INTO courses(user_id,name,semester,description) VALUES(?,?,?,?)", user, text(name,100,true),text(semester,50,false),text(description,1000,false));
        return detail(user,id);
    }
    public Map<String, Object> detail(long user, long course) {
        var dto = courseDto(requireCourse(user,course));
        dto.put("chapters",db.rows("SELECT id,name,sort_order FROM course_chapters WHERE course_id=? ORDER BY sort_order,id",course).stream().map(row -> Map.of("id", row.get("id").toString(), "name",row.get("name"), "sortOrder",row.get("sort_order"))).toList());
        return dto;
    }
    public Map<String, Object> createChapter(long user,long course,String name) {
        String clean = text(name,100,true);
        return tx.execute(status -> {
            requireCourse(user,course);
            db.rows("SELECT id FROM courses WHERE id=? FOR UPDATE",course);
            int order = ((Number)db.rows("SELECT COALESCE(MAX(sort_order),0)+1 AS n FROM course_chapters WHERE course_id=?",course).getFirst().get("n")).intValue();
            long id = db.insert("INSERT INTO course_chapters(course_id,name,sort_order) VALUES(?,?,?)",course,clean,order);
            return Map.of("id",Long.toString(id),"name",clean,"sortOrder",order);
        });
    }
    public List<Map<String,Object>> resources(long user,long course,Long chapter,boolean unassigned) {
        requireCourse(user,course); chapter(course,chapter);
        if (chapter != null && unassigned) throw new IllegalArgumentException("章节筛选冲突");
        String filter = chapter != null ? " AND cr.chapter_id=?" : unassigned ? " AND cr.chapter_id IS NULL" : "";
        String sql = "SELECT r.*,cr.chapter_id,m.status AS video_status FROM course_resources cr JOIN learning_resources r ON r.id=cr.resource_id LEFT JOIN media_files m ON m.id=r.media_id AND m.user_id=r.user_id WHERE cr.course_id=? AND r.user_id=? AND (r.media_id IS NULL OR m.id IS NOT NULL)"+filter+" ORDER BY r.id DESC";
        return (chapter == null ? db.rows(sql,course,user) : db.rows(sql,course,user,chapter)).stream().map(CourseService::resourceDto).toList();
    }
    public List<Map<String,Object>> availableVideos(long user) {
        return db.rows("SELECT m.id,m.filename,m.status FROM media_files m LEFT JOIN learning_resources r ON r.media_id=m.id LEFT JOIN course_resources cr ON cr.resource_id=r.id WHERE m.user_id=? AND cr.resource_id IS NULL ORDER BY m.id DESC",user).stream().map(row -> Map.<String,Object>of("id",row.get("id").toString(),"filename",row.get("filename"),"status",row.get("status"))).toList();
    }
    public Map<String,Object> addVideo(long user,long course,Long chapter,long mediaId) {
        return tx.execute(status -> {
            requireCourse(user,course); chapter(course,chapter);
            // Lock the original video so concurrent joins cannot assign it twice.
            if (db.rows("SELECT id FROM media_files WHERE id=? AND user_id=? FOR UPDATE",mediaId,user).isEmpty())
                throw new NoSuchElementException("视频不存在");
            var source = media.requireOwnedMedia(mediaId,user);
            var rows = db.rows("SELECT id FROM learning_resources WHERE media_id=?",mediaId);
            long id = rows.isEmpty() ? db.insert("INSERT INTO learning_resources(user_id,type,media_id,filename,parse_status) VALUES(?,'VIDEO',?,?,'VIDEO_PIPELINE')",user,mediaId,source.getFilename()) : ((Number)rows.getFirst().get("id")).longValue();
            var memberships = db.rows("SELECT course_id,chapter_id FROM course_resources WHERE resource_id=?",id);
            if (!memberships.isEmpty()) {
                var existing = memberships.getFirst();
                if (((Number)existing.get("course_id")).longValue()!=course || !Objects.equals(number(existing.get("chapter_id")),chapter))
                    throw new BusinessException(ErrorCode.CONFLICT,"视频已加入课程，请勿重复归档");
            } else db.update("INSERT INTO course_resources(resource_id,course_id,chapter_id) VALUES(?,?,?)",id,course,chapter);
            return Map.of("id",Long.toString(id),"mediaId",Long.toString(mediaId));
        });
    }
    public Map<String,Object> upload(long user,long course,Long chapter,MultipartFile file,String key) throws Exception {
        requireCourse(user,course); chapter(course,chapter);
        if (key == null || !key.matches("[A-Za-z0-9_-]{8,100}")) throw new IllegalArgumentException("上传请求标识无效");
        String type = DocumentUploadValidator.validate(file);
        String filename = DocumentUploadValidator.filename(file.getOriginalFilename());
        String fingerprint = fingerprint(course, chapter, filename, file);
        var receipt = uploadReceipt(user, key, fingerprint);
        if (receipt != null) return receipt;
        String object = "learning/"+user+"/"+UUID.randomUUID()+"."+type.toLowerCase(Locale.ROOT);
        // File I/O is outside the DB transaction. Failed/duplicate commits clean up only this new object.
        try {
            try (var input = file.getInputStream()) {
                storage.uploadObject(object, input, file.getSize(), contentType(type));
            }
            UploadCommit result = tx.execute(status -> {
                // Serialize receipt commits per account, including simultaneous requests with the same key.
                if (db.rows("SELECT id FROM users WHERE id=? FOR UPDATE", user).isEmpty())
                    throw new NoSuchElementException("用户不存在");
                requireCourse(user,course); chapter(course,chapter);
                var duplicate = uploadReceipt(user, key, fingerprint);
                if (duplicate != null) return new UploadCommit(duplicate, false);
                long id = db.insert("INSERT INTO learning_resources(user_id,type,filename,object_key,size_bytes,upload_key,request_fingerprint) VALUES(?,?,?,?,?,?,?)",user,type,filename,object,file.getSize(),key,fingerprint);
                db.update("INSERT INTO course_resources(resource_id,course_id,chapter_id) VALUES(?,?,?)",id,course,chapter);
                return new UploadCommit(Map.of("id",Long.toString(id),"filename",filename,"status","UPLOADED"), true);
            });
            if (!result.created()) cleanupUpload(object);
            return result.data();
        } catch (Exception error) {
            // A lost DB commit acknowledgement is ambiguous. Never delete an object
            // that may already belong to a committed resource; keep it if DB is unavailable.
            try {
                if (db.rows("SELECT id FROM learning_resources WHERE object_key=?", object).isEmpty()) cleanupUpload(object);
            } catch (RuntimeException lookupFailure) {
                log.warn("learning_upload_commit_uncertain object={}",object);
            }
            throw error;
        }
    }
    private record UploadCommit(Map<String,Object> data, boolean created) {}

    private Map<String,Object> uploadReceipt(long user, String key, String fingerprint) {
        var rows = db.rows("SELECT id,filename,parse_status,request_fingerprint FROM learning_resources WHERE user_id=? AND upload_key=?",user,key);
        if (rows.isEmpty()) return null;
        var row = rows.getFirst();
        if (!fingerprint.equals(row.get("request_fingerprint")))
            throw new BusinessException(ErrorCode.CONFLICT,"上传标识已用于不同文件或归档位置，请刷新后重新上传");
        return Map.of("id",row.get("id").toString(),"filename",row.get("filename"),"status",row.get("parse_status"));
    }

    static String fingerprint(long course, Long chapter, String filename, MultipartFile file) throws Exception {
        var digest = MessageDigest.getInstance("SHA-256");
        digest.update((course + "\n" + chapter + "\n" + filename + "\n" + file.getSize() + "\n").getBytes(StandardCharsets.UTF_8));
        try (var input = file.getInputStream()) {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer,0,count);
        }
        return HexFormat.of().formatHex(digest.digest());
    }

    private static String contentType(String type) {
        return switch (type) {
            case "PDF" -> "application/pdf";
            case "DOCX" -> "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
            case "PPTX" -> "application/vnd.openxmlformats-officedocument.presentationml.presentation";
            default -> "application/octet-stream";
        };
    }

    private void cleanupUpload(String object) {
        try { storage.removeObject(object); }
        catch (RuntimeException cleanup) {
            // Retain the exact object key for an operator; never scan/delete the old video prefix.
            log.warn("learning_upload_cleanup_required object={}",object);
        }
    }
    public Map<String,Object> file(long user,long resource) {
        var rows = db.rows("SELECT * FROM learning_resources WHERE id=? AND user_id=?",resource,user);
        if (rows.isEmpty()) throw new NoSuchElementException("资料不存在");
        var row=rows.getFirst();
        if (row.get("media_id")!=null) {
            var source=media.requireOwnedMedia(((Number)row.get("media_id")).longValue(),user);
            return Map.of("url",media.readableSource(source.getFilePath()));
        }
        return Map.of("url",storage.readableSource(storage.objectUrl(row.get("object_key").toString())));
    }
    private static Long number(Object value) { return value == null ? null : ((Number)value).longValue(); }
    private static Map<String,Object> courseDto(Map<String,Object> row) {
        var dto = new LinkedHashMap<String,Object>();
        dto.put("id",row.get("id").toString()); dto.put("name",row.get("name"));
        dto.put("semester",row.get("semester")); dto.put("description",row.get("description"));
        dto.put("resourceCount",row.getOrDefault("resource_count",0)); return dto;
    }
    private static Map<String,Object> resourceDto(Map<String,Object> row) {
        var dto=new LinkedHashMap<String,Object>();
        dto.put("id",row.get("id").toString()); dto.put("filename",row.get("filename")); dto.put("type",row.get("type"));
        dto.put("chapterId",row.get("chapter_id")==null?null:row.get("chapter_id").toString());
        dto.put("mediaId",row.get("media_id")==null?null:row.get("media_id").toString());
        dto.put("parseJobId",row.get("parsing_job_id"));
        dto.put("parseStatus",row.get("parse_status"));
        dto.put("status",row.get("video_status")==null?row.get("parse_status"):row.get("video_status")); dto.put("sizeBytes",row.get("size_bytes"));
        return dto;
    }
}
