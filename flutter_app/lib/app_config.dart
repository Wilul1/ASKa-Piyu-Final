import 'dart:convert';

import 'package:flutter/foundation.dart';

import 'services/extraction_preview_store.dart';
import 'services/local_store.dart';

class AppConfig {
  static const String apiBase =
      String.fromEnvironment('ASKA_API_BASE_URL', defaultValue: '');

  static const String _extractionKey = kExtractionPreviewStorageKey;

  static String get resolvedApiBase {
    final configured = apiBase.trim();
    if (configured.isEmpty) {
      if (kReleaseMode) {
        throw StateError(
          'ASKA_API_BASE_URL is required for release builds. '
          'Pass --dart-define=ASKA_API_BASE_URL=https://your-api.example',
        );
      }
      assert(() {
        // ignore: avoid_print
        print(
          'WARNING: ASKA_API_BASE_URL is empty. '
          'API calls use relative paths and will fail on mobile.',
        );
        return true;
      }());
      return '';
    }
    final normalized = configured.endsWith('/')
        ? configured.substring(0, configured.length - 1)
        : configured;
    if (kReleaseMode &&
        !normalized.toLowerCase().startsWith('https://')) {
      throw StateError(
        'ASKA_API_BASE_URL must use https:// in release builds '
        '(got "$normalized").',
      );
    }
    return normalized;
  }

  /// In-memory only — never persist the shared admin API key.
  static String? _sessionAdminKey;

  /// Cached extraction handoff loaded from SharedPreferences.
  static Map<String, dynamic>? _extractionCache;

  static Future<void> init() async {
    await LocalStore.init();
    // Drop legacy persisted admin key if present from older builds.
    await LocalStore.remove('aska_admin_key');
    _loadExtractionCache();
  }

  static String? get savedAdminKey {
    final value = _sessionAdminKey?.trim();
    return value == null || value.isEmpty ? null : value;
  }

  static set savedAdminKey(String? value) {
    final cleaned = value?.trim() ?? '';
    _sessionAdminKey = cleaned.isEmpty ? null : cleaned;
  }

  /// Latest Documents → Generate Articles extraction handoff package.
  static Map<String, dynamic>? get lastExtractionPreview => _extractionCache;

  static void _loadExtractionCache() {
    final raw = LocalStore.getString(_extractionKey);
    if (raw == null) {
      _extractionCache = null;
      return;
    }
    try {
      final decoded = jsonDecode(raw);
      _extractionCache = decodeExtractionHandoff(decoded);
    } catch (_) {
      _extractionCache = null;
    }
  }

  /// Persist a compact extraction handoff. Empty/invalid payloads never
  /// overwrite a valid cached extraction. Returns whether storage succeeded.
  static Future<bool> saveLastExtractionPreview(
    Map<String, dynamic>? value,
  ) async {
    if (value == null) {
      _extractionCache = null;
      await LocalStore.remove(_extractionKey);
      return true;
    }

    final existing = lastExtractionPreview;
    if (!shouldReplaceExtractionHandoff(existing: existing, incoming: value)) {
      return isValidExtractionHandoff(existing);
    }

    final encoded = jsonEncode(value);
    try {
      await LocalStore.setString(_extractionKey, encoded);
      _loadExtractionCache();
      return lastExtractionPreview != null;
    } catch (_) {
      try {
        final compact = _aggressivelyCompactHandoff(value);
        if (!isValidExtractionHandoff(compact)) {
          return false;
        }
        await LocalStore.setString(_extractionKey, jsonEncode(compact));
        _loadExtractionCache();
        return lastExtractionPreview != null;
      } catch (_) {
        return false;
      }
    }
  }

  /// Back-compat setter used by older call sites.
  static set lastExtractionPreview(Map<String, dynamic>? value) {
    // Fire-and-forget; callers that need confirmation should await
    // [saveLastExtractionPreview].
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
