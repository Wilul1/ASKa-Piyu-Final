import 'package:dart_quill_delta/dart_quill_delta.dart';
import 'package:flutter_quill/flutter_quill.dart';
import 'package:flutter_quill_delta_from_html/flutter_quill_delta_from_html.dart';

class ArticleEditorValue {
  const ArticleEditorValue({
    required this.content,
    required this.contentFormat,
  });

  final String content;
  final String contentFormat;

  bool get isHtml => contentFormat == 'html';
  bool get isEmpty => articleHtmlToPlain(content).trim().isEmpty;
}

final _tagRe = RegExp(r'<[^>]+>');
final _htmlStartRe = RegExp(
  r'<(p|h[1-4]|ul|ol|blockquote|div|span|strong|em|img)\b',
  caseSensitive: false,
);

bool looksLikeArticleHtml(String? text) {
  final raw = (text ?? '').trimLeft();
  if (!raw.startsWith('<')) return false;
  return _htmlStartRe.hasMatch(raw);
}

String articleHtmlToPlain(String? text) {
  var raw = (text ?? '');
  if (raw.trim().isEmpty) return '';
  raw = raw.replaceAll(RegExp(r'<br\s*/?>', caseSensitive: false), '\n');
  raw = raw.replaceAll(
    RegExp(r'</(p|h[1-4]|li|blockquote|div)>', caseSensitive: false),
    '\n',
  );
  raw = raw.replaceAll(_tagRe, '');
  raw = _unescapeHtml(raw);
  return raw
      .split('\n')
      .map((line) => line.trim())
      .where((line) => line.isNotEmpty)
      .join('\n')
      .trim();
}

String _unescapeHtml(String value) {
  return value
      .replaceAll('&nbsp;', ' ')
      .replaceAll('&amp;', '&')
      .replaceAll('&lt;', '<')
      .replaceAll('&gt;', '>')
      .replaceAll('&quot;', '"')
      .replaceAll('&#39;', "'");
}

String escapeArticleHtml(String value) {
  return value
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;');
}

String? safeArticleHref(String? raw) {
  final href = (raw ?? '').trim();
  if (href.isEmpty || href.startsWith('#')) return null;
  if (href.contains(RegExp(r'\s')) || href.contains('\\')) return null;
  final lowered = href.toLowerCase();
  if (lowered.startsWith('javascript:') ||
      lowered.startsWith('data:') ||
      lowered.startsWith('vbscript:') ||
      href.startsWith('//')) {
    return null;
  }
  final schemeMatch = RegExp(r'^([a-zA-Z][a-zA-Z0-9+.-]*):').firstMatch(href);
  if (schemeMatch != null) {
    final scheme = schemeMatch.group(1)!.toLowerCase();
    if (scheme != 'http' && scheme != 'https' && scheme != 'mailto') {
      return null;
    }
    return href;
  }
  if (href.startsWith('/') && !href.startsWith('//')) return href;
  return null;
}

String? safeArticleImageSrc(String? raw) {
  final src = (raw ?? '').trim();
  if (src.isEmpty) return null;
  if (src.startsWith('data:') || src.toLowerCase().startsWith('javascript:')) {
    return null;
  }
  final path = Uri.tryParse(src)?.path ?? src;
  if (RegExp(r'^/kb/media/[A-Za-z0-9._-]+$').hasMatch(path)) {
    return path;
  }
  if (RegExp(r'^/kb/media/[A-Za-z0-9._-]+$').hasMatch(src)) {
    return src;
  }
  return null;
}

Document documentFromArticleContent({
  required String content,
  required String contentFormat,
}) {
  final raw = content.trim();
  if (raw.isEmpty) {
    return Document();
  }
  final asHtml = contentFormat == 'html' || looksLikeArticleHtml(raw);
  if (!asHtml) {
    return _plainDocument(content.replaceAll('\r\n', '\n'));
  }
  try {
    final delta = HtmlToDelta().convert(raw);
    if (delta.isEmpty) {
      return Document();
    }
    final last = delta.last;
    final lastData = last.data;
    if (lastData is! String || !lastData.endsWith('\n')) {
      delta.insert('\n');
    }
    return Document.fromDelta(delta);
  } catch (_) {
    final fallback = articleHtmlToPlain(raw);
    if (fallback.isEmpty) return Document();
    return _plainDocument(fallback);
  }
}

