/// Compact extraction-preview handoff between Documents and Generate Articles.
///
/// Pure Dart (no `dart:html`) so unit tests can cover save/load rules without
/// a browser. Persistence itself lives in [AppConfig] / localStorage.

const String kExtractionPreviewStorageKey = 'aska_last_extraction_preview';

const int _maxReviewTextChars = 120000;
const int _maxParserDebugChars = 400;
const int _maxUnitContentChars = 8000;

/// True when a stored handoff package has enough data for Generate Articles.
bool isValidExtractionHandoff(Map<String, dynamic>? package) {
  if (package == null || package.isEmpty) return false;
  final preview = _asStringKeyMap(package['preview']);
  if (preview == null) return false;
  final units = preview['knowledge_units'];
  final hasUnits = units is List && units.isNotEmpty;
  final v2 = preview['charter_v2_services'];
  final hasV2 = v2 is List && v2.isNotEmpty;
  final review = (preview['review_text'] ??
          preview['extracted_text'] ??
          preview['cleaned_text'] ??
          '')
      .toString()
      .trim();
  final filename = (package['source_filename'] ?? '').toString().trim();
  if (!hasUnits && !hasV2 && review.isEmpty) return false;
  // Filename is preferred but not strictly required if preview content exists.
  return hasUnits || hasV2 || (review.isNotEmpty && filename.isNotEmpty);
}

/// Whether [incoming] should replace [existing] in storage.
///
/// Empty/invalid packages never overwrite a valid cached extraction.
bool shouldReplaceExtractionHandoff({
  required Map<String, dynamic>? existing,
  required Map<String, dynamic>? incoming,
}) {
  if (!isValidExtractionHandoff(incoming)) return false;
  if (!isValidExtractionHandoff(existing)) return true;
  return true; // Valid new extract replaces previous valid extract.
}

/// Build the compact localStorage package from an extract API response.
Map<String, dynamic> buildExtractionHandoffPackage({
  required Map<String, dynamic> extractResponse,
  String? sourceFilename,
  String? status,
  String? classificationReason,
}) {
  final preview = buildCompactExtractionPreview(extractResponse);
  final units = preview['knowledge_units'];
  final unitCount = units is List ? units.length : 0;
  final v2 = preview['charter_v2_services'];
  final v2Count = v2 is List ? v2.length : 0;
  return {
    'preview': preview,
    'source_filename': (sourceFilename ??
            extractResponse['source_filename']?.toString() ??
            '')
        .toString(),
    'detected_document_type': extractResponse['detected_document_type'],
    'document_type': extractResponse['document_type'],
    'document_profile': extractResponse['document_profile'],
    'admin_selected_document_type':
        extractResponse['admin_selected_document_type'],
    'parser_document_type': extractResponse['parser_document_type'],
    'source_type': extractResponse['source_type'],
    'classification_reason': classificationReason,
    'knowledge_units_count': unitCount,
    'has_charter_v2_services': v2Count > 0,
    'charter_v2_services_count':
        extractResponse['charter_v2_detected_count'] ?? v2Count,
    'status': status ?? 'Extraction preview is ready.',
  };
}

/// Compact preview payload for Generate Articles (no raw word geometry).
Map<String, dynamic> buildCompactExtractionPreview(Map<String, dynamic> data) {
  final unitsRaw = data['knowledge_units'];
  final units = <Map<String, dynamic>>[];
  if (unitsRaw is List) {
    for (final item in unitsRaw) {
      final map = _asStringKeyMap(item);
      if (map == null) continue;
      units.add(_compactKnowledgeUnit(map));
    }
  }

  final v2Raw = data['charter_v2_services'];
  final v2Services = <Map<String, dynamic>>[];
  if (v2Raw is List) {
    for (final item in v2Raw) {
      final map = _asStringKeyMap(item);
      if (map == null) continue;
      v2Services.add(_compactCharterV2Service(map));
    }
  }

  final diagnostics = _asStringKeyMap(data['charter_v2_diagnostics']) ?? {};

  return {
    'knowledge_units': units,
    'document_type': data['document_type'],
    'document_profile': data['document_profile'],
    'detected_document_type': data['detected_document_type'],
    'admin_selected_document_type': data['admin_selected_document_type'],
    'parser_document_type': data['parser_document_type'],
    'source_type': data['source_type'],
    'review_text': _clipText(
      data['review_text'] ?? data['extracted_text'] ?? data['cleaned_text'],
      _maxReviewTextChars,
    ),
    // Keep aliases for backend collect_charter_parser_text fallbacks.
    'cleaned_text': _clipText(data['cleaned_text'], _maxReviewTextChars),
    'extracted_text': _clipText(
      data['extracted_text'] ?? data['review_text'],
      _maxReviewTextChars,
    ),
    // Drop bulky admin-only blobs from the Generate Articles handoff.
    // structured / chunk_preview / kb_statistics are not required to generate.
    'charter_v2_services': v2Services,
    'charter_v2_detected_count': data['charter_v2_detected_count'] ?? v2Services.length,
    'charter_v2_clean_count': data['charter_v2_clean_count'] ?? 0,
    'charter_v2_needs_review_count': data['charter_v2_needs_review_count'] ?? 0,
    'charter_v2_low_quality_count': data['charter_v2_low_quality_count'] ?? 0,
    'charter_v2_rag_only_count': data['charter_v2_rag_only_count'] ?? 0,
    'charter_v2_diagnostics': _compactDiagnostics(diagnostics),
  };
}

