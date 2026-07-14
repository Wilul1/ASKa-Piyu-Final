import 'package:flutter/material.dart';

import '../design_tokens.dart';
import '../models/admin_article_models.dart';
import '../services/admin_article_service.dart';
import 'admin_article_preview_download_stub.dart'
    if (dart.library.html) 'admin_article_preview_download_web.dart';
import 'admin_article_preview_export.dart';
import 'admin_kb_article_widgets.dart';

class AdminArticleCard extends StatelessWidget {
  const AdminArticleCard({
    super.key,
    required this.article,
    required this.onView,
    required this.onEdit,
    this.onPublish,
    this.onUnpublish,
    this.onDelete,
    this.onSaveDraft,
    this.onDiscard,
    this.onDownloadTxt,
    this.onUpdateExisting,
    this.compactActions = false,
    this.lightweight = false,
    this.isUnsavedPreview = false,
    this.alreadyPublishedLabel = false,
    this.allowPublish = true,
    this.allowSaveDraft = true,
    this.showReviewBeforePublishBadge = false,
    this.showLowQualityBadges = false,
    this.allowEditAsReviewDraft = false,
    this.lowQualityHelperText,
    this.showPublicReadinessLabels = false,
    this.selected = false,
    this.onSelectedChanged,
    this.showCheckbox = false,
  });

  final AdminArticle article;
  final VoidCallback onView;
  final VoidCallback onEdit;
  final VoidCallback? onPublish;
  final VoidCallback? onUnpublish;
  final VoidCallback? onDelete;
  final VoidCallback? onSaveDraft;
  final VoidCallback? onDiscard;
  final VoidCallback? onDownloadTxt;
  final VoidCallback? onUpdateExisting;
  final bool compactActions;
  final bool lightweight;
  final bool isUnsavedPreview;
  final bool alreadyPublishedLabel;
  final bool allowPublish;
  final bool allowSaveDraft;
  final bool showReviewBeforePublishBadge;
  final bool showLowQualityBadges;
  final bool allowEditAsReviewDraft;
  final String? lowQualityHelperText;
  final bool showPublicReadinessLabels;
  final bool selected;
  final ValueChanged<bool>? onSelectedChanged;
  final bool showCheckbox;

