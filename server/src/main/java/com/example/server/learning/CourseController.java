package com.example.server.learning;

import com.example.server.common.Result;
import com.example.server.service.AuthService;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/learn")
public class CourseController {
    private final CourseService service;
    public CourseController(CourseService service) { this.service=service; }
    public record CourseInput(String name,String semester,String description) {}
    public record ChapterInput(String name) {}
    public record VideoInput(Long mediaId,Long chapterId) {}
    @GetMapping("/courses")
    public Result<Map<String,Object>> courses(@RequestAttribute(AuthService.REQUEST_USER_ID) Long user,@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="20") int size) { return Result.ok(service.courses(user,page,size)); }
    @PostMapping("/courses")
    public Result<Map<String,Object>> create(@RequestAttribute(AuthService.REQUEST_USER_ID) Long user,@RequestBody CourseInput input) { return Result.ok(service.create(user,input.name(),input.semester(),input.description())); }
    @GetMapping("/courses/{id}")
    public Result<Map<String,Object>> detail(@RequestAttribute(AuthService.REQUEST_USER_ID) Long user,@PathVariable long id) { return Result.ok(service.detail(user,id)); }
    @PostMapping("/courses/{id}/chapters")
    public Result<Map<String,Object>> chapter(@RequestAttribute(AuthService.REQUEST_USER_ID) Long user,@PathVariable long id,@RequestBody ChapterInput input) { return Result.ok(service.createChapter(user,id,input.name())); }
    @GetMapping("/courses/{id}/resources")
    public Result<List<Map<String,Object>>> resources(@RequestAttribute(AuthService.REQUEST_USER_ID) Long user,@PathVariable long id,@RequestParam(required=false) Long chapterId,@RequestParam(defaultValue="false") boolean unassigned) { return Result.ok(service.resources(user,id,chapterId,unassigned)); }
    @GetMapping("/available-videos")
    public Result<List<Map<String,Object>>> videos(@RequestAttribute(AuthService.REQUEST_USER_ID) Long user) { return Result.ok(service.availableVideos(user)); }
    @PostMapping("/courses/{id}/videos")
    public Result<Map<String,Object>> video(@RequestAttribute(AuthService.REQUEST_USER_ID) Long user,@PathVariable long id,@RequestBody VideoInput input) {
        if(input.mediaId()==null) throw new IllegalArgumentException("请选择视频");
        return Result.ok(service.addVideo(user,id,input.chapterId(),input.mediaId()));
    }
    @PostMapping("/courses/{id}/documents")
    public Result<Map<String,Object>> document(@RequestAttribute(AuthService.REQUEST_USER_ID) Long user,@PathVariable long id,@RequestParam(required=false) Long chapterId,@RequestParam("file") MultipartFile file,@RequestHeader("Idempotency-Key") String key) throws Exception { return Result.ok(service.upload(user,id,chapterId,file,key)); }
    @GetMapping("/resources/{id}/file")
    public Result<Map<String,Object>> file(@RequestAttribute(AuthService.REQUEST_USER_ID) Long user,@PathVariable long id) { return Result.ok(service.file(user,id)); }
}
