import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:html/dom.dart' as dom;
import 'package:html/parser.dart' as html_parser;
import 'package:url_launcher/url_launcher.dart';

import '../app_config.dart';
import '../design_tokens.dart';
import '../models/article_media_models.dart';
import 'article_html_codec.dart';
import 'article_kb_image_embed.dart';

class SafeArticleHtml extends StatelessWidget {
  const SafeArticleHtml({
    super.key,
    required this.html,
    this.imageHeaders = const {},
    this.textStyle,
  });

  final String html;
  final Map<String, String> imageHeaders;
  final TextStyle? textStyle;

  @override
  Widget build(BuildContext context) {
    final sanitized = html.trim();
    if (sanitized.isEmpty) {
      return Text(
        'No content available.',
        style: textStyle ??
            const TextStyle(
              fontSize: 16,
              height: 1.7,
              color: DesignTokens.muted,
            ),
      );
    }
    final document = html_parser.parse(sanitized);
    final nodes = document.body?.nodes ?? document.nodes;
    final children = <Widget>[];
    for (final node in nodes) {
      children.addAll(_widgetsForNode(context, node));
    }
    if (children.isEmpty) {
      return SelectableText(
        articleHtmlToPlain(sanitized),
        style: textStyle ??
            const TextStyle(
              fontSize: 16,
              height: 1.7,
              color: Color(0xFF334155),
            ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: children,
    );
  }

  List<Widget> _widgetsForNode(BuildContext context, dom.Node node) {
    if (node is! dom.Element) {
      final text = node.text?.trim() ?? '';
      if (text.isEmpty) return const [];
      return [
        Padding(
          padding: const EdgeInsets.only(bottom: 14),
          child: Text.rich(_spanForNode(context, node)),
        ),
      ];
    }
    final tag = node.localName?.toLowerCase() ?? '';
    switch (tag) {
      case 'h1':
      case 'h2':
      case 'h3':
      case 'h4':
        final size = tag == 'h1'
            ? 26.0
            : tag == 'h2'
                ? 22.0
                : tag == 'h3'
                    ? 18.0
                    : 16.0;
        return [
          Padding(
            padding: const EdgeInsets.only(bottom: 12, top: 8),
            child: Text.rich(
              _spanForChildren(context, node.nodes),
              style: TextStyle(
                fontSize: size,
                fontWeight: FontWeight.w800,
                height: 1.3,
                color: const Color(0xFF5C0A0F),
              ),
            ),
          ),
        ];
      case 'blockquote':
        return [
          Container(
            width: double.infinity,
            margin: const EdgeInsets.only(bottom: 14),
            padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
            decoration: const BoxDecoration(
              border: Border(
                left: BorderSide(color: DesignTokens.maroon, width: 3),
              ),
              color: Color(0xFFF8FAFC),
            ),
            child: Text.rich(
              _spanForChildren(context, node.nodes),
              style: const TextStyle(
                fontSize: 16,
                height: 1.65,
                fontStyle: FontStyle.italic,
                color: Color(0xFF334155),
              ),
            ),
          ),
        ];
      case 'ul':
      case 'ol':
        final items = node.children
            .where((child) => child.localName?.toLowerCase() == 'li')
            .toList();
        return [
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Column(
              children: [
                for (var i = 0; i < items.length; i++)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(
                          width: 28,
                          child: Text(
                            tag == 'ol' ? '${i + 1}.' : '•',
                            style: const TextStyle(
                              fontSize: 16,
                              height: 1.7,
                              fontWeight: FontWeight.w700,
                              color: Color(0xFF334155),
                            ),
                          ),
                        ),
                        Expanded(
                          child: Text.rich(
                            _spanForChildren(context, items[i].nodes),
                            style: const TextStyle(
                              fontSize: 16,
                              height: 1.7,
                              color: Color(0xFF334155),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
        ];
      case 'img':
        return [_image(node)];
      case 'p':
      case 'div':
        final nestedImages = node.querySelectorAll('img');
        if (nestedImages.isNotEmpty && (node.text.trim().isEmpty)) {
          return nestedImages.map(_image).toList();
        }
        return [
          Padding(
            padding: const EdgeInsets.only(bottom: 14),
            child: Text.rich(
              _spanForChildren(context, node.nodes),
              style: const TextStyle(
                fontSize: 16,
                height: 1.7,
                color: Color(0xFF334155),
              ),
            ),
          ),
          ...nestedImages.where((img) => img.parent != node).map(_image),
        ];
      default:
        if (node.text.trim().isEmpty) return const [];
        return [
          Padding(
            padding: const EdgeInsets.only(bottom: 14),
            child: Text.rich(_spanForChildren(context, node.nodes)),
          ),
        ];
    }
  }

  Widget _image(dom.Element node) {
    final src = safeArticleImageSrc(node.attributes['src']);
    final alt = node.attributes['alt'] ?? '';
    if (src == null) {
      return const SizedBox.shrink();
    }
    final url = resolveKbMediaUrl(src);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: Image.network(
              url,
              headers: imageHeaders.isEmpty ? null : imageHeaders,
              fit: BoxFit.contain,
              errorBuilder: (_, __, ___) => Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                color: const Color(0xFFF1F5F9),
                child: Text(
                  alt.isEmpty ? 'Image unavailable' : alt,
                  style: const TextStyle(color: DesignTokens.muted),
                ),
              ),
            ),
          ),
          if (alt.trim().isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              alt,
              style: const TextStyle(
                fontSize: 12,
                color: DesignTokens.muted,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ],
      ),
    );
  }

  TextSpan _spanForNode(BuildContext context, dom.Node node) {
    if (node is! dom.Element) {
      return TextSpan(text: node.text ?? '');
    }
    return _spanForChildren(context, node.nodes, element: node);
  }

  TextSpan _spanForChildren(
    BuildContext context,
    List<dom.Node> nodes, {
    dom.Element? element,
  }) {
    final children = <InlineSpan>[];
    for (final node in nodes) {
      if (node is dom.Element && node.localName?.toLowerCase() == 'img') {
        continue;
      }
      if (node is dom.Element) {
        children.add(_spanForChildren(context, node.nodes, element: node));
      } else {
        children.add(TextSpan(text: node.text ?? ''));
      }
    }
    var style = const TextStyle();
    GestureRecognizer? recognizer;
    final tag = element?.localName?.toLowerCase() ?? '';
    if (tag == 'strong' || tag == 'b') {
      style = style.copyWith(fontWeight: FontWeight.w800);
    }
    if (tag == 'em' || tag == 'i') {
      style = style.copyWith(fontStyle: FontStyle.italic);
    }
    if (tag == 'u') {
      style = style.copyWith(decoration: TextDecoration.underline);
    }
    if (tag == 'a') {
      final href = safeArticleHref(element?.attributes['href']);
      if (href != null) {
        style = style.copyWith(
          color: DesignTokens.maroon,
          decoration: TextDecoration.underline,
          fontWeight: FontWeight.w700,
        );
        recognizer = TapGestureRecognizer()
          ..onTap = () => _openSafeUrl(href);
      }
    }
    if (tag == 'br') {
      return const TextSpan(text: '\n');
    }
    return TextSpan(style: style, children: children, recognizer: recognizer);
  }
}

Future<void> _openSafeUrl(String href) async {
  final safe = safeArticleHref(href);
  if (safe == null) return;
  final uri = Uri.tryParse(safe);
  if (uri == null) return;
  if (uri.scheme.isNotEmpty &&
      uri.scheme != 'http' &&
      uri.scheme != 'https' &&
      uri.scheme != 'mailto') {
    return;
  }
  await launchUrl(uri, mode: LaunchMode.externalApplication);
}

class ArticleAttachmentsPublicList extends StatelessWidget {
  const ArticleAttachmentsPublicList({
    super.key,
    required this.attachments,
  });

  final List<ArticleMediaItem> attachments;

  @override
  Widget build(BuildContext context) {
    if (attachments.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 8),
        const Text(
          'Attachments',
          style: TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w800,
            color: Color(0xFF5C0A0F),
          ),
        ),
        const SizedBox(height: 10),
        for (final item in attachments)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: InkWell(
              onTap: () {
                final href = safeArticleImageSrc(item.url) ??
                    (item.url.startsWith('/') ? item.url : null);
                if (href == null) return;
                final url = '${AppConfig.resolvedApiBase}$href';
                _openSafeUrl(url);
              },
              child: Row(
                children: [
                  Icon(
                    item.isPdf ? Icons.picture_as_pdf_outlined : Icons.image_outlined,
                    size: 18,
                    color: DesignTokens.maroon,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      item.originalFilename,
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                        color: DesignTokens.maroon,
                        decoration: TextDecoration.underline,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}
