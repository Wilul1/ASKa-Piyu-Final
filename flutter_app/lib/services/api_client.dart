import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

/// Cross-platform HTTP helper replacing `dart:html` HttpRequest.
class ApiResult {
  ApiResult({
    required this.statusCode,
    required this.body,
    required this.bytes,
    required this.headers,
  });

  final int statusCode;
  final String body;
  final Uint8List bytes;
  final Map<String, String> headers;

  bool get ok => statusCode >= 200 && statusCode < 300;

  Map<String, dynamic> get jsonObject {
    final text = body.trim();
    if (text.isEmpty) return <String, dynamic>{};
    try {
      final decoded = jsonDecode(text);
      return decoded is Map<String, dynamic>
          ? decoded
          : <String, dynamic>{'detail': text};
    } catch (_) {
      return <String, dynamic>{'detail': text};
    }
  }

  dynamic get json {
    final text = body.trim();
    if (text.isEmpty) return null;
    try {
      return jsonDecode(text);
    } catch (_) {
      return text;
    }
  }

  String? header(String name) {
    final wanted = name.toLowerCase();
    for (final entry in headers.entries) {
      if (entry.key.toLowerCase() == wanted) return entry.value;
    }
    return null;
  }
}

class ApiClient {
  ApiClient._();

  static final http.Client _client = http.Client();

  /// Invoked on Bearer-authenticated requests that return HTTP 401.
  /// Wired by SessionExpiry.bind so Tickets/KB/Admin clear dead JWTs.
  static Future<void> Function(ApiResult result, String url)? onUnauthorized;

  static Future<ApiResult> send({
    required String method,
    required String url,
    Map<String, String>? headers,
    Object? jsonBody,
    bool asBytes = false,
  }) async {
    final uri = Uri.parse(url);
    final request = http.Request(method.toUpperCase(), uri);
    if (headers != null) {
      request.headers.addAll(headers);
    }
    if (jsonBody != null) {
      request.headers.putIfAbsent('Content-Type', () => 'application/json');
      request.body = jsonBody is String ? jsonBody : jsonEncode(jsonBody);
    }

    final streamed = await _client.send(request).timeout(
      const Duration(seconds: 60),
    );
    final bytes = await streamed.stream.toBytes().timeout(
      const Duration(seconds: 60),
    );
    final result = ApiResult(
      statusCode: streamed.statusCode,
      body: asBytes ? '' : utf8.decode(bytes, allowMalformed: true),
      bytes: Uint8List.fromList(bytes),
      headers: streamed.headers,
    );
    await _maybeNotifyUnauthorized(result, url, headers);
    return result;
  }

  static Future<ApiResult> multipart({
    required String method,
    required String url,
    Map<String, String>? headers,
    Map<String, String>? fields,
    List<http.MultipartFile>? files,
  }) async {
    final uri = Uri.parse(url);
    final request = http.MultipartRequest(method.toUpperCase(), uri);
    if (headers != null) {
      // Multipart sets its own Content-Type with boundary.
      for (final entry in headers.entries) {
        if (entry.key.toLowerCase() == 'content-type') continue;
        request.headers[entry.key] = entry.value;
      }
    }
    if (fields != null) {
      request.fields.addAll(fields);
    }
    if (files != null) {
      request.files.addAll(files);
    }

    final streamed = await _client.send(request);
    final bytes = await streamed.stream.toBytes();
    final result = ApiResult(
      statusCode: streamed.statusCode,
      body: utf8.decode(bytes, allowMalformed: true),
      bytes: Uint8List.fromList(bytes),
      headers: streamed.headers,
    );
    await _maybeNotifyUnauthorized(result, url, headers);
    return result;
  }

  static bool _hasBearer(Map<String, String>? headers) {
    if (headers == null) return false;
    for (final entry in headers.entries) {
      if (entry.key.toLowerCase() != 'authorization') continue;
      return entry.value.toLowerCase().trimLeft().startsWith('bearer ');
    }
    return false;
  }

  /// Login / signup / change-password 401s are credential errors, not expired sessions.
  static bool _isCredentialAuthEndpoint(String url) {
    final path = Uri.tryParse(url)?.path.toLowerCase() ?? url.toLowerCase();
    return path.endsWith('/auth/login') ||
        path.endsWith('/auth/signup') ||
        path.endsWith('/auth/change-password');
  }

  static Future<void> _maybeNotifyUnauthorized(
    ApiResult result,
    String url,
    Map<String, String>? headers,
  ) async {
    if (result.statusCode != 401) return;
    if (!_hasBearer(headers)) return;
    if (_isCredentialAuthEndpoint(url)) return;
    final hook = onUnauthorized;
    if (hook == null) return;
    try {
      await hook(result, url);
    } catch (_) {
      // Never break the original API caller if session UX fails.
    }
  }

  static String extractError(
    Map<String, dynamic> data, {
    String fallback = 'Request failed.',
  }) {
    final detail = data['detail'];
    if (detail is String && detail.trim().isNotEmpty) return detail;
    if (detail is List && detail.isNotEmpty) {
      return detail.map((item) => item.toString()).join('\n');
    }
    if (detail is Map) {
      final message = detail['message']?.toString();
      if (message != null && message.trim().isNotEmpty) return message;
    }
    final message = data['message'];
    if (message is String && message.trim().isNotEmpty) return message;
    return fallback;
  }
}
