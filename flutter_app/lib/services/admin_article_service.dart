import 'dart:convert';
import 'dart:html' as html;

import '../models/admin_article_models.dart';

typedef AdminHeaderSetter = void Function(html.HttpRequest request);

class AdminArticleService {
  AdminArticleService({
    required this.apiBase,
    required this.setAdminHeader,
  });

  final String apiBase;
  final AdminHeaderSetter setAdminHeader;

  Future<List<AdminArticle>> listArticles() async {
    final data = await _request(method: 'GET', path: '/admin/kb/articles');
    final items = _readArticleList(data);
    return items
        .map((item) => AdminArticle.fromListJson(Map<String, dynamic>.from(item)))
        .toList();
  }

  Future<AdminArticle> getArticle(String id) async {
    final data = await _request(method: 'GET', path: '/admin/kb/articles/$id');
    if (data is! Map) {
      throw AdminArticleRequestException(
        message: 'Invalid article response.',
        responseBody: data?.toString(),
      );
    }
    return AdminArticle.fromJson(Map<String, dynamic>.from(data));
  }

  Future<AdminArticle> updateArticle(
    String id,
    Map<String, dynamic> payload,
  ) async {
    final data = await _request(
      method: 'PATCH',
      path: '/admin/kb/articles/$id',
      body: payload,
    );
    if (data is! Map) {
      throw AdminArticleRequestException(
        message: 'Invalid article response.',
        responseBody: data?.toString(),
      );
    }
    return AdminArticle.fromJson(Map<String, dynamic>.from(data));
  }

  Future<AdminArticle> createArticle(
    Map<String, dynamic> payload, {
    String? updateExistingId,
    bool forceCreate = false,
  }) async {
    final body = Map<String, dynamic>.from(payload);
    if (updateExistingId != null && updateExistingId.trim().isNotEmpty) {
      body['update_existing_id'] = updateExistingId.trim();
    }
    if (forceCreate) {
      body['force_create'] = true;
    }
    final data = await _request(
      method: 'POST',
      path: '/admin/kb/articles',
      body: body,
    );
    if (data is! Map) {
      throw AdminArticleRequestException(
        message: 'Invalid article response.',
        responseBody: data?.toString(),
      );
    }
    return AdminArticle.fromJson(Map<String, dynamic>.from(data));
  }

  Future<void> publishArticle(String id) async {
    await _request(method: 'POST', path: '/admin/kb/articles/$id/publish');
  }

  Future<void> unpublishArticle(String id) async {
    await _request(method: 'POST', path: '/admin/kb/articles/$id/unpublish');
  }

  Future<void> deleteArticle(String id) async {
    await _request(method: 'DELETE', path: '/admin/kb/articles/$id');
  }

  Future<BulkArticleActionResult> bulkSaveDraft(
    List<Map<String, dynamic>> articles,
  ) async {
    return _bulkAction(
      path: '/admin/kb/articles/bulk-save-draft',
      articles: articles,
    );
  }

  Future<BulkArticleActionResult> bulkPublish(
    List<Map<String, dynamic>> articles,
  ) async {
    return _bulkAction(
      path: '/admin/kb/articles/bulk-publish',
      articles: articles,
    );
  }

  Future<BulkArticleActionResult> bulkUnpublish(List<String> articleIds) async {
    final data = await _request(
      method: 'POST',
      path: '/admin/kb/articles/bulk-unpublish',
      body: {'article_ids': articleIds},
    );
    if (data is! Map) {
      throw AdminArticleRequestException(
        message: 'Invalid bulk unpublish response.',
        responseBody: data?.toString(),
      );
    }
    return BulkArticleActionResult.fromJson(Map<String, dynamic>.from(data));
  }

  Future<BulkArticleActionResult> _bulkAction({
    required String path,
    required List<Map<String, dynamic>> articles,
  }) async {
    final data = await _request(
      method: 'POST',
      path: path,
      body: {'articles': articles},
    );
    if (data is! Map) {
      throw AdminArticleRequestException(
        message: 'Invalid bulk article response.',
        responseBody: data?.toString(),
      );
    }
    return BulkArticleActionResult.fromJson(Map<String, dynamic>.from(data));
  }

  Future<Map<String, AdminArticle>> fetchArticlesByIds(Iterable<String> ids) async {
    final uniqueIds = ids.where((id) => id.trim().isNotEmpty).toSet();
    if (uniqueIds.isEmpty) return {};

    try {
      final all = await listArticles();
      final fromList = {
        for (final article in all)
          if (uniqueIds.contains(article.id)) article.id: article,
      };
      if (fromList.isNotEmpty) {
        if (fromList.length == uniqueIds.length) return fromList;
      }
    } on AdminArticleRequestException {
      // Fall through to per-id fetch.
    }

    final map = <String, AdminArticle>{};
    AdminArticleRequestException? lastError;
    for (final id in uniqueIds) {
      try {
        map[id] = await getArticle(id);
      } on AdminArticleRequestException catch (error) {
        lastError = error;
      }
    }
    if (map.isEmpty && lastError != null) throw lastError;
    return map;
  }

