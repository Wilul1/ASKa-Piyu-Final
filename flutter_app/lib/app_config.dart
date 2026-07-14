import 'dart:convert';
import 'dart:html' as html;

import 'services/extraction_preview_store.dart';

class AppConfig {
  static const String apiBase =
      String.fromEnvironment('ASKA_API_BASE_URL', defaultValue: '');

  static String get resolvedApiBase {
    final configured = apiBase.trim();
    if (configured.endsWith('/')) {
      return configured.substring(0, configured.length - 1);
    }
    return configured;
  }

  static Map<String, String> studentHeaders() {
    return {
      'x-user-id': 'student-001',
      'x-user-role': 'student',
      'x-user-name': 'Student',
      'x-user-email': 'student@test.local',
    };
  }

  static String? get savedAdminKey {
    final value = html.window.localStorage['aska_admin_key']?.trim();
    return value == null || value.isEmpty ? null : value;
  }

  static set savedAdminKey(String? value) {
    final cleaned = value?.trim() ?? '';
    if (cleaned.isEmpty) {
      html.window.localStorage.remove('aska_admin_key');
      return;
    }
    html.window.localStorage['aska_admin_key'] = cleaned;
  }

  /// Latest Documents → Generate Articles extraction handoff package.
  ///
  /// Shape: `{ preview: {...}, source_filename, document_profile, ... }`.
  static Map<String, dynamic>? get lastExtractionPreview {
    final raw = html.window.localStorage[kExtractionPreviewStorageKey];
    if (raw == null || raw.trim().isEmpty) return null;
    try {
      final decoded = jsonDecode(raw);
      return decodeExtractionHandoff(decoded);
    } catch (_) {
      // Ignore malformed cache.
    }
    return null;
  }

  /// Persist a compact extraction handoff. Empty/invalid payloads never
  /// overwrite a valid cached extraction. Returns whether storage succeeded.
  static bool saveLastExtractionPreview(Map<String, dynamic>? value) {
    if (value == null) {
      html.window.localStorage.remove(kExtractionPreviewStorageKey);
      return true;
    }

    final existing = lastExtractionPreview;
    if (!shouldReplaceExtractionHandoff(existing: existing, incoming: value)) {
      // Keep the previous valid extraction when the new package is empty/invalid.
      return isValidExtractionHandoff(existing);
    }

    final encoded = jsonEncode(value);
    try {
      html.window.localStorage[kExtractionPreviewStorageKey] = encoded;
      return lastExtractionPreview != null;
    } catch (_) {
      // QuotaExceeded or serialization failure — try a more aggressive compact.
      try {
        final compact = _aggressivelyCompactHandoff(value);
        if (!isValidExtractionHandoff(compact)) {
          return false;
        }
        html.window.localStorage[kExtractionPreviewStorageKey] =
            jsonEncode(compact);
        return lastExtractionPreview != null;
      } catch (_) {
        return false;
      }
    }
  }

  /// Back-compat setter used by older call sites. Prefer [saveLastExtractionPreview].
  static set lastExtractionPreview(Map<String, dynamic>? value) {
    saveLastExtractionPreview(value);
  }

  static Map<String, dynamic> _aggressivelyCompactHandoff(
    Map<String, dynamic> value,
  ) {
    final copy = Map<String, dynamic>.from(value);
    final preview = decodeExtractionHandoff({'preview': copy['preview']});
    final previewMap = preview == null
        ? <String, dynamic>{}
        : Map<String, dynamic>.from(preview['preview'] as Map? ?? {});
    // Drop the largest text fields if quota is still too tight.
    previewMap.remove('cleaned_text');
    previewMap['review_text'] = _hardClip(previewMap['review_text'], 40000);
    previewMap['extracted_text'] = previewMap['review_text'];
    final units = previewMap['knowledge_units'];
    if (units is List) {
      previewMap['knowledge_units'] = units.take(200).map((unit) {
        if (unit is! Map) return unit;
        final map = Map<String, dynamic>.from(
          unit.map((key, item) => MapEntry(key.toString(), item)),
        );
        map['content'] = _hardClip(map['content'], 2000);
        return map;
      }).toList();
    }
    final v2 = previewMap['charter_v2_services'];
    if (v2 is List) {
      previewMap['charter_v2_services'] = v2.take(80).map((service) {
        if (service is! Map) return service;
        final map = Map<String, dynamic>.from(
          service.map((key, item) => MapEntry(key.toString(), item)),
        );
        final debug = map['parser_debug'];
        if (debug is Map) {
          map['parser_debug'] = {
            'extraction_quality': debug['extraction_quality'],
            'extraction_quality_reason': debug['extraction_quality_reason'],
            'parser_strategy_used': debug['parser_strategy_used'],
            'table_extraction_method': debug['table_extraction_method'],
            'page_start': debug['page_start'],
            'page_end': debug['page_end'],
            'detected_service_title': debug['detected_service_title'],
            'detected_office': debug['detected_office'],
            'detected_step_rows': debug['detected_step_rows'],
          };
        }
        return map;
      }).toList();
    }
    final diagnostics = previewMap['charter_v2_diagnostics'];
    if (diagnostics is Map) {
      final diag = Map<String, dynamic>.from(
        diagnostics.map((key, item) => MapEntry(key.toString(), item)),
      );
      diag.remove('page_geometry_debug');
      previewMap['charter_v2_diagnostics'] = diag;
    }
    copy['preview'] = previewMap;
    return copy;
  }

  static String? _hardClip(Object? value, int maxChars) {
    if (value == null) return null;
    final text = value.toString();
    if (text.length <= maxChars) return text;
    return '${text.substring(0, maxChars)}…';
  }
}