  @override
  Widget build(BuildContext context) {
    final publishBlocked = shouldBlockCharterPublish(
      title: article.title,
      reviewReasons: article.reviewReasons,
      sourceSection: article.sourceSection,
      plannerBucket: article.metadata['planner_bucket']?.toString(),
      finalBucket: article.metadata['final_bucket']?.toString(),
    );
    final canPublish = allowPublish && !publishBlocked;
    final canSaveDraft = allowSaveDraft;
    final canEdit = !publishBlocked || allowEditAsReviewDraft;
    final editLabel =
        allowEditAsReviewDraft ? 'Edit as Review Draft' : 'Edit';
    final bucket = article.reviewBucket;
    final bucketColor = reviewBucketColor(bucket);
    final padding = lightweight ? 12.0 : 18.0;
    final titleSize = lightweight ? 16.0 : 18.0;
    final consolidatedParent = article.metadata['consolidated_parent'] == true;
    final shortSummary = lightweight
        ? buildShortSummary(
            article.summary,
            article.displayContent,
            title: article.title,
            documentType: article.documentType,
            consolidatedParent: consolidatedParent,
          )
        : '';
    final officeLabel = displayOffice(article.office);
    final groupLabel = article.metadata['group_name']?.toString();
    final sourceFilename = resolveSourceFilename(
      article,
      fallbackFilename: null,
    );

    return KbAdminPanel(
      child: Padding(
        padding: EdgeInsets.all(padding),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (showCheckbox && onSelectedChanged != null) ...[
                  Padding(
                    padding: const EdgeInsets.only(right: 8, top: 2),
                    child: Checkbox(
                      value: selected,
                      onChanged: (value) =>
                          onSelectedChanged!(value ?? false),
                      activeColor: DesignTokens.maroon,
                      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      visualDensity: VisualDensity.compact,
                    ),
                  ),
                ],
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        article.title,
                        style: TextStyle(
                          fontSize: titleSize,
                          fontWeight: FontWeight.w800,
                          color: DesignTokens.ink,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        article.category,
                        style: const TextStyle(color: DesignTokens.muted, fontSize: 13),
                      ),
                      if (lightweight && shortSummary.isNotEmpty) ...[
                        const SizedBox(height: 6),
                        Text(
                          shortSummary,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontSize: 13, height: 1.4),
                        ),
                      ],
                    ],
                  ),
                ),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    if (alreadyPublishedLabel || (!isUnsavedPreview && article.published && !showPublicReadinessLabels))
                      KbBadge(
                        label: alreadyPublishedLabel ? 'Already Published' : 'Published',
                        background: DesignTokens.maroon.withValues(alpha: 0.12),
                        foreground: DesignTokens.maroon,
                      )
                    else if (isUnsavedPreview)
                      const KbBadge(
                        label: 'Unsaved Preview',
                        background: Color(0xFFEFF6FF),
                        foreground: Color(0xFF1D4ED8),
                      )
                    else if (showPublicReadinessLabels)
                      KbBadge(
                        label: article.published ? 'Public' : 'Draft',
                        background: article.published
                            ? DesignTokens.maroon.withValues(alpha: 0.12)
                            : const Color(0xFFE2E8F0),
                        foreground: article.published
                            ? DesignTokens.maroon
                            : DesignTokens.ink,
                      )
                    else
                      KbBadge(
                        label: article.published ? 'Published' : 'Draft',
                        background: article.published
                            ? DesignTokens.maroon.withValues(alpha: 0.12)
                            : const Color(0xFFE2E8F0),
                        foreground:
                            article.published ? DesignTokens.maroon : DesignTokens.ink,
                      ),
                    if (showPublicReadinessLabels) ...[
                      if (article.needsReview || article.reviewReasons.isNotEmpty)
                        const KbBadge(
                          label: 'Needs Review',
                          background: Color(0xFFFFF7ED),
                          foreground: Color(0xFFB45309),
                        ),
                      if (_librarySourceLabel(article) != null)
                        KbBadge(
                          label: 'Source: ${_librarySourceLabel(article)}',
                          background: const Color(0xFFF8FAFC),
                          foreground: DesignTokens.muted,
                        ),
                    ],
                    if (showLowQualityBadges) ...[
                      const KbBadge(
                        label: 'Needs Cleanup',
                        background: Color(0xFFFEE2E2),
                        foreground: Color(0xFFB91C1C),
                      ),
                      const KbBadge(
                        label: 'Not recommended for direct publishing',
                        background: Color(0xFFF1F5F9),
                        foreground: Color(0xFF475569),
                      ),
                    ] else if (showReviewBeforePublishBadge)
                      const KbBadge(
                        label: 'Review before publishing',
                        background: Color(0xFFFFF7ED),
                        foreground: Color(0xFFB45309),
                      )
                    else if (!showPublicReadinessLabels && article.needsReview)
                      const KbBadge(
                        label: 'Needs Review',
                        background: Color(0xFFFFF7ED),
                        foreground: Color(0xFFB45309),
                      ),
                    if (!article.published && !lightweight && !showPublicReadinessLabels)
                      KbBadge(
                        label: reviewBucketLabel(bucket),
                        background: bucketColor.withValues(alpha: 0.12),
                        foreground: bucketColor,
                      ),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 10),
                Wrap(
              spacing: 12,
              runSpacing: 6,
              children: [
                if (lightweight && officeLabel != 'Not specified')
                  _MetaLine('Office', officeLabel),
                if (lightweight && groupLabel != null && groupLabel.isNotEmpty)
                  _MetaLine('Group', groupLabel),
                if (lightweight && sourceFilename != 'Not specified')
                  _MetaLine('Source file', sourceFilename),
                _MetaLine(
                  'Article type',
                  article.metadata['article_type']?.toString() ??
                      article.documentType ??
                      'information',
                ),
                if (article.metadata['merged_unit_count'] != null)
                  _MetaLine(
                    'Merged units',
                    '${article.metadata['merged_unit_count']}',
                  ),
                if (!lightweight || article.sourceSection != null)
                  _MetaLine(
                    'Source section',
                    displaySourceSectionForCard(article),
                  ),
                _MetaLine('Quality', formatScore(article.qualityScore)),
                _MetaLine('Confidence', formatScore(article.categoryConfidence)),
                _MetaLine('Usefulness', formatScore(article.studentUsefulnessScore)),
              ],
            ),
            if (lightweight && article.reviewReasons.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                'Review reasons: ${article.reviewReasons.join(', ')}',
                style: const TextStyle(fontSize: 12, color: Color(0xFFB45309)),
              ),
            ],
            if (!lightweight && article.reviewReasons.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                'Review reasons: ${article.reviewReasons.join(', ')}',
                style: const TextStyle(fontSize: 12, color: Color(0xFFB45309)),
              ),
            ],
            if (lowQualityHelperText != null &&
                lowQualityHelperText!.trim().isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                lowQualityHelperText!,
                style: const TextStyle(
                  fontSize: 12,
                  color: DesignTokens.muted,
                  height: 1.4,
                ),
              ),
            ],
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                OutlinedButton(
                  onPressed: onView,
                  child: const Text('View'),
                ),
                if (canEdit)
                  OutlinedButton(
                    onPressed: onEdit,
                    child: Text(editLabel),
                  ),
                if (onDownloadTxt != null)
                  TextButton(
                    onPressed: onDownloadTxt,
                    child: const Text('Download TXT'),
                  ),
                if (canSaveDraft && isUnsavedPreview && onSaveDraft != null)
                  OutlinedButton(
                    onPressed: onSaveDraft,
                    child: const Text('Save as Draft'),
                  ),
                if (onUpdateExisting != null)
                  ElevatedButton(
                    onPressed: onUpdateExisting,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: DesignTokens.maroon,
                      foregroundColor: Colors.white,
                    ),
                    child: const Text('Update Existing'),
                  ),
                if (canPublish &&
                    !alreadyPublishedLabel &&
                    !isUnsavedPreview &&
                    !article.published &&
                    onPublish != null)
                  ElevatedButton(
                    onPressed: onPublish,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: DesignTokens.maroon,
                      foregroundColor: Colors.white,
                    ),
                    child: const Text('Publish'),
                  ),
                if (canPublish &&
                    !alreadyPublishedLabel &&
                    isUnsavedPreview &&
                    onPublish != null)
                  ElevatedButton(
                    onPressed: onPublish,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: DesignTokens.maroon,
                      foregroundColor: Colors.white,
                    ),
                    child: const Text('Publish'),
                  ),
                if (!isUnsavedPreview &&
                    article.published &&
                    onUnpublish != null &&
                    !publishBlocked)
                  OutlinedButton(
                    onPressed: onUnpublish,
                    child: const Text('Unpublish'),
                  ),
                if (isUnsavedPreview && !alreadyPublishedLabel && onDiscard != null)
                  TextButton(
                    onPressed: onDiscard,
                    style: TextButton.styleFrom(foregroundColor: Colors.red.shade700),
                    child: const Text('Discard'),
                  ),
                if (!isUnsavedPreview && !compactActions && onDelete != null)
                  TextButton(
                    onPressed: onDelete,
                    style: TextButton.styleFrom(foregroundColor: Colors.red.shade700),
                    child: const Text('Delete'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _MetaLine extends StatelessWidget {
  const _MetaLine(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Text(
      '$label: $value',
      style: const TextStyle(fontSize: 12, color: DesignTokens.muted),
    );
  }
}

String? _librarySourceLabel(AdminArticle article) {
  final raw = (article.sourceFilename ?? '').trim();
  if (raw.isEmpty) return null;
  final lower = raw.toLowerCase();
  if (lower.contains('handbook')) return 'Student Handbook';
  if (lower.contains('charter') || lower.contains('citizen')) {
    return "Citizen's Charter";
  }
  final cleaned = raw
      .replaceAll(RegExp(r'\.[^.]+$'), '')
      .replaceAll(RegExp(r'[_\-]+'), ' ')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
  return cleaned.isEmpty ? null : cleaned;
}

Future<void> showAdminArticleViewDialog(
  BuildContext context,
  AdminArticle article,
  AdminArticleService service, {
  String? fallbackSourceFilename,
}) async {
  await showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (dialogContext) {
      return FutureBuilder<AdminArticle>(
        future: article.hasLoadedContent
            ? Future.value(article)
            : service.getArticle(article.id),
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const AlertDialog(
              content: Padding(
                padding: EdgeInsets.all(24),
                child: Center(
                  child: CircularProgressIndicator(color: DesignTokens.maroon),
                ),
              ),
            );
          }
          if (snapshot.hasError) {
            return AlertDialog(
              title: const Text('Could not load article'),
              content: SelectableText(snapshot.error.toString()),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(),
                  child: const Text('Close'),
                ),
              ],
            );
          }

          final full = snapshot.data ?? article;
          final displayContent = cleanArticleContentForDisplay(full.displayContent);
          final shortSummary = buildShortSummary(
            full.summary,
            displayContent,
            title: full.title,
            documentType: full.documentType,
          );
          final showSummary = shortSummary.isNotEmpty;
          final showContentSummary = showSummary &&
              normalizeArticleText(shortSummary) != normalizeArticleText(displayContent);

          return AlertDialog(
            title: Text(full.title),
            content: SizedBox(
              width: 720,
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _DialogField('Category', full.category),
                    if (showContentSummary)
                      _DialogField('Short Summary', shortSummary),
                    const Text(
                      'Article Content',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: DesignTokens.muted,
                      ),
                    ),
                    const SizedBox(height: 6),
                    FormattedArticleContentView(content: displayContent),
                    const SizedBox(height: 12),
                    const Text(
                      'Source Information',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w800,
                        color: DesignTokens.ink,
                      ),
                    ),
                    const SizedBox(height: 6),
                    _DialogField(
                      'Source filename',
                      resolveSourceFilename(
                        full,
                        fallbackFilename: fallbackSourceFilename,
                      ),
                    ),
                    _DialogField(
                      'Source section',
                      displaySourceSectionsForView(full),
                    ),
                    _DialogField(
                      'Document type',
                      full.documentType ?? 'information',
                    ),
                    _DialogField('Office', displayOffice(full.office)),
                    if ((full.officialSourceExcerpt ?? '').trim().isNotEmpty)
                      OfficialSourceExcerptPanel(
                        excerpt: full.officialSourceExcerpt!,
                      ),
                    Theme(
                      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                      child: ExpansionTile(
                        tilePadding: EdgeInsets.zero,
                        title: const Text(
                          'Admin Metadata',
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                            color: DesignTokens.muted,
                          ),
                        ),
                        children: [
                          _DialogField('Quality score', formatScore(full.qualityScore)),
                          _DialogField(
                            'Category confidence',
                            formatScore(full.categoryConfidence),
                          ),
                          _DialogField(
                            'Student usefulness',
                            formatScore(full.studentUsefulnessScore),
                          ),
                          _DialogField(
                            'Review reasons',
                            full.reviewReasons.isEmpty
                                ? '—'
                                : full.reviewReasons.join(', '),
                          ),
                          _DialogField(
                            'Published status',
                            full.published ? 'Published' : 'Draft',
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(dialogContext).pop(),
                child: const Text('Close'),
              ),
            ],
          );
        },
      );
    },
  );
}