Document _plainDocument(String text) {
  final insert = text.endsWith('\n') ? text : '$text\n';
  return Document.fromJson([
    {'insert': insert},
  ]);
}

bool documentHasRichFormatting(Document document) {
  for (final op in document.toDelta().toList()) {
    final data = op.data;
    if (data is Map) return true;
    final attrs = op.attributes;
    if (attrs == null || attrs.isEmpty) continue;
    for (final key in attrs.keys) {
      if (key == 'align' || key == 'direction') continue;
      return true;
    }
  }
  return false;
}

ArticleEditorValue editorValueFromDocument(
  Document document, {
  required String existingFormat,
}) {
  final rich = documentHasRichFormatting(document);
  final stayHtml = existingFormat == 'html' || rich;
  if (!stayHtml) {
    final plain = document.toPlainText().replaceAll(RegExp(r'\n+$'), '').trim();
    return ArticleEditorValue(content: plain, contentFormat: 'plain');
  }
  return ArticleEditorValue(
    content: deltaToArticleHtml(document.toDelta()),
    contentFormat: 'html',
  );
}

String deltaToArticleHtml(Delta delta) {
  final lines = <_HtmlLine>[];
  var inline = StringBuffer();

  void flushInlineInto(Map<String, dynamic>? blockAttrs, {String? imageSrc}) {
    lines.add(
      _HtmlLine(
        html: inline.toString(),
        header: blockAttrs?['header'] is num
            ? (blockAttrs!['header'] as num).toInt()
            : int.tryParse(blockAttrs?['header']?.toString() ?? ''),
        list: blockAttrs?['list']?.toString(),
        quote: blockAttrs?['blockquote'] == true,
        imageSrc: imageSrc,
      ),
    );
    inline = StringBuffer();
  }

  for (final op in delta.toList()) {
    final data = op.data;
    final attrs = Map<String, dynamic>.from(op.attributes ?? const {});
    if (data is Map) {
      final image = data['image']?.toString();
      final src = safeArticleImageSrc(image);
      if (src != null) {
        inline.write(
          '<img src="${escapeArticleHtml(src)}" alt="">',
        );
      }
      continue;
    }
    if (data is! String) continue;
    final parts = data.split('\n');
    for (var i = 0; i < parts.length; i++) {
      final chunk = parts[i];
      if (chunk.isNotEmpty) {
        inline.write(_wrapInline(chunk, attrs));
      }
      if (i < parts.length - 1) {
        flushInlineInto(attrs);
      }
    }
  }
  if (inline.isNotEmpty) {
    flushInlineInto(const {});
  }

  final out = StringBuffer();
  String? openList;
  void closeList() {
    if (openList == 'bullet') out.write('</ul>');
    if (openList == 'ordered') out.write('</ol>');
    openList = null;
  }

  for (final line in lines) {
    if (line.imageSrc != null && line.html.contains('<img ')) {
      closeList();
      out.write('<p>${line.html}</p>');
      continue;
    }
    if (line.list != null) {
      if (openList != line.list) {
        closeList();
        out.write(line.list == 'ordered' ? '<ol>' : '<ul>');
        openList = line.list;
      }
      out.write('<li>${line.html}</li>');
      continue;
    }
    closeList();
    if (line.header != null && line.header! >= 1 && line.header! <= 4) {
      out.write('<h${line.header}>${line.html}</h${line.header}>');
    } else if (line.quote) {
      out.write('<blockquote>${line.html}</blockquote>');
    } else if (line.html.trim().isEmpty) {
      continue;
    } else {
      out.write('<p>${line.html}</p>');
    }
  }
  closeList();
  return out.toString();
}

class _HtmlLine {
  const _HtmlLine({
    required this.html,
    this.header,
    this.list,
    this.quote = false,
    this.imageSrc,
  });

  final String html;
  final int? header;
  final String? list;
  final bool quote;
  final String? imageSrc;
}

String _wrapInline(String text, Map<String, dynamic> attrs) {
  var wrapped = escapeArticleHtml(text);
  if (attrs['bold'] == true) wrapped = '<strong>$wrapped</strong>';
  if (attrs['italic'] == true) wrapped = '<em>$wrapped</em>';
  if (attrs['underline'] == true) wrapped = '<u>$wrapped</u>';
  final href = safeArticleHref(attrs['link']?.toString());
  if (href != null) {
    wrapped =
        '<a href="${escapeArticleHtml(href)}" rel="noopener noreferrer" target="_blank">$wrapped</a>';
  }
  return wrapped;
}
