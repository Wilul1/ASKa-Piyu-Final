import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../services/api_client.dart';
import 'source_pdf_embed.dart';

/// Build an absolute API URL for a relative source_view_url, with optional page fragment.
String resolveSourcePdfUrl(String? viewUrl, {int? page}) {
  final raw = (viewUrl ?? '').trim();
  if (raw.isEmpty) return '';
  final base = AppConfig.resolvedApiBase;
  var url = raw.startsWith('http')
      ? raw
      : (base.isEmpty ? raw : '$base$raw');

  if (page != null && page > 0) {
    final withoutHash = url.split('#').first;
    var next = withoutHash;
    if (!RegExp(r'[?&]page=\d+').hasMatch(next)) {
      final sep = next.contains('?') ? '&' : '?';
      next = '$next${sep}page=$page';
    }
    url = '$next#page=$page';
  } else if (!url.contains('#page=') &&
      RegExp(r'[?&]page=(\d+)').hasMatch(url)) {
    final match = RegExp(r'[?&]page=(\d+)').firstMatch(url);
    final pageFromQuery = int.tryParse(match?.group(1) ?? '');
    if (pageFromQuery != null && pageFromQuery > 0) {
      url = '${url.split('#').first}#page=$pageFromQuery';
    }
  }
  return url;
}

Future<void> showSourcePdfViewer(
  BuildContext context, {
  required String title,
  String? sourceLabel,
  String? sourceSection,
  int? page,
  String? viewUrl,
  String? pageUrl,
}) async {
  final fullUrl = resolveSourcePdfUrl(viewUrl, page: page);
  final pageOnlyUrl = resolveSourcePdfUrl(pageUrl, page: page);
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
      // 401: ApiClient + SessionExpiry already cleared the JWT and opened Login.
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
  final sectionName = (sourceSection ?? '').trim();

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
                          if (sectionName.isNotEmpty) ...[
                            const SizedBox(height: 4),
                            Text(
                              'Section: $sectionName',
                              style: const TextStyle(
                                fontSize: 13,
                                color: DesignTokens.muted,
                              ),
                            ),
                          ],
                          if (page != null) ...[
                            const SizedBox(height: 2),
                            Text(
                              'Page: $page',
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
