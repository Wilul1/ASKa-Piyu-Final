import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../models/admin_article_models.dart';
import '../models/article_media_models.dart';
import 'api_client.dart';

typedef AdminHeaderSetter = void Function(Map<String, String> headers);

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

  Future<void> reindexArticle(String id) async {
    await _request(method: 'POST', path: '/admin/kb/articles/$id/reindex');
  }

  Future<Map<String, dynamic>> reindexStaleArticles() async {
    final data = await _request(
      method: 'POST',
      path: '/admin/kb/articles/reindex-stale',
    );
    if (data is! Map) {
      throw AdminArticleRequestException(
        message: 'Invalid reindex-stale response.',
        responseBody: data?.toString(),
      );
    }
    return Map<String, dynamic>.from(data);
  }

  Future<void> unpublishArticle(String id) async {
    await _request(method: 'POST', path: '/admin/kb/articles/$id/unpublish');
  }

  Future<void> deleteArticle(String id) async {
    await _request(method: 'DELETE', path: '/admin/kb/articles/$id');
  }

  Future<ArticleMediaItem> uploadArticleMedia({
    required Uint8List bytes,
    required String filename,
    required String kind,
    String? articleId,
  }) async {
    final path = (articleId != null && articleId.trim().isNotEmpty)
        ? '/admin/kb/articles/${articleId.trim()}/media'
        : '/admin/kb/media';
    final data = await _request(
      method: 'POST',
      path: path,
      fields: {'kind': kind},
      files: [
        http.MultipartFile.fromBytes('file', bytes, filename: filename),
      ],
    );
    if (data is! Map) {
      throw AdminArticleRequestException(
        message: 'Invalid media upload response.',
        responseBody: data?.toString(),
      );
    }
    return ArticleMediaItem.fromJson(Map<String, dynamic>.from(data));
  }

  Future<List<ArticleMediaItem>> listArticleMedia(String articleId) async {
    final data = await _request(
      method: 'GET',
      path: '/admin/kb/articles/$articleId/media',
    );
    if (data is! List) return const [];
    return data
        .whereType<Map>()
        .map((item) => ArticleMediaItem.fromJson(Map<String, dynamic>.from(item)))
        .toList();
  }

  Future<void> deleteArticleMedia(String mediaId) async {
    await _request(method: 'DELETE', path: '/admin/kb/media/$mediaId');
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
      'preview': _slimPreviewForGeneration(preview),
      if (filename != null && filename.isNotEmpty) 'filename': filename,
      if (maxCandidates != null && maxCandidates > 0)
        'max_candidates': maxCandidates,
      'save_mode': saveMode,
    };
    final data = await _request(
      method: 'POST',
      path: '/admin/kb/articles/generate-preview',
      body: body,
      // Handbooks with many units (e.g. Faculty Manual ~80) need more than
      // the default 60s API timeout used by lighter admin calls.
      timeout: const Duration(minutes: 20),
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
    required Uint8List bytes,
    required String filename,
    String? documentType,
    int? maxCandidates,
    String? previewFilePath,
  }) async {
    final fields = <String, String>{};
    if (documentType != null &&
        documentType.isNotEmpty &&
        documentType != 'auto') {
      fields['document_type'] = documentType;
    }
    if (maxCandidates != null && maxCandidates > 0) {
      fields['max_candidates'] = '$maxCandidates';
    }
    if (previewFilePath != null && previewFilePath.trim().isNotEmpty) {
      fields['preview_file_path'] = previewFilePath.trim();
    }

    final data = await _request(
      method: 'POST',
      path: '/admin/kb/articles/generate-from-source',
      fields: fields,
      files: [
        http.MultipartFile.fromBytes('file', bytes, filename: filename),
      ],
      timeout: const Duration(minutes: 20),
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
    Map<String, String>? fields,
    List<http.MultipartFile>? files,
    Duration timeout = ApiClient.defaultTimeout,
  }) async {
    final url = apiBase.isEmpty ? path : '$apiBase$path';
    final headers = <String, String>{};
    try {
      setAdminHeader(headers);
    } catch (error) {
      throw AdminArticleRequestException(message: error.toString());
    }

    final ApiResult result;
    if (files != null || fields != null) {
      result = await ApiClient.multipart(
        method: method,
        url: url,
        headers: headers,
        fields: fields,
        files: files,
        timeout: timeout,
      );
    } else {
      result = await ApiClient.send(
        method: method,
        url: url,
        headers: headers,
        jsonBody: body,
        timeout: timeout,
      );
    }

    final decoded = result.json;
    if (!result.ok) {
      throw _buildRequestException(
        status: result.statusCode,
        decoded: decoded,
        responseText: result.body,
      );
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
        : decoded?.toString();

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
    final text = detail?.trim() ?? '';
    if (text.isNotEmpty) return text;
    if (status == 401) {
      return 'Admin authorization failed. Please log in again as admin.';
    }
    if (status == 403) {
      return 'You do not have permission to do that.';
    }
    return status == null ? 'Request failed.' : 'Request failed with status $status.';
  }
}

Map<String, dynamic> _slimPreviewForGeneration(Map<String, dynamic> preview) {
  final copy = Map<String, dynamic>.from(preview);
  final units = copy['knowledge_units'];
  final v2 = copy['charter_v2_services'];
  final hasUnits = units is List && units.isNotEmpty;
  final hasV2 = v2 is List && v2.isNotEmpty;
  if (!hasUnits && !hasV2) return copy;
  // Units already carry article text. Drop duplicate 120k review blobs so
  // generate-preview does not stall uploading a huge JSON body.
  copy.remove('review_text');
  copy.remove('cleaned_text');
  copy.remove('extracted_text');
  return copy;
}
