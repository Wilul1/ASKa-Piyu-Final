import 'package:flutter/material.dart';

import '../design_tokens.dart';
import '../models/admin_article_models.dart';

class KbAdminPanel extends StatelessWidget {
  const KbAdminPanel({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFE8ECF2)),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.03),
            blurRadius: 14,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: child,
    );
  }
}

class KbSectionHeader extends StatelessWidget {
  const KbSectionHeader({
    super.key,
    required this.icon,
    required this.title,
    this.subtitle,
  });

  final IconData icon;
  final String title;
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, color: DesignTokens.maroon, size: 22),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w800,
                  color: DesignTokens.ink,
                ),
              ),
              if (subtitle != null) ...[
                const SizedBox(height: 4),
                Text(
                  subtitle!,
                  style: const TextStyle(
                    fontSize: 13,
                    height: 1.45,
                    color: DesignTokens.muted,
                  ),
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

class KbStatCard extends StatelessWidget {
  const KbStatCard({
    super.key,
    required this.label,
    required this.value,
    required this.icon,
  });

  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: DesignTokens.maroon.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(icon, color: DesignTokens.maroon, size: 20),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  value,
                  style: const TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.w900,
                    color: DesignTokens.ink,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  label,
                  style: const TextStyle(fontSize: 12, color: DesignTokens.muted),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class KbBadge extends StatelessWidget {
  const KbBadge({
    super.key,
    required this.label,
    required this.background,
    required this.foreground,
  });

  final String label;
  final Color background;
  final Color foreground;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w700,
          color: foreground,
        ),
      ),
    );
  }
}

void showKbSnackBar(BuildContext context, String message) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(message),
      behavior: SnackBarBehavior.floating,
      backgroundColor: DesignTokens.ink,
    ),
  );
}

String reviewBucketLabel(ArticleReviewBucket bucket) {
  switch (bucket) {
    case ArticleReviewBucket.recommended:
      return 'Recommended';
    case ArticleReviewBucket.needsReview:
      return 'Needs Review';
    case ArticleReviewBucket.overflow:
      return 'Overflow';
    case ArticleReviewBucket.published:
      return 'Published';
  }
}

Color reviewBucketColor(ArticleReviewBucket bucket) {
  switch (bucket) {
    case ArticleReviewBucket.recommended:
      return const Color(0xFF166534);
    case ArticleReviewBucket.needsReview:
      return const Color(0xFFB45309);
    case ArticleReviewBucket.overflow:
      return const Color(0xFF475569);
    case ArticleReviewBucket.published:
      return DesignTokens.maroon;
  }
}

String formatScore(double? value) {
  if (value == null) return '—';
  return value.toStringAsFixed(value == value.roundToDouble() ? 0 : 2);
}

class FormattedArticleContentView extends StatefulWidget {
  const FormattedArticleContentView({
    super.key,
    required this.content,
    this.maxHeight = 360,
  });

  final String content;
  final double maxHeight;

  @override
  State<FormattedArticleContentView> createState() =>
      _FormattedArticleContentViewState();
}

class _FormattedArticleContentViewState extends State<FormattedArticleContentView> {
  final ScrollController _scrollController = ScrollController();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.jumpTo(0);
      }
    });
  }

  @override
  void didUpdateWidget(covariant FormattedArticleContentView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.content != widget.content) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scrollController.hasClients) {
          _scrollController.jumpTo(0);
        }
      });
    }
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final display = cleanArticleContentForDisplay(widget.content);
    if (display.isEmpty) {
      return const Text('—', style: TextStyle(height: 1.5));
    }

    final lines = display
        .replaceAll('\r\n', '\n')
        .split('\n')
        .map((line) => line.trimRight())
        .toList();

    final children = <Widget>[];
    var paragraphBuffer = <String>[];

    void flushParagraph() {
      final text = paragraphBuffer.join(' ').trim();
      paragraphBuffer = [];
      if (text.isEmpty) return;
      children.add(
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Text(text, style: const TextStyle(height: 1.5)),
        ),
      );
    }

    for (final line in lines) {
      final trimmed = line.trim();
      if (trimmed.isEmpty) {
        flushParagraph();
        continue;
      }

      if (isFormattedArticleSectionHeading(trimmed)) {
        flushParagraph();
        children.add(
          Padding(
            padding: EdgeInsets.only(top: children.isEmpty ? 0 : 12, bottom: 6),
            child: Text(
              trimmed,
              style: const TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w800,
                color: DesignTokens.ink,
              ),
            ),
          ),
        );
        continue;
      }

      final numbered = RegExp(r'^(\d+(?:\.\d+)*)\.\s+(.+)$').firstMatch(trimmed);
      if (numbered != null) {
        flushParagraph();
        final marker = numbered.group(1)!;
        final body = numbered.group(2)!.trim();
        final wordCount = body.split(RegExp(r'\s+')).where((part) => part.isNotEmpty).length;
        final isShortLabel = wordCount <= 5 &&
            body.length <= 48 &&
            !body.endsWith('.') &&
            !body.contains(',');
        children.add(
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Text.rich(
              TextSpan(
                style: const TextStyle(height: 1.45, fontWeight: FontWeight.w400),
                children: [
                  TextSpan(
                    text: '$marker. ',
                    style: TextStyle(
                      fontWeight: isShortLabel ? FontWeight.w700 : FontWeight.w400,
                    ),
                  ),
                  TextSpan(
                    text: body,
                    style: TextStyle(
                      fontWeight: isShortLabel ? FontWeight.w700 : FontWeight.w400,
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
        continue;
      }

      if (trimmed.startsWith('- ')) {
        flushParagraph();
        children.add(
          Padding(
            padding: const EdgeInsets.only(left: 8, bottom: 4),
            child: Text(trimmed, style: const TextStyle(height: 1.45)),
          ),
        );
        continue;
      }

      paragraphBuffer.add(trimmed);
    }
    flushParagraph();

    return Container(
      width: double.infinity,
      constraints: BoxConstraints(maxHeight: widget.maxHeight),
      padding: const EdgeInsets.fromLTRB(12, 14, 12, 12),
      clipBehavior: Clip.hardEdge,
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: DesignTokens.border),
      ),
      child: SingleChildScrollView(
        controller: _scrollController,
        primary: false,
        padding: EdgeInsets.zero,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: children,
        ),
      ),
    );
  }
}

class OfficialSourceExcerptPanel extends StatelessWidget {
  const OfficialSourceExcerptPanel({
    super.key,
    required this.excerpt,
    this.initiallyExpanded = false,
  });

  final String excerpt;
  final bool initiallyExpanded;

  @override
  Widget build(BuildContext context) {
    final text = cleanArticleContentForDisplay(excerpt);
    if (text.isEmpty) return const SizedBox.shrink();

    return Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        initiallyExpanded: initiallyExpanded,
        tilePadding: EdgeInsets.zero,
        title: const Text(
          'Official Source Excerpt',
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w700,
            color: DesignTokens.muted,
          ),
        ),
        subtitle: const Text(
          'Original extracted text used for grounding and verification.',
          style: TextStyle(fontSize: 12, color: DesignTokens.muted, height: 1.35),
        ),
        children: [
          Container(
            width: double.infinity,
            constraints: const BoxConstraints(maxHeight: 220),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFFF8FAFC),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: DesignTokens.border),
            ),
            child: SingleChildScrollView(
              child: SelectableText(text, style: const TextStyle(height: 1.45, fontSize: 13)),
            ),
          ),
        ],
      ),
    );
  }
}