  Future<CandidateGenerationResult> generateFromPreview({
    required Map<String, dynamic> preview,
    String? filename,
    int? maxCandidates,
    String saveMode = 'preview_only',
  }) async {
    final body = <String, dynamic>{
      'preview': preview,
      if (filename != null && filename.isNotEmpty) 'filename': filename,
      if (maxCandidates != null && maxCandidates > 0)
        'max_candidates': maxCandidates,
      'save_mode': saveMode,
    };
    final data = await _request(
      method: 'POST',
      path: '/admin/kb/articles/generate-preview',
      body: body,
    );
    if (data is! Map) {
      throw AdminArticleRequestException(
        message: 'Invalid candidate generation response.',
        responseBody: data?.toString(),
      );
    }
    return CandidateGenerationResult.fromJson(Map<String, dynamic>.from(data));
  }

  Future<CandidateGenerationResult> generateFromSource({
    required html.File file,
    String? documentType,
    int? maxCandidates,
    String? previewFilePath,
  }) async {
    final formData = html.FormData();
    formData.appendBlob('file', file, file.name);
    if (documentType != null && documentType.isNotEmpty && documentType != 'auto') {
      formData.append('document_type', documentType);
    }
    if (maxCandidates != null && maxCandidates > 0) {
      formData.append('max_candidates', '$maxCandidates');
    }
    if (previewFilePath != null && previewFilePath.trim().isNotEmpty) {
      formData.append('preview_file_path', previewFilePath.trim());
    }

    final data = await _request(
      method: 'POST',
      path: '/admin/kb/articles/generate-from-source',
      formData: formData,
    );
    if (data is! Map) {
      throw AdminArticleRequestException(
        message: 'Invalid candidate generation response.',
        responseBody: data?.toString(),
      );
    }
    return CandidateGenerationResult.fromJson(Map<String, dynamic>.from(data));
  }

  List<Map<String, dynamic>> _readArticleList(dynamic data) {
    if (data is List) {
      return data.whereType<Map>().map((item) => Map<String, dynamic>.from(item)).toList();
    }
    if (data is Map) {
      final items = data['items'] ?? data['articles'] ?? data['results'];
      if (items is List) {
        return items.whereType<Map>().map((item) => Map<String, dynamic>.from(item)).toList();
      }
      throw AdminArticleRequestException(
        message: 'Unexpected article list response shape.',
        responseBody: jsonEncode(data),
      );
    }
    return const [];
  }

  Future<dynamic> _request({
    required String method,
    required String path,
    Map<String, dynamic>? body,
    html.FormData? formData,
  }) async {
    final url = apiBase.isEmpty ? path : '$apiBase$path';
    final request = html.HttpRequest();
    request.open(method, url);
    try {
      setAdminHeader(request);
    } catch (error) {
      throw AdminArticleRequestException(message: error.toString());
    }
    if (formData != null) {
      request.send(formData);
    } else if (body != null) {
      request.setRequestHeader('Content-Type', 'application/json');
      request.send(jsonEncode(body));
    } else {
      request.send();
    }
    await request.onLoadEnd.first;

    final status = request.status;
    final responseText = request.responseText ?? '';
    dynamic decoded;
    if (responseText.isNotEmpty) {
      try {
        decoded = jsonDecode(responseText);
      } catch (_) {
        decoded = responseText;
      }
    }

    if (status == null || status < 200 || status >= 300) {
      throw _buildRequestException(status: status, decoded: decoded, responseText: responseText);
    }
    return decoded;
  }

  AdminArticleRequestException _buildRequestException({
    required int? status,
    required dynamic decoded,
    required String responseText,
  }) {
    String? detail;
    Map<String, dynamic>? conflictDetail;
    if (decoded is Map) {
      final rawDetail = decoded['detail'];
      if (rawDetail is Map) {
        conflictDetail = Map<String, dynamic>.from(rawDetail);
        final messageText = conflictDetail['message']?.toString();
        detail = messageText ?? jsonEncode(rawDetail);
      } else if (rawDetail != null) {
        detail = rawDetail is String ? rawDetail : jsonEncode(rawDetail);
      }
    }

    final body = responseText.trim().isNotEmpty
        ? responseText.trim()
        : (decoded != null ? decoded.toString() : null);

    return AdminArticleRequestException(
      message: _formatError(status, detail),
      statusCode: status,
      responseBody: body,
      conflictDetail: conflictDetail,
    );
  }

  String _formatError(int? status, String? detail) {
    if (status == 0) {
      return 'Could not reach the backend at $apiBase.';
    }
    if (status == 401) {
      return 'Admin authorization failed. Please log in again as admin.';
    }
    if (status == 403) {
      return 'Only admin accounts can use Knowledge Base Admin tools.';
    }
    final text = detail?.trim() ?? '';
    if (text.isNotEmpty) return text;
    return status == null ? 'Request failed.' : 'Request failed with status $status.';
  }
}
