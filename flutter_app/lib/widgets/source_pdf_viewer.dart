import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../services/api_client.dart';
import 'source_pdf_embed.dart';

/// Build an absolute API URL for a relative source URL, with optional page range.
String resolveSourcePdfUrl(
  String? viewUrl, {
  int? page,
  int? pageEnd,
  String? section,
}) {
  final raw = (viewUrl ?? '').trim();
  if (raw.isEmpty) return '';
  final base = AppConfig.resolvedApiBase;
  var url = raw.startsWith('http')
      ? raw
      : (base.isEmpty ? raw : '$base$raw');

  final withoutHash = url.split('#').first;
  final uri = Uri.tryParse(withoutHash);
  if (uri == null) return url;

  final params = Map<String, String>.from(uri.queryParameters);
  if (page != null && page > 0) {
    params.putIfAbsent('page', () => '$page');
  }
  if (pageEnd != null && page != null && pageEnd > page) {
    params['end'] = '$pageEnd';
  }
  final cleanedSection = (section ?? '').trim();
  if (cleanedSection.isNotEmpty && uri.path.contains('/source/page/')) {
    params.putIfAbsent('section', () => cleanedSection);
  }

  var next = uri.replace(queryParameters: params.isEmpty ? null : params).toString();
  if (page != null && page > 0) {
    next = '$next#page=$page';
  }
  return next;
}

Future<void> showSourcePdfViewer(
  BuildContext context, {
  required String title,
  String? sourceLabel,
  String? sourceSection,
  int? page,
  int? pageEnd,
  String? viewUrl,
  String? pageUrl,
}) async {
  final section = (sourceSection ?? '').trim();
  final fullUrl = resolveSourcePdfUrl(
    viewUrl,
    page: page,
    pageEnd: pageEnd,
    section: section,
  );
  final pageOnlyUrl = resolveSourcePdfUrl(
    pageUrl,
    page: page,
    pageEnd: pageEnd,
    section: section,
  );
  final embedUrl = pageOnlyUrl.isNotEmpty ? pageOnlyUrl : fullUrl;

  if (embedUrl.isEmpty) {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text(
          'PDF source unavailable. Re-index this document to enable PDF viewing.',
        ),
      ),
    );
    return;
  }

  final auth = AuthScope.of(context);
  final token = auth.accessToken;
  if (token == null || token.isEmpty) {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Log in to view source PDFs.')),
    );
    return;
  }

  late final Uint8List bytes;
  try {
    final result = await ApiClient.send(
      method: 'GET',
      url: embedUrl.split('#').first,
      headers: {'Authorization': 'Bearer $token'},
      asBytes: true,
    );
    final status = result.statusCode;
    final contentType = (result.header('content-type') ?? '').toLowerCase();
    if (status == 401 || status == 403) {
      if (!context.mounted) return;
      if (status == 403) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('This source PDF is restricted for your account.'),
          ),
        );
      }
      return;
    }
    if (status < 200 || status >= 300 || !contentType.contains('pdf')) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'PDF source unavailable. Re-index this document to enable PDF viewing.',
          ),
        ),
      );
      return;
    }
    if (result.bytes.isEmpty) {
      throw StateError('Empty PDF response');
    }
    bytes = result.bytes;
  } catch (_) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text(
          'PDF source unavailable. Re-index this document to enable PDF viewing.',
        ),
      ),
    );
    return;
  }

  if (!context.mounted) return;

  final sourceName = (sourceLabel ?? '').trim().isNotEmpty
      ? sourceLabel!.trim()
      : (title.trim().isEmpty ? 'Source document' : title.trim());
  final pageLabel = () {
    if (page == null) return null;
    if (pageEnd != null && pageEnd > page) return '$page–$pageEnd';
    return '$page';
  }();

  await showDialog<void>(
    context: context,
    barrierDismissible: true,
    builder: (dialogContext) {
      return Dialog(
        insetPadding: const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 980, maxHeight: 860),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 16, 12, 12),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Source: $sourceName',
                            style: const TextStyle(
                              fontSize: 18,
                              fontWeight: FontWeight.w800,
                              color: DesignTokens.ink,
                            ),
                          ),
                          if (section.isNotEmpty) ...[
                            const SizedBox(height: 4),
                            Text(
                              'Section: $section',
                              style: const TextStyle(
                                fontSize: 13,
                                color: DesignTokens.muted,
                              ),
                            ),
                          ],
                          if (pageLabel != null) ...[
                            const SizedBox(height: 2),
                            Text(
                              pageEnd != null && page != null && pageEnd > page
                                  ? 'Pages: $pageLabel'
                                  : 'Page: $pageLabel',
                              style: const TextStyle(
                                fontSize: 13,
                                color: DesignTokens.muted,
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                    TextButton(
                      onPressed: () => openPdfExternally(bytes),
                      child: const Text('Open PDF'),
                    ),
                    IconButton(
                      tooltip: 'Close',
                      onPressed: () => Navigator.of(dialogContext).pop(),
                      icon: const Icon(Icons.close_rounded),
                    ),
                  ],
                ),
              ),
              const Divider(height: 1),
              Expanded(
                child: ClipRRect(
                  borderRadius: const BorderRadius.only(
                    bottomLeft: Radius.circular(18),
                    bottomRight: Radius.circular(18),
                  ),
                  child: SourcePdfEmbed(bytes: bytes),
                ),
              ),
            ],
          ),
        ),
      );
    },
  );
}
