import 'package:flutter/material.dart';
import 'package:flutter_quill/flutter_quill.dart';

import '../app_config.dart';
import '../design_tokens.dart';
import 'article_html_codec.dart';

String resolveKbMediaUrl(String raw) {
  final src = safeArticleImageSrc(raw) ?? raw.trim();
  if (src.startsWith('http://') || src.startsWith('https://')) {
    return src;
  }
  final base = AppConfig.resolvedApiBase;
  if (src.startsWith('/')) return '$base$src';
  return src;
}

class KbImageEmbedBuilder extends EmbedBuilder {
  KbImageEmbedBuilder({this.headers = const {}});

  final Map<String, String> headers;

  @override
  String get key => BlockEmbed.imageType;

  @override
  Widget build(
    BuildContext context,
    QuillController controller,
    Embed node,
    bool readOnly,
    bool inline,
    TextStyle textStyle,
  ) {
    final raw = node.value.data?.toString() ?? '';
    final url = resolveKbMediaUrl(raw);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(8),
        child: Image.network(
          url,
          headers: headers.isEmpty ? null : headers,
          fit: BoxFit.contain,
          errorBuilder: (_, __, ___) => Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            color: const Color(0xFFF1F5F9),
            child: const Text(
              'Image unavailable',
              style: TextStyle(color: DesignTokens.muted),
            ),
          ),
        ),
      ),
    );
  }
}