Future<dynamic> showAdminArticleEditDialog({
  required BuildContext context,
  required AdminArticle article,
  required AdminArticleService service,
  bool isPreview = false,
  bool asReviewDraft = false,
}) {
  return showDialog<dynamic>(
    context: context,
    barrierDismissible: false,
    builder: (dialogContext) {
      if (isPreview || isPreviewCandidateId(article.id)) {
        return _AdminArticleEditDialogBody(
          article: article,
          service: service,
          isPreview: true,
          asReviewDraft: asReviewDraft,
        );
      }
      return FutureBuilder<AdminArticle>(
        future: article.hasLoadedContent
            ? Future.value(article)
            : service.getArticle(article.id),
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const AlertDialog(
              content: Padding(
                padding: EdgeInsets.all(24),
                child: Center(
                  child: CircularProgressIndicator(color: DesignTokens.maroon),
                ),
              ),
            );
          }
          if (snapshot.hasError) {
            return AlertDialog(
              title: const Text('Could not load article'),
              content: SelectableText(snapshot.error.toString()),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(false),
                  child: const Text('Close'),
                ),
              ],
            );
          }

          final loaded = snapshot.data ?? article;
          return _AdminArticleEditDialogBody(
            article: loaded,
            service: service,
            isPreview: false,
            asReviewDraft: asReviewDraft,
          );
        },
      );
    },
  );
}

class _AdminArticleEditDialogBody extends StatefulWidget {
  const _AdminArticleEditDialogBody({
    required this.article,
    required this.service,
    this.isPreview = false,
    this.asReviewDraft = false,
  });

  final AdminArticle article;
  final AdminArticleService service;
  final bool isPreview;
  final bool asReviewDraft;

  @override
  State<_AdminArticleEditDialogBody> createState() =>
      _AdminArticleEditDialogBodyState();
}

class _AdminArticleEditDialogBodyState extends State<_AdminArticleEditDialogBody> {
  late final TextEditingController titleController =
      TextEditingController(text: widget.article.title);
  late final TextEditingController categoryController =
      TextEditingController(text: widget.article.category);
  late final TextEditingController summaryController =
      TextEditingController(
          text: buildShortSummary(
            widget.article.summary,
            widget.article.displayContent,
            title: widget.article.title,
            documentType: widget.article.documentType,
          ));
  late final TextEditingController contentController =
      TextEditingController(
          text: cleanArticleContentForDisplay(widget.article.displayContent));
  late final TextEditingController officeController =
      TextEditingController(text: widget.article.office ?? '');
  late final TextEditingController sourceController =
      TextEditingController(text: widget.article.sourceFilename ?? '');
  late final TextEditingController sourceSectionController =
      TextEditingController(text: widget.article.sourceSection ?? '');
  late final TextEditingController articleTypeController =
      TextEditingController(
          text: widget.article.metadata['article_type']?.toString() ??
              widget.article.documentType ??
              '');
  var saving = false;

  @override
  void dispose() {
    titleController.dispose();
    categoryController.dispose();
    summaryController.dispose();
    contentController.dispose();
    officeController.dispose();
    sourceController.dispose();
    sourceSectionController.dispose();
    articleTypeController.dispose();
    super.dispose();
  }

