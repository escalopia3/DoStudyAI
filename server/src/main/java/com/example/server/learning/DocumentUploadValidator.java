package com.example.server.learning;

import org.springframework.web.multipart.MultipartFile;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.zip.ZipInputStream;

/** Validate modern Office containers without executing or parsing document content. */
public final class DocumentUploadValidator {
    public static final long MAX_BYTES = 50L * 1024 * 1024;
    private DocumentUploadValidator() {}

    public static String validate(MultipartFile file) throws Exception {
        if (file == null || file.isEmpty()) throw new IllegalArgumentException("请选择非空文件");
        if (file.getSize() > MAX_BYTES) throw new IllegalArgumentException("文档不能超过 50 MiB");
        String name = filename(file.getOriginalFilename());
        String suffix = name.substring(name.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
        if (!java.util.Set.of("pdf", "docx", "pptx").contains(suffix))
            throw new IllegalArgumentException("当前支持 PDF、DOCX、PPTX；旧版 DOC/PPT 请先转换格式");
        try (InputStream input = file.getInputStream()) {
            if (suffix.equals("pdf")) {
                String header = new String(input.readNBytes(1024), StandardCharsets.ISO_8859_1);
                if (!header.contains("%PDF-")) throw new IllegalArgumentException("文件内容不是有效 PDF");
            } else {
                String expected = suffix.equals("docx") ? "word/document.xml" : "ppt/presentation.xml";
                boolean document = false, types = false;
                long expanded = 0;
                int entries = 0;
                try (var zip = new ZipInputStream(input)) {
                    var buffer = new byte[8192];
                    for (var entry = zip.getNextEntry(); entry != null; entry = zip.getNextEntry()) {
                        if (++entries > 10000) throw new IllegalArgumentException("文档内部文件过多");
                        if (entry.getName().equals(expected)) document = true;
                        if (entry.getName().equals("[Content_Types].xml")) types = true;
                        if (entry.getName().toLowerCase(Locale.ROOT).endsWith("vbaproject.bin"))
                            throw new IllegalArgumentException("不支持包含宏的文档");
                        int count;
                        while ((count = zip.read(buffer)) != -1) {
                            expanded += count;
                            if (expanded > 200L * 1024 * 1024)
                                throw new IllegalArgumentException("文档解压内容超过限制");
                        }
                    }
                } catch (java.io.IOException error) {
                    throw new IllegalArgumentException("Office 文件损坏或格式不正确", error);
                }
                if (!document || !types) throw new IllegalArgumentException("文件内容与 Office 扩展名不符");
            }
        }
        return suffix.toUpperCase(Locale.ROOT);
    }

    public static String filename(String original) {
        String name = original == null ? "" : original.replace('\\', '/');
        name = name.substring(name.lastIndexOf('/') + 1).trim();
        if (name.isEmpty() || name.length() > 255 || name.chars().anyMatch(Character::isISOControl))
            throw new IllegalArgumentException("文件名为空、过长或包含无效字符");
        return name;
    }
}
