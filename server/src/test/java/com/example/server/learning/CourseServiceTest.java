package com.example.server.learning;

import com.example.server.entity.MediaFile;
import com.example.server.exception.BusinessException;
import com.example.server.service.MediaService;
import com.example.server.utils.MinioUtils;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;
import org.springframework.transaction.support.TransactionTemplate;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class CourseServiceTest {
    final CourseRepository db=mock(CourseRepository.class);
    final MediaService media=mock(MediaService.class);
    final MinioUtils storage=mock(MinioUtils.class);
    final PlatformTransactionManager manager=mock(PlatformTransactionManager.class);
    final CourseService service;
    CourseServiceTest() {
        when(manager.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        service=new CourseService(db,media,storage,new TransactionTemplate(manager));
    }
    void ownedCourse() {
        when(db.rows("SELECT * FROM courses WHERE id=? AND user_id=?",10L,1L))
            .thenReturn(List.of(Map.of("id",10L,"name","Course","semester","","description","")));
    }
    @Test void deniesForeignCourseBeforeStorageOrMediaAccess() {
        assertThrows(NoSuchElementException.class,()->service.resources(2,10,null,false));
        verifyNoInteractions(storage,media);
    }
    @Test void rejectsChapterFromAnotherCourse() {
        ownedCourse();
        assertThrows(IllegalArgumentException.class,()->service.addVideo(1,10,99L,3));
        verifyNoInteractions(media);
    }
    @Test void identicalUploadReceiptReturnsOriginalWithoutWritingObject() throws Exception {
        ownedCourse();
        var file=new MockMultipartFile("file","a.pdf",null,"%PDF-1.4\n".getBytes());
        String hash=CourseService.fingerprint(10,null,"a.pdf",file);
        when(db.rows("SELECT id,filename,parse_status,request_fingerprint FROM learning_resources WHERE user_id=? AND upload_key=?",1L,"receipt-1"))
            .thenReturn(List.of(Map.of("id",22L,"filename","a.pdf","parse_status","UPLOADED","request_fingerprint",hash)));
        assertEquals("22",service.upload(1,10,null,file,"receipt-1").get("id"));
        verifyNoInteractions(storage);
    }
    @Test void receiptCannotBeReusedWithDifferentBytes() throws Exception {
        ownedCourse();
        var file=new MockMultipartFile("file","a.pdf",null,"%PDF-1.4\n".getBytes());
        when(db.rows("SELECT id,filename,parse_status,request_fingerprint FROM learning_resources WHERE user_id=? AND upload_key=?",1L,"receipt-1"))
            .thenReturn(List.of(Map.of("id",22L,"filename","a.pdf","parse_status","UPLOADED","request_fingerprint","different")));
        assertThrows(BusinessException.class,()->service.upload(1,10,null,file,"receipt-1"));
        verifyNoInteractions(storage);
    }
    @Test void failedDatabaseWriteRollsBackAndCleansNewObject() throws Exception {
        ownedCourse();
        when(db.rows("SELECT id FROM users WHERE id=? FOR UPDATE",1L)).thenReturn(List.of(Map.of("id",1L)));
        when(db.insert(startsWith("INSERT INTO learning_resources"),any(Object[].class))).thenThrow(new IllegalStateException("database unavailable"));
        var file=new MockMultipartFile("file","a.pdf",null,"%PDF-1.4\n".getBytes());
        assertThrows(IllegalStateException.class,()->service.upload(1,10,null,file,"receipt-1"));
        verify(manager).rollback(any());
        verify(storage).removeObject(startsWith("learning/1/"));
    }
    @Test void videoCannotBeJoinedToTwoCourses() {
        ownedCourse();
        when(db.rows("SELECT id FROM media_files WHERE id=? AND user_id=? FOR UPDATE",3L,1L)).thenReturn(List.of(Map.of("id",3L)));
        var video=new MediaFile(); video.setFilename("lesson.mp4");
        when(media.requireOwnedMedia(3L,1L)).thenReturn(video);
        when(db.rows("SELECT id FROM learning_resources WHERE media_id=?",3L)).thenReturn(List.of(Map.of("id",22L)));
        when(db.rows("SELECT course_id,chapter_id FROM course_resources WHERE resource_id=?",22L)).thenReturn(List.of(Map.of("course_id",20L)));
        assertThrows(BusinessException.class,()->service.addVideo(1,10,null,3));
        verify(manager).rollback(any());
    }
    @Test void identicalVideoJoinIsIdempotent() {
        ownedCourse();
        when(db.rows("SELECT id FROM media_files WHERE id=? AND user_id=? FOR UPDATE",3L,1L)).thenReturn(List.of(Map.of("id",3L)));
        var video=new MediaFile();video.setFilename("lesson.mp4");when(media.requireOwnedMedia(3L,1L)).thenReturn(video);
        when(db.rows("SELECT id FROM learning_resources WHERE media_id=?",3L)).thenReturn(List.of(Map.of("id",22L)));
        when(db.rows("SELECT course_id,chapter_id FROM course_resources WHERE resource_id=?",22L)).thenReturn(List.of(Map.of("course_id",10L)));
        assertEquals("22",service.addVideo(1,10,null,3).get("id"));
        verify(db,never()).insert(anyString(),any(Object[].class));
        verify(db,never()).update(anyString(),any(Object[].class));
    }
    @Test void fileReadDoesNotExposeAnotherUsersObject() {
        assertThrows(NoSuchElementException.class,()->service.file(2,22));
        verifyNoInteractions(storage,media);
    }
}
