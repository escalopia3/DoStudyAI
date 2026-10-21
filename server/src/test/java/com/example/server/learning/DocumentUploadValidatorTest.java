package com.example.server.learning;

import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockMultipartFile;
import java.io.ByteArrayOutputStream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import static org.junit.jupiter.api.Assertions.*;

class DocumentUploadValidatorTest {
    private MockMultipartFile office(String name, String... entries) throws Exception {
        var bytes = new ByteArrayOutputStream();
        try (var zip = new ZipOutputStream(bytes)) {
            for (String entry : entries) {
                zip.putNextEntry(new ZipEntry(entry)); zip.write("<test/>".getBytes()); zip.closeEntry();
            }
        }
        return new MockMultipartFile("file",name,"application/octet-stream",bytes.toByteArray());
    }
    @Test void acceptsOnlyMatchingModernOfficeContainers() throws Exception {
        assertEquals("DOCX",DocumentUploadValidator.validate(office("lesson.docx","[Content_Types].xml","word/document.xml")));
        assertEquals("PPTX",DocumentUploadValidator.validate(office("lesson.pptx","[Content_Types].xml","ppt/presentation.xml")));
        assertThrows(IllegalArgumentException.class,()->DocumentUploadValidator.validate(office("lesson.docx","[Content_Types].xml","ppt/presentation.xml")));
    }
    @Test void rejectsMacrosAndRenamedFiles() throws Exception {
        assertThrows(IllegalArgumentException.class,()->DocumentUploadValidator.validate(office("lesson.docx","[Content_Types].xml","word/document.xml","word/vbaProject.bin")));
        assertThrows(IllegalArgumentException.class,()->DocumentUploadValidator.validate(new MockMultipartFile("file","fake.pdf",null,"not a pdf".getBytes())));
        assertThrows(IllegalArgumentException.class,()->DocumentUploadValidator.validate(new MockMultipartFile("file","old.ppt",null,new byte[]{1})));
        assertThrows(IllegalArgumentException.class,()->DocumentUploadValidator.validate(new MockMultipartFile("file","empty.pdf",null,new byte[0])));
    }
    @Test void normalizesFilenameAndRejectsControls() {
        assertEquals("lecture.pdf",DocumentUploadValidator.filename("C:\\Users\\test\\lecture.pdf"));
        assertThrows(IllegalArgumentException.class,()->DocumentUploadValidator.filename("bad\nname.pdf"));
    }
    @Test void uploadFingerprintBindsBytesNameCourseAndChapter() throws Exception {
        var first = new MockMultipartFile("file","a.pdf",null,"%PDF-one".getBytes());
        var second = new MockMultipartFile("file","a.pdf",null,"%PDF-two".getBytes());
        String value = CourseService.fingerprint(1,null,"a.pdf",first);
        assertEquals(value,CourseService.fingerprint(1,null,"a.pdf",first));
        assertNotEquals(value,CourseService.fingerprint(2,null,"a.pdf",first));
        assertNotEquals(value,CourseService.fingerprint(1,3L,"a.pdf",first));
        assertNotEquals(value,CourseService.fingerprint(1,null,"b.pdf",first));
        assertNotEquals(value,CourseService.fingerprint(1,null,"a.pdf",second));
    }
}