  Future<void> save() async {
    setState(() => saving = true);
    try {
      var content = contentController.text.trim();
      final raw = widget.article.content ?? '';
      const marker = '----EXTRACTED METADATA----';
      final markerIndex = raw.indexOf(marker);
      if (markerIndex >= 0) {
        content = '$content\n\n${raw.substring(markerIndex)}';
      }
      final meta = Map<String, dynamic>.from(widget.article.metadata);
      final sourceSection = sourceSectionController.text.trim();
      final articleType = articleTypeController.text.trim();
      if (sourceSection.isNotEmpty) {
        meta['source_section'] = sourceSection;
      }
      if (articleType.isNotEmpty) {
        meta['article_type'] = articleType;
      }
      if (widget.isPreview) {
        var updated = AdminArticle(
          id: widget.article.id,
          title: titleController.text.trim(),
          category: categoryController.text.trim(),
          published: false,
          summary: summaryController.text.trim(),
          content: content,
          office: officeController.text.trim(),
          sourceFilename: sourceController.text.trim(),
          metadata: meta,
          displayContent: cleanArticleContentForDisplay(content.split(marker).first.trim()),
        );
        if (widget.asReviewDraft) {
          updated = stampManualReviewFromLowQuality(updated);
        }
        if (mounted) Navigator.of(context).pop(updated);
        return;
      }
      await widget.service.updateArticle(
        widget.article.id,
        widget.article.toUpdatePayload(
          title: titleController.text.trim(),
          category: categoryController.text.trim(),
          summary: summaryController.text.trim(),
          content: content,
          office: officeController.text.trim(),
          sourceFilename: sourceController.text.trim(),
        ),
      );
      if (mounted) Navigator.of(context).pop(true);
    } catch (error) {
      if (mounted) showKbSnackBar(context, error.toString());
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final article = widget.article;
    return AlertDialog(
      title: Text(widget.asReviewDraft ? 'Edit as Review Draft' : 'Edit Article'),
      content: SizedBox(
        width: 720,
        child: SingleChildScrollView(
          child: Column(
            children: [
              if (widget.asReviewDraft) ...[
                const Align(
                  alignment: Alignment.centerLeft,
                  child: Text(
                    'Manual review draft — not auto-recommended. Save as draft, then publish from Drafts after placeholders are removed.',
                    style: TextStyle(fontSize: 12, color: DesignTokens.muted, height: 1.4),
                  ),
                ),
                const SizedBox(height: 12),
              ],
              TextField(
                controller: titleController,
                decoration: const InputDecoration(labelText: 'Title'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: categoryController,
                decoration: const InputDecoration(labelText: 'Category'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: summaryController,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(labelText: 'Summary'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: contentController,
                minLines: 8,
                maxLines: 14,
                decoration: const InputDecoration(
                  labelText: 'Article Content',
                  helperText: 'Student-friendly formatted content shown in the knowledge base.',
                ),
              ),
              if ((article.officialSourceExcerpt ?? '').trim().isNotEmpty) ...[
                const SizedBox(height: 12),
                OfficialSourceExcerptPanel(
                  excerpt: article.officialSourceExcerpt!,
                ),
              ],
              const SizedBox(height: 10),
              TextField(
                controller: officeController,
                decoration: const InputDecoration(labelText: 'Office'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: sourceController,
                decoration: const InputDecoration(labelText: 'Source filename'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: sourceSectionController,
                decoration: const InputDecoration(labelText: 'Source section'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: articleTypeController,
                decoration: const InputDecoration(
                  labelText: 'Article type',
                  helperText: 'e.g. procedure, policy, information',
                ),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: saving ? null : () => Navigator.of(context).pop(false),
          child: const Text('Cancel'),
        ),
        if (!widget.isPreview && !article.published && !widget.asReviewDraft)
          TextButton(
            onPressed: saving
                ? null
                : () async {
                    try {
                      await widget.service.publishArticle(article.id);
                      if (context.mounted) Navigator.of(context).pop(true);
                    } catch (error) {
                      if (context.mounted) showKbSnackBar(context, error.toString());
                    }
                  },
            child: const Text('Publish'),
          ),
        if (!widget.isPreview && article.published)
          TextButton(
            onPressed: saving
                ? null
                : () async {
                    try {
                      await widget.service.unpublishArticle(article.id);
                      if (context.mounted) Navigator.of(context).pop(true);
                    } catch (error) {
                      if (context.mounted) showKbSnackBar(context, error.toString());
                    }
                  },
            child: const Text('Unpublish'),
          ),
        if (!widget.isPreview)
          TextButton(
            onPressed: saving
                ? null
                : () async {
                    try {
                      await widget.service.deleteArticle(article.id);
                      if (context.mounted) Navigator.of(context).pop(true);
                    } catch (error) {
                      if (context.mounted) showKbSnackBar(context, error.toString());
                    }
                  },
            child: Text('Delete', style: TextStyle(color: Colors.red.shade700)),
          ),
        ElevatedButton(
          onPressed: saving ? null : save,
          style: ElevatedButton.styleFrom(
            backgroundColor: DesignTokens.maroon,
            foregroundColor: Colors.white,
          ),
          child: saving
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                )
              : Text(widget.asReviewDraft && widget.isPreview
                  ? 'Apply Corrections'
                  : 'Save Changes'),
        ),
      ],
    );
  }
}

class _DialogField extends StatelessWidget {
  const _DialogField(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: DesignTokens.muted,
            ),
          ),
          const SizedBox(height: 4),
          Text(value, style: const TextStyle(height: 1.45)),
        ],
      ),
    );
  }
}

class CandidateGroupPanel extends StatefulWidget {
  const CandidateGroupPanel({
    super.key,
    required this.title,
    required this.items,
    this.expandedInitially = false,
    this.initialVisibleCount = 10,
    this.pageSize = 10,
  });

  final String title;
  final List<CandidateSummary> items;
  final bool expandedInitially;
  final int initialVisibleCount;
  final int pageSize;

  @override
  State<CandidateGroupPanel> createState() => _CandidateGroupPanelState();
}

class _CandidateGroupPanelState extends State<CandidateGroupPanel> {
  late bool _expanded = widget.expandedInitially;
  late int _visibleCount = widget.initialVisibleCount;

  @override
  void didUpdateWidget(CandidateGroupPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.items != widget.items) {
      _visibleCount = widget.initialVisibleCount;
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.items.isEmpty) return const SizedBox.shrink();

    final visibleItems = _expanded
        ? widget.items.take(_visibleCount).toList()
        : const <CandidateSummary>[];
    final hasMore = _expanded && _visibleCount < widget.items.length;

    return KbAdminPanel(
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: EdgeInsets.zero,
          childrenPadding: const EdgeInsets.only(top: 8),
          initiallyExpanded: widget.expandedInitially,
          onExpansionChanged: (value) => setState(() => _expanded = value),
          title: Text(
            '${widget.title} (${widget.items.length})',
            style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: DesignTokens.ink,
            ),
          ),
          children: [
            ...visibleItems.map(
              (item) => Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: _CandidateSummaryRow(item: item),
              ),
            ),
            if (hasMore)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton(
                  onPressed: () => setState(
                    () => _visibleCount += widget.pageSize,
                  ),
                  child: Text(
                    'Load more (${widget.items.length - _visibleCount} remaining)',
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class GeneratedCandidateGroupSection extends StatefulWidget {
  const GeneratedCandidateGroupSection({
    super.key,
    required this.title,
    required this.bucketKey,
    required this.items,
    required this.previewArticlesById,
    required this.savedArticlesByPreviewId,
    required this.discardedPreviewIds,
    required this.service,
    required this.onArticlesChanged,
    required this.onPreviewUpdated,
    required this.onPreviewSaved,
    required this.onDiscardPreview,
    this.expandedInitially = false,
    this.initialVisibleCount = 10,
    this.pageSize = 10,
    this.fallbackSourceFilename,
    this.allowPublish = true,
    this.allowSaveDraft = true,
    this.allowBulkPublish = false,
    this.allowBulkSaveDraft = false,
    this.showReviewBeforePublishBadge = false,
    this.showLowQualityBadges = false,
    this.allowEditAsReviewDraft = false,
    this.lowQualityHelperText,
    this.bulkPublishAllLabel,
    this.bulkSaveAllLabel,
    this.bulkPublishAllConfirmMessage,
  });

  final String title;
  final String bucketKey;
  final List<CandidateSummary> items;
  final Map<String, AdminArticle> previewArticlesById;
  final Map<String, AdminArticle> savedArticlesByPreviewId;
  final Set<String> discardedPreviewIds;
  final AdminArticleService service;
  final Future<void> Function() onArticlesChanged;
  final void Function(String previewId, AdminArticle article) onPreviewUpdated;
  final void Function(String previewId, AdminArticle saved) onPreviewSaved;
  final void Function(String previewId) onDiscardPreview;
  final bool expandedInitially;
  final int initialVisibleCount;
  final int pageSize;
  final String? fallbackSourceFilename;
  final bool allowPublish;
  final bool allowSaveDraft;
  final bool allowBulkPublish;
  final bool allowBulkSaveDraft;
  final bool showReviewBeforePublishBadge;
  final bool showLowQualityBadges;
  final bool allowEditAsReviewDraft;
  final String? lowQualityHelperText;
  final String? bulkPublishAllLabel;
  final String? bulkSaveAllLabel;
  final String? bulkPublishAllConfirmMessage;

  @override
  State<GeneratedCandidateGroupSection> createState() =>
      _GeneratedCandidateGroupSectionState();
}

class _GeneratedCandidateGroupSectionState
    extends State<GeneratedCandidateGroupSection> {
  late bool _expanded = widget.expandedInitially;
  late int _visibleCount = widget.initialVisibleCount;
  final Set<String> _selectedIds = {};
  bool _bulkBusy = false;

  bool get _supportsSelection =>
      widget.allowBulkSaveDraft || widget.allowBulkPublish;

  List<String> get _selectableIds {
    return widget.items
        .map((item) => item.id)
        .whereType<String>()
        .where((id) => id.isNotEmpty && !widget.discardedPreviewIds.contains(id))
        .toList();
  }

  @override
  void didUpdateWidget(GeneratedCandidateGroupSection oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.items != widget.items) {
      _visibleCount = widget.initialVisibleCount;
      _selectedIds.removeWhere((id) => !_selectableIds.contains(id));
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.items.isEmpty) return const SizedBox.shrink();

    final visibleItems =
        _expanded ? widget.items.take(_visibleCount).toList() : const <CandidateSummary>[];
    final hasMore = _expanded && _visibleCount < widget.items.length;
    final selectable = _selectableIds;
    final selectedCount = _selectedIds.length;

    return KbAdminPanel(
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: EdgeInsets.zero,
          childrenPadding: const EdgeInsets.only(top: 8),
          initiallyExpanded: widget.expandedInitially,
          onExpansionChanged: (value) => setState(() => _expanded = value),
          title: Text(
            '${widget.title} (${widget.items.length})',
            style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: DesignTokens.ink,
            ),
          ),
          children: [
            if (_supportsSelection) ...[
              Wrap(
                spacing: 8,
                runSpacing: 8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text(
                    '$selectedCount selected',
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: DesignTokens.ink,
                    ),
                  ),
                  TextButton(
                    onPressed: selectable.isEmpty
                        ? null
                        : () => setState(() {
                              _selectedIds
                                ..clear()
                                ..addAll(selectable);
                            }),
                    child: const Text('Select All'),
                  ),
                  TextButton(
                    onPressed: selectedCount == 0
                        ? null
                        : () => setState(_selectedIds.clear),
                    child: const Text('Clear Selection'),
                  ),
                  if (widget.allowBulkSaveDraft &&
                      widget.bulkSaveAllLabel != null)
                    OutlinedButton(
                      onPressed: _bulkBusy
                          ? null
                          : () => _runBulk(
                                context,
                                items: widget.items,
                                publish: false,
                                confirmPublish: false,
                              ),
                      child: Text(widget.bulkSaveAllLabel!),
                    ),
                  if (widget.allowBulkPublish &&
                      widget.bulkPublishAllLabel != null)
                    ElevatedButton(
                      onPressed: _bulkBusy
                          ? null
                          : () => _runBulk(
                                context,
                                items: widget.items,
                                publish: true,
                                confirmPublish: true,
                                confirmMessage:
                                    widget.bulkPublishAllConfirmMessage,
                              ),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: DesignTokens.maroon,
                        foregroundColor: Colors.white,
                      ),
                      child: Text(widget.bulkPublishAllLabel!),
                    ),
                ],
              ),
              if (selectedCount > 0) ...[
                const SizedBox(height: 10),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: const Color(0xFFF8FAFC),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: DesignTokens.border),
                  ),
                  child: Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      Text(
                        '$selectedCount selected',
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      if (widget.allowBulkSaveDraft)
                        OutlinedButton(
                          onPressed: _bulkBusy
                              ? null
                              : () => _runBulk(
                                    context,
                                    items: _selectedItems(),
                                    publish: false,
                                    confirmPublish: false,
                                  ),
                          child: const Text('Save Selected as Draft'),
                        ),
                      if (widget.allowBulkPublish)
                        ElevatedButton(
                          onPressed: _bulkBusy
                              ? null
                              : () => _runBulk(
                                    context,
                                    items: _selectedItems(),
                                    publish: true,
                                    confirmPublish: true,
                                  ),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: DesignTokens.maroon,
                            foregroundColor: Colors.white,
                          ),
                          child: const Text('Publish Selected'),
                        ),
                      TextButton(
                        onPressed: _bulkBusy
                            ? null
                            : () => setState(_selectedIds.clear),
                        child: const Text('Clear Selection'),
                      ),
                    ],
                  ),
                ),
              ],
              const SizedBox(height: 12),
            ],
            ...visibleItems.map((item) => _buildCandidateItem(context, item)),
            if (hasMore)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton(
                  onPressed: () => setState(
                    () => _visibleCount += widget.pageSize,
                  ),
                  child: Text(
                    'Load more (${widget.items.length - _visibleCount} remaining)',
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  List<CandidateSummary> _selectedItems() {
    return widget.items
        .where((item) => item.id != null && _selectedIds.contains(item.id))
        .toList();
  }

  Widget _buildCandidateItem(BuildContext context, CandidateSummary item) {
    final previewId = item.id;
    if (previewId == null || previewId.isEmpty) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: KbAdminPanel(child: _CandidateSummaryRow(item: item)),
      );
    }
    if (widget.discardedPreviewIds.contains(previewId)) {
      return const SizedBox.shrink();
    }

    final saved = widget.savedArticlesByPreviewId[previewId];
    final matchedPublished = item.matchedExistingPublished;
    final existingId = item.existingArticleId;
    final isPreview = !matchedPublished &&
        saved == null &&
        (item.isUnsavedPreview || isPreviewCandidateId(previewId));
    var article = saved ??
        widget.previewArticlesById[previewId] ??
        item.toPreviewArticle();
    if (matchedPublished && existingId != null && existingId.isNotEmpty) {
      article = AdminArticle(
        id: existingId,
        title: article.title,
        category: article.category,
        published: true,
        summary: article.summary,
        content: article.content,
        office: article.office,
        sourceFilename: article.sourceFilename,
        metadata: {
          ...article.metadata,
          'existing_article_id': existingId,
          'already_published': true,
        },
        displayContent: article.displayContent,
      );
    }
    final alreadyPublished = matchedPublished || (!isPreview && article.published);
    final showCheckbox = _supportsSelection && !alreadyPublished;
    final bucketLabel = bucketLabelForExport(
      item.finalBucket ?? item.plannerBucket ?? widget.bucketKey,
      fallback: widget.title,
    );
    final publishBlocked = shouldBlockCharterPublish(
      title: article.title,
      reviewReasons: [
        ...article.reviewReasons,
        ...item.reviewReasons,
      ],
      sourceSection: article.sourceSection ?? item.sourceSection,
      plannerBucket: item.plannerBucket ?? widget.bucketKey,
      finalBucket: item.finalBucket,
    );
    final resolvedBucket =
        (item.finalBucket ?? item.plannerBucket ?? widget.bucketKey).toLowerCase();
    final canPublishByBucket = item.publishAllowed ??
        (resolvedBucket == 'recommended' || resolvedBucket == 'consolidated_parent');
    final canSaveByBucket = item.saveDraftAllowed ??
        (resolvedBucket == 'recommended' ||
            resolvedBucket == 'consolidated_parent' ||
            resolvedBucket == 'needs_review' ||
            resolvedBucket == 'low_quality');
    final sectionAllowsPublish = widget.allowPublish && canPublishByBucket && !publishBlocked;
    final sectionAllowsSave = widget.allowSaveDraft && canSaveByBucket;

    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: AdminArticleCard(
        article: article,
        lightweight: true,
        isUnsavedPreview: isPreview && !matchedPublished,
        alreadyPublishedLabel: matchedPublished,
        showCheckbox: showCheckbox && !publishBlocked,
        selected: _selectedIds.contains(previewId),
        onSelectedChanged: showCheckbox && !publishBlocked
            ? (value) {
                setState(() {
                  if (value) {
                    _selectedIds.add(previewId);
                  } else {
                    _selectedIds.remove(previewId);
                  }
                });
              }
            : null,
        onView: () => showAdminArticleViewDialog(
          context,
          article,
          widget.service,
          fallbackSourceFilename: widget.fallbackSourceFilename,
        ),
        onEdit: () => _editArticle(context, previewId, article, isPreview: isPreview),
        onSaveDraft: isPreview && sectionAllowsSave
            ? () => _savePreview(
                  context,
                  previewId,
                  widget.allowEditAsReviewDraft
                      ? stampManualReviewFromLowQuality(article)
                      : article,
                  publish: false,
                )
            : null,
        onPublish: sectionAllowsPublish && !matchedPublished
            ? (isPreview
                ? () => _savePreview(context, previewId, article, publish: true)
                : () => _publishArticle(context, previewId, article))
            : null,
        onUpdateExisting: matchedPublished && existingId != null
            ? () => _savePreview(
                  context,
                  previewId,
                  article,
                  publish: true,
                  updateExistingId: existingId,
                )
            : null,
        onUnpublish: alreadyPublished && !isPreviewCandidateId(article.id)
            ? () => _unpublishArticle(context, previewId, article)
            : null,
        onDelete: !isPreview && !matchedPublished
            ? () => _deleteArticle(context, article)
            : null,
        onDiscard: isPreview && !matchedPublished
            ? () => widget.onDiscardPreview(previewId)
            : null,
        onDownloadTxt: () => downloadArticlePreviewTxt(
          article: article,
          bucketLabel: bucketLabel,
          candidate: item,
          fallbackSourceFilename: widget.fallbackSourceFilename,
        ),
        allowPublish: sectionAllowsPublish && !matchedPublished,
        allowSaveDraft: sectionAllowsSave && !matchedPublished,
        showReviewBeforePublishBadge: widget.showReviewBeforePublishBadge,
        showLowQualityBadges: widget.showLowQualityBadges,
        allowEditAsReviewDraft: widget.allowEditAsReviewDraft,
        lowQualityHelperText: widget.lowQualityHelperText,
      ),
    );
  }

  Map<String, dynamic> _bulkPayloadFor(
    CandidateSummary item,
    AdminArticle article, {
    required bool isPreview,
  }) {
    final previewId = item.id ?? '';
    final payload = article.toCreatePayload(publish: false);
    payload['preview_id'] = previewId;
    payload['planner_bucket'] = item.plannerBucket ?? widget.bucketKey;
    payload['needs_review'] = item.needsReview || article.needsReview;
    if (!isPreview &&
        article.id.trim().isNotEmpty &&
        !isPreviewCandidateId(article.id)) {
      payload['existing_article_id'] = article.id;
    }
    return payload;
  }

  Future<void> _runBulk(
    BuildContext context, {
    required List<CandidateSummary> items,
    required bool publish,
    required bool confirmPublish,
    String? confirmMessage,
  }) async {
    final actionable = <Map<String, dynamic>>[];
    final previewIds = <String>[];

    for (final item in items) {
      final previewId = item.id;
      if (previewId == null || previewId.isEmpty) continue;
      if (widget.discardedPreviewIds.contains(previewId)) continue;
      if (item.matchedExistingPublished && publish) {
        continue;
      }
      final saved = widget.savedArticlesByPreviewId[previewId];
      final isPreview =
          saved == null && (item.isUnsavedPreview || isPreviewCandidateId(previewId));
      final article = saved ??
          widget.previewArticlesById[previewId] ??
          item.toPreviewArticle();
      if (!isPreview && article.published && publish) {
        continue;
      }
      // Never unpublish via Save as Draft — keep public articles public.
      if (!isPreview && article.published && !publish) {
        continue;
      }
      if (publish && !widget.allowBulkPublish) continue;
      if (!publish && !widget.allowBulkSaveDraft) continue;
      if (shouldBlockCharterPublish(
        title: article.title,
        reviewReasons: [
          ...article.reviewReasons,
          ...item.reviewReasons,
        ],
        sourceSection: article.sourceSection ?? item.sourceSection,
        plannerBucket: item.plannerBucket ?? widget.bucketKey,
      )) {
        continue;
      }
      if (!isPreview && !publish && !article.published) {
        // Already a draft — skip create.
        continue;
      }
      actionable.add(
        _bulkPayloadFor(item, article, isPreview: isPreview),
      );
      previewIds.add(previewId);
    }

    if (actionable.isEmpty) {
      showKbSnackBar(
        context,
        publish
            ? 'No eligible articles to publish.'
            : 'No eligible articles to save as draft.',
      );
      return;
    }

    if (confirmPublish) {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Publish selected articles?'),
          content: Text(
            confirmMessage ??
                'You are about to publish ${actionable.length} articles to the public Knowledge Base. Published articles will be visible to students. Continue?',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Cancel'),
            ),
            ElevatedButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              style: ElevatedButton.styleFrom(
                backgroundColor: DesignTokens.maroon,
                foregroundColor: Colors.white,
              ),
              child: const Text('Publish'),
            ),
          ],
        ),
      );
      if (confirmed != true || !context.mounted) return;
    }

    setState(() => _bulkBusy = true);
    try {
      final result = publish
          ? await widget.service.bulkPublish(actionable)
          : await widget.service.bulkSaveDraft(actionable);
      if (!context.mounted) return;

      for (final item in result.results) {
        if (!item.success || item.id == null || item.id!.isEmpty) continue;
        final previewId = item.previewId;
        if (previewId == null || previewId.isEmpty) continue;
        try {
          final saved = await widget.service.getArticle(item.id!);
          widget.onPreviewSaved(previewId, saved);
        } catch (_) {
          widget.onPreviewSaved(
            previewId,
            AdminArticle(
              id: item.id!,
              title: item.title ?? 'Untitled Article',
              category: 'General Information',
              published: item.published ?? publish,
            ),
          );
        }
      }

      setState(() {
        _selectedIds.removeAll(previewIds);
      });
      await widget.onArticlesChanged();
      if (!context.mounted) return;

      final verb = publish
          ? '${result.successCount} articles published to the Knowledge Base.'
          : '${result.successCount} articles saved as drafts.';
      final failureNote = result.failureCount > 0
          ? ' ${result.failureCount} skipped or failed.'
          : '';
      showKbSnackBar(context, '$verb$failureNote');
    } catch (error) {
      if (!context.mounted) return;
      showKbSnackBar(context, error.toString());
    } finally {
      if (mounted) setState(() => _bulkBusy = false);
    }
  }

  Future<void> _editArticle(
    BuildContext context,
    String previewId,
    AdminArticle article, {
    required bool isPreview,
  }) async {
    final result = await showAdminArticleEditDialog(
      context: context,
      article: article,
      service: widget.service,
      isPreview: isPreview,
      asReviewDraft: widget.allowEditAsReviewDraft,
    );
    if (!context.mounted) return;
    if (result is AdminArticle) {
      final stamped = widget.allowEditAsReviewDraft &&
              result.metadata['manual_review_from_low_quality'] != true
          ? stampManualReviewFromLowQuality(result)
          : result;
      widget.onPreviewUpdated(previewId, stamped);
      showKbSnackBar(
        context,
        widget.allowEditAsReviewDraft
            ? 'Review draft updated. Use Save as Draft to store it for publishing from Drafts.'
            : 'Preview updated.',
      );
      return;
    }
    if (result == true) {
      try {
        final updated = await widget.service.getArticle(article.id);
        if (!context.mounted) return;
        widget.onPreviewSaved(previewId, updated);
      } catch (_) {}
      showKbSnackBar(context, 'Article updated.');
      await widget.onArticlesChanged();
    }
  }

  Future<void> _savePreview(
    BuildContext context,
    String previewId,
    AdminArticle article, {
    required bool publish,
    String? updateExistingId,
  }) async {
    try {
      final saved = await widget.service.createArticle(
        article.toCreatePayload(publish: publish),
        updateExistingId: updateExistingId,
      );
      if (!context.mounted) return;
      widget.onPreviewSaved(previewId, saved);
      showKbSnackBar(
        context,
        updateExistingId != null
            ? 'Updated existing "${saved.title}" (published=${saved.published}).'
            : publish
                ? 'Published "${saved.title}" to published_articles (id=${saved.id}, published=${saved.published}).'
                : 'Saved "${saved.title}" as draft (published=${saved.published}).',
      );
      await widget.onArticlesChanged();
    } on AdminArticleRequestException catch (error) {
      if (!context.mounted) return;
      if (!error.isSimilarArticleConflict) {
        showKbSnackBar(context, error.toString());
        return;
      }
      final choice = await _showSimilarArticleDialog(context, error);
      if (!context.mounted || choice == null) return;
      final existingId = error.existingArticle?['id']?.toString();
      try {
        final saved = await widget.service.createArticle(
          article.toCreatePayload(publish: publish),
          updateExistingId:
              choice == _SimilarArticleChoice.updateExisting ? existingId : null,
          forceCreate: choice == _SimilarArticleChoice.createNew,
        );
        if (!context.mounted) return;
        widget.onPreviewSaved(previewId, saved);
        showKbSnackBar(
          context,
          publish ? 'Published "${saved.title}".' : 'Saved "${saved.title}" as draft.',
        );
        await widget.onArticlesChanged();
      } catch (retryError) {
        if (!context.mounted) return;
        showKbSnackBar(context, retryError.toString());
      }
    } catch (error) {
      if (!context.mounted) return;
      showKbSnackBar(context, error.toString());
    }
  }

  Future<void> _publishArticle(
    BuildContext context,
    String previewId,
    AdminArticle article,
  ) async {
    try {
      await widget.service.publishArticle(article.id);
      final updated = await widget.service.getArticle(article.id);
      if (!context.mounted) return;
      widget.onPreviewSaved(previewId, updated);
      showKbSnackBar(context, 'Published "${article.title}".');
      await widget.onArticlesChanged();
    } catch (error) {
      if (!context.mounted) return;
      showKbSnackBar(context, error.toString());
    }
  }

  Future<void> _unpublishArticle(
    BuildContext context,
    String previewId,
    AdminArticle article,
  ) async {
    try {
      await widget.service.unpublishArticle(article.id);
      final updated = await widget.service.getArticle(article.id);
      if (!context.mounted) return;
      widget.onPreviewSaved(previewId, updated);
      showKbSnackBar(context, 'Unpublished "${article.title}".');
      await widget.onArticlesChanged();
    } catch (error) {
      if (!context.mounted) return;
      showKbSnackBar(context, error.toString());
    }
  }

  Future<void> _deleteArticle(BuildContext context, AdminArticle article) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete article?'),
        content: Text('Delete "${article.title}" permanently?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text('Delete', style: TextStyle(color: Colors.red.shade700)),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await widget.service.deleteArticle(article.id);
      if (!context.mounted) return;
      showKbSnackBar(context, 'Deleted "${article.title}".');
      await widget.onArticlesChanged();
    } catch (error) {
      if (!context.mounted) return;
      showKbSnackBar(context, error.toString());
    }
  }
}

