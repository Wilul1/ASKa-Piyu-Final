import 'package:flutter/material.dart';

import '../design_tokens.dart';
import '../models/article_media_models.dart';
import '../services/file_pick.dart';
import 'article_file_drop.dart';

class ArticleAttachmentsPanel extends StatefulWidget {
  const ArticleAttachmentsPanel({
    super.key,
    required this.attachments,
    required this.uploading,
    this.enabled = true,
    this.error,
    this.onPick,
    this.onDropped,
    this.onRemove,
    this.debugPickFiles,
    this.showTitle = true,
  });

  final List<ArticleMediaItem> attachments;
  final Set<String> uploading;
  final bool enabled;
  final String? error;
  final Future<void> Function(List<PickedAppFile> files)? onPick;
  final ValueChanged<List<PickedAppFile>>? onDropped;
  final Future<void> Function(ArticleMediaItem item)? onRemove;
  final Future<List<PickedAppFile>> Function()? debugPickFiles;
  final bool showTitle;

  @override
  State<ArticleAttachmentsPanel> createState() => _ArticleAttachmentsPanelState();
}

class _ArticleAttachmentsPanelState extends State<ArticleAttachmentsPanel> {
  bool _hovering = false;

  Future<void> _pick() async {
    if (!widget.enabled || widget.onPick == null) return;
    final files = widget.debugPickFiles != null
        ? await widget.debugPickFiles!()
        : await pickAppFiles(
            allowedExtensions: articleAttachmentExtensions,
            dialogTitle: 'Upload attachments',
          );
    if (files.isEmpty) return;
    await widget.onPick!(files);
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (widget.showTitle) ...[
          const Text(
            'Attachments (optional)',
            style: TextStyle(
              color: DesignTokens.ink,
              fontSize: 16,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 4),
          const Text(
            'Upload images or PDFs to support your article. Maximum 10 MB per file. Allowed: JPG, PNG, WebP, GIF, or PDF.',
            style: TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              fontWeight: FontWeight.w600,
              height: 1.35,
            ),
          ),
          const SizedBox(height: 12),
        ],
        ArticleFileDropHost(
          enabled: widget.enabled,
          onHoverChanged: (value) => setState(() => _hovering = value),
          onDropped: (files) {
            if (widget.onDropped != null) {
              widget.onDropped!(files);
            } else {
              widget.onPick?.call(files);
            }
          },
          child: Material(
            color: _hovering ? const Color(0xFFF8FAFC) : Colors.white,
            child: InkWell(
              key: const Key('knowledge-article-attachments-dropzone'),
              onTap: widget.enabled ? _pick : null,
              borderRadius: BorderRadius.circular(10),
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.fromLTRB(16, 22, 16, 22),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(
                    color: _hovering ? DesignTokens.maroon : DesignTokens.border,
                    style: BorderStyle.solid,
                  ),
                ),
                child: Column(
                  children: [
                    Icon(
                      Icons.cloud_upload_outlined,
                      color: DesignTokens.maroon.withValues(alpha: 0.9),
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      'Drag and drop files here, or click to upload.',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 13,
                        color: DesignTokens.ink,
                      ),
                    ),
                    const SizedBox(height: 4),
                    const Text(
                      'JPG, PNG, WebP, GIF, or PDF · 10 MB max',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: DesignTokens.muted,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
        if (widget.error != null) ...[
          const SizedBox(height: 8),
          Text(
            widget.error!,
            key: const Key('knowledge-article-attachments-error'),
            style: const TextStyle(
              color: Color(0xFFB91C1C),
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
        if (widget.attachments.isNotEmpty) ...[
          const SizedBox(height: 12),
          for (final item in widget.attachments)
            _AttachmentRow(
              item: item,
              uploading: widget.uploading.contains(item.id),
              onRemove: widget.enabled && widget.onRemove != null
                  ? () => widget.onRemove!(item)
                  : null,
            ),
        ],
      ],
    );
  }
}

class _AttachmentRow extends StatelessWidget {
  const _AttachmentRow({
    required this.item,
    required this.uploading,
    this.onRemove,
  });

  final ArticleMediaItem item;
  final bool uploading;
  final VoidCallback? onRemove;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: Key('knowledge-article-attachment-${item.id}'),
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.fromLTRB(10, 8, 6, 8),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Row(
        children: [
          Icon(
            item.isPdf ? Icons.picture_as_pdf_outlined : Icons.insert_drive_file_outlined,
            size: 18,
            color: DesignTokens.maroon,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  item.originalFilename,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                  ),
                ),
                Text(
                  _sizeLabel(item.sizeBytes),
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
          if (uploading)
            const SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          else if (onRemove != null)
            IconButton(
              key: Key('knowledge-article-attachment-remove-${item.id}'),
              tooltip: 'Remove',
              icon: const Icon(Icons.close, size: 18),
              onPressed: onRemove,
            ),
        ],
      ),
    );
  }
}

String _sizeLabel(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) {
    return '${(bytes / 1024).toStringAsFixed(1)} KB';
  }
  return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
}
