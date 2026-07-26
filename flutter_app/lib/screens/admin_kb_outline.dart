/// Helpers for grouping extracted knowledge units into document outline sections.

class DocumentOutlineSection {
  const DocumentOutlineSection({
    required this.title,
    required this.units,
  });

  final String title;
  final List<Map<String, dynamic>> units;

  int get unitCount => units.length;

  String get previewText {
    final buffer = StringBuffer();
    for (final unit in units.take(3)) {
      final content = (unit['content'] ?? unit['text'] ?? '').toString().trim();
      if (content.isEmpty) continue;
      if (buffer.isNotEmpty) buffer.writeln();
      buffer.write(content);
      if (buffer.length > 1200) break;
    }
    return buffer.toString().trim();
  }

  String? get pageLabel {
    int? start;
    int? end;
    for (final unit in units) {
      final pageStart = _asInt(unit['page_start'] ?? unit['page']);
      final pageEnd = _asInt(unit['page_end'] ?? pageStart);
      if (pageStart != null) {
        start = start == null ? pageStart : (pageStart < start ? pageStart : start);
      }
      if (pageEnd != null) {
        end = end == null ? pageEnd : (pageEnd > end ? pageEnd : end);
      }
    }
    if (start == null) return null;
    if (end == null || end == start) return 'Page $start';
    return 'Pages $start–$end';
  }
}

List<DocumentOutlineSection> buildDocumentOutline(
  List<Map<String, dynamic>> units,
) {
  if (units.isEmpty) return const [];
  final groups = <String, List<Map<String, dynamic>>>{};
  for (final unit in units) {
    final key = _outlineKey(unit);
    groups.putIfAbsent(key, () => []).add(unit);
  }
  return groups.entries
      .map((e) => DocumentOutlineSection(title: e.key, units: e.value))
      .toList();
}

/// Normalize API document-type payloads (string or detection map) for UI chips.
String? formatDocumentTypeLabel(Object? value) {
  if (value == null) return null;
  if (value is Map) {
    final type = value['document_type']?.toString().trim();
    if (type == null || type.isEmpty) return null;
    return _titleCaseWords(type);
  }
  final text = value.toString().trim();
  if (text.isEmpty) return null;
  if (text.startsWith('{') && text.contains('document_type')) {
    final match = RegExp(r'document_type:\s*([^,}\s]+)').firstMatch(text);
    if (match != null) return _titleCaseWords(match.group(1)!);
  }
  return _titleCaseWords(text);
}

String? formatClassificationReason(Object? value) {
  if (value == null) return null;
  if (value is Map) {
    final reason = value['reason']?.toString().trim();
    return (reason == null || reason.isEmpty) ? null : reason;
  }
  final text = value.toString().trim();
  if (text.isEmpty || text.startsWith('{')) return null;
  return text;
}

String buildFullExtractionText({
  required String reviewText,
  required List<Map<String, dynamic>> knowledgeUnits,
}) {
  final cleaned = reviewText.trim();
  if (cleaned.isNotEmpty) return cleaned;
  return buildKnowledgeUnitsExtractionTxt(knowledgeUnits: knowledgeUnits);
}

/// One downloadable .txt with every knowledge unit (not one file per unit).
String buildKnowledgeUnitsExtractionTxt({
  required List<Map<String, dynamic>> knowledgeUnits,
  String? sourceFilename,
}) {
  if (knowledgeUnits.isEmpty) return '';
  final buffer = StringBuffer();
  final source = (sourceFilename ?? '').trim();
  buffer.writeln('ASKa-Piyu extraction units');
  if (source.isNotEmpty) buffer.writeln('Source: $source');
  buffer.writeln('Total units: ${knowledgeUnits.length}');
  buffer.writeln('=' * 64);

  for (var i = 0; i < knowledgeUnits.length; i++) {
    final unit = knowledgeUnits[i];
    final index = unit['unit_index'] ?? i;
    final title = (unit['title'] ?? 'Untitled').toString().trim();
    final path = (unit['hierarchy_path'] ?? unit['source_section'] ?? '')
        .toString()
        .trim();
    final contentType = (unit['content_type'] ?? '').toString().trim();
    final status = (unit['status'] ?? '').toString().trim();
    final pageStart = unit['page_start'] ?? unit['page'];
    final pageEnd = unit['page_end'];
    final content = (unit['content'] ?? unit['text'] ?? '').toString().trim();
    final metadata = unit['metadata'];
    final meta = metadata is Map ? Map<String, dynamic>.from(metadata) : const {};

    buffer.writeln();
    buffer.writeln('UNIT ${i + 1} / ${knowledgeUnits.length}');
    buffer.writeln('-' * 64);
    buffer.writeln('unit_index: $index');
    buffer.writeln(title.isEmpty ? 'title: Untitled' : 'title: $title');
    if (path.isNotEmpty) buffer.writeln('hierarchy_path: $path');
    if (contentType.isNotEmpty) buffer.writeln('content_type: $contentType');
    if (status.isNotEmpty) buffer.writeln('status: $status');
    if (pageStart != null) {
      if (pageEnd != null && pageEnd != pageStart) {
        buffer.writeln('pages: $pageStart-$pageEnd');
      } else {
        buffer.writeln('page: $pageStart');
      }
    }
    for (final key in const [
      'office',
      'responsible_office',
      'total_fees',
      'fees',
      'total_processing_time',
      'who_may_avail',
      'classification',
      'parser_document_type',
      'document_type',
    ]) {
      final value = (unit[key] ?? meta[key] ?? '').toString().trim();
      if (value.isNotEmpty) buffer.writeln('$key: $value');
    }
    final reasons = unit['suspicious_reasons'];
    if (reasons is List && reasons.isNotEmpty) {
      buffer.writeln('suspicious_reasons: ${reasons.join('; ')}');
    }
    buffer.writeln();
    buffer.writeln(content.isEmpty ? '(empty content)' : content);
    buffer.writeln();
    buffer.writeln('=' * 64);
  }

  return buffer.toString().trimRight();
}

String _outlineKey(Map<String, dynamic> unit) {
  final hierarchy = (unit['hierarchy_path'] ?? '').toString().trim();
  if (hierarchy.isNotEmpty) {
    final parts = hierarchy
        .split(RegExp(r'[>|/]'))
        .map((part) => part.trim())
        .where((part) => part.isNotEmpty)
        .toList();
    if (parts.isNotEmpty) return _cleanOutlineLabel(parts.first);
  }
  for (final key in ['chapter', 'category', 'section', 'article']) {
    final value = (unit[key] ?? '').toString().trim();
    if (value.isNotEmpty) return _cleanOutlineLabel(value);
  }
  final title = (unit['title'] ?? '').toString().trim();
  if (title.isNotEmpty) return _cleanOutlineLabel(title);
  return 'General';
}

String _cleanOutlineLabel(String value) {
  final cleaned = value
      .replaceFirst(
        RegExp(
          r'^(chapter|article|section|sec\.?)\s+[ivxlcdm0-9]+\s*[-:.)]?\s*',
          caseSensitive: false,
        ),
        '',
      )
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
  return cleaned.isEmpty ? value.trim() : cleaned;
}

String _titleCaseWords(String value) {
  return value
      .split(RegExp(r'[_\s]+'))
      .where((part) => part.isNotEmpty)
      .map((part) {
        final lower = part.toLowerCase();
        return '${lower[0].toUpperCase()}${lower.substring(1)}';
      })
      .join(' ');
}

int? _asInt(Object? value) {
  if (value is int) return value;
  return int.tryParse((value ?? '').toString());
}