/// Decode a stored JSON object into a string-keyed map (handles web JSON typing).
Map<String, dynamic>? decodeExtractionHandoff(Object? decoded) {
  final map = _asStringKeyMap(decoded);
  if (map == null) return null;
  // Normalize nested preview map typing from jsonDecode.
  final preview = _asStringKeyMap(map['preview']);
  if (preview != null) {
    map['preview'] = preview;
  }
  return map;
}

/// Debug summary for UI chips / console.
Map<String, Object?> extractionHandoffDebugSummary(Map<String, dynamic>? package) {
  final preview = _asStringKeyMap(package?['preview']);
  final units = preview?['knowledge_units'];
  final v2 = preview?['charter_v2_services'];
  final unitCount = units is List ? units.length : 0;
  final v2Count = v2 is List ? v2.length : 0;
  return {
    'has_last_extraction_preview': isValidExtractionHandoff(package),
    'source_filename': (package?['source_filename'] ?? '').toString(),
    'knowledge_units_count':
        package?['knowledge_units_count'] ?? unitCount,
    'has_charter_v2_services': v2Count > 0,
    'charter_v2_services_count':
        package?['charter_v2_services_count'] ?? v2Count,
    'document_profile': (package?['document_profile'] ??
            preview?['document_profile'] ??
            '')
        .toString(),
  };
}

Map<String, dynamic> _compactKnowledgeUnit(Map<String, dynamic> unit) {
  final compact = Map<String, dynamic>.from(unit);
  if (compact['content'] != null) {
    compact['content'] = _clipText(compact['content'], _maxUnitContentChars);
  }
  final metadata = _asStringKeyMap(compact['metadata']);
  if (metadata != null) {
    compact['metadata'] = Map<String, dynamic>.from(metadata);
  }
  return compact;
}

Map<String, dynamic> _compactCharterV2Service(Map<String, dynamic> service) {
  final compact = Map<String, dynamic>.from(service);
  final debug = _asStringKeyMap(compact['parser_debug']);
  if (debug != null) {
    final clipped = Map<String, dynamic>.from(debug);
    for (final key in const [
      'raw_service_block',
      'cleaned_service_block',
    ]) {
      if (clipped[key] != null) {
        clipped[key] = _clipText(clipped[key], _maxParserDebugChars);
      }
    }
    // Drop oversized rejected_fragments lists.
    final rejected = clipped['rejected_fragments'];
    if (rejected is List && rejected.length > 30) {
      clipped['rejected_fragments'] = rejected.take(30).toList();
    }
    compact['parser_debug'] = clipped;
  }
  return compact;
}

Map<String, dynamic> _compactDiagnostics(Map<String, dynamic> diagnostics) {
  final compact = Map<String, dynamic>.from(diagnostics);
  // Keep page_geometry_debug but cap rows to avoid localStorage bloat.
  final pages = compact['page_geometry_debug'];
  if (pages is List) {
    compact['page_geometry_debug'] = pages.take(3).map((page) {
      final map = _asStringKeyMap(page);
      if (map == null) return page;
      final copy = Map<String, dynamic>.from(map);
      final rows = copy['first_20_rows'];
      if (rows is List && rows.length > 20) {
        copy['first_20_rows'] = rows.take(20).toList();
      }
      return copy;
    }).toList();
  }
  return compact;
}

String? _clipText(Object? value, int maxChars) {
  if (value == null) return null;
  final text = value.toString();
  if (text.length <= maxChars) return text;
  return '${text.substring(0, maxChars)}…';
}

Map<String, dynamic>? _asStringKeyMap(Object? value) {
  if (value is Map<String, dynamic>) {
    return Map<String, dynamic>.from(value);
  }
  if (value is Map) {
    return value.map((key, item) => MapEntry(key.toString(), item));
  }
  return null;
}