enum _SimilarArticleChoice { updateExisting, createNew }

Future<_SimilarArticleChoice?> _showSimilarArticleDialog(
  BuildContext context,
  AdminArticleRequestException error,
) {
  final existing = error.existingArticle;
  final existingTitle = existing?['title']?.toString() ?? 'existing article';
  return showDialog<_SimilarArticleChoice>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('Similar article found'),
      content: Text(
        'A similar article already exists ("$existingTitle"). '
        'Do you want to update the existing draft or create a new one?',
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        TextButton(
          onPressed: () => Navigator.pop(context, _SimilarArticleChoice.createNew),
          child: const Text('Create New'),
        ),
        ElevatedButton(
          onPressed: () => Navigator.pop(context, _SimilarArticleChoice.updateExisting),
          style: ElevatedButton.styleFrom(
            backgroundColor: DesignTokens.maroon,
            foregroundColor: Colors.white,
          ),
          child: const Text('Update Existing'),
        ),
      ],
    ),
  );
}

class _CandidateSummaryRow extends StatelessWidget {
  const _CandidateSummaryRow({required this.item});

  final CandidateSummary item;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                item.title,
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 4),
              Text(
                [
                  if (item.category != null) 'Category: ${item.category}',
                  if (item.articleType != null || item.documentType != null)
                    'Type: ${item.articleType ?? item.documentType}',
                  if (item.mergedUnitCount != null && item.mergedUnitCount! > 1)
                    'Merged units: ${item.mergedUnitCount}',
                  if (item.plannerBucket != null) 'Bucket: ${item.plannerBucket}',
                  if (item.sourceSection != null) 'Section: ${item.sourceSection}',
                  'Quality: ${formatScore(item.qualityScore)}',
                  'Confidence: ${formatScore(item.categoryConfidence)}',
                  'Usefulness: ${formatScore(item.studentUsefulnessScore)}',
                ].join(' • '),
                style: const TextStyle(fontSize: 12, color: DesignTokens.muted),
              ),
              if (item.reviewReasons.isNotEmpty || item.displayReviewReasons.isNotEmpty)
                Text(
                  'Why not recommended: ${item.displayReviewReasons.join('; ')}',
                  style: const TextStyle(fontSize: 12, color: Color(0xFFB45309)),
                ),
              if (item.repairActionsApplied.isNotEmpty)
                Text(
                  'Repair attempted: ${item.repairActionsApplied.join(', ')}',
                  style: const TextStyle(fontSize: 11, color: DesignTokens.muted),
                ),
            ],
          ),
        ),
      ],
    );
  }
}
