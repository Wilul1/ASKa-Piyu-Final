import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../design_tokens.dart';
import '../services/download_file.dart';
import '../widgets/admin_action_buttons.dart';
import 'admin_kb_outline.dart';

export 'admin_kb_outline.dart';

void _downloadExtractionTxt(String text, String? fileName, {String suffix = 'extraction'}) {
  final stem = (fileName == null || fileName.trim().isEmpty)
      ? 'extraction-result'
      : fileName.trim().replaceAll(RegExp(r'\.[^.]+$'), '');
  final safeStem = stem.replaceAll(RegExp(r'[^\w\-]+'), '_');
  final safeSuffix = suffix.trim().isEmpty ? 'extraction' : suffix.trim();
  downloadTextFile(
    filename: '$safeStem-$safeSuffix.txt',
    text: text,
    mimeType: 'text/plain',
  );
}

String _extractionDownloadText({
  required String reviewText,
  required List<Map<String, dynamic>> knowledgeUnits,
  String? fileName,
}) {
  final unitsTxt = buildKnowledgeUnitsExtractionTxt(
    knowledgeUnits: knowledgeUnits,
    sourceFilename: fileName,
  );
  if (unitsTxt.isNotEmpty) return unitsTxt;
  return buildFullExtractionText(
    reviewText: reviewText,
    knowledgeUnits: knowledgeUnits,
  );
}

/// Extraction-focused Knowledge Base Admin workspace.
class AdminKbWorkspace extends StatelessWidget {
  const AdminKbWorkspace({
    super.key,
    required this.fileName,
    required this.fileSizeBytes,
    required this.isBusy,
    required this.status,
    required this.pipelineStages,
    required this.knowledgeUnits,
    required this.validationReport,
    required this.kbStatistics,
    required this.reviewText,
    required this.rawOcrText,
    required this.documentType,
    required this.classificationReason,
    required this.publishedCount,
    required this.draftCount,
    required this.candidateHintCount,
    required this.selectedOutlineIndex,
    required this.onPickFile,
    required this.onExtract,
    required this.onIngest,
    required this.onSelectOutline,
  });

  final String? fileName;
  final int? fileSizeBytes;
  final bool isBusy;
  final String status;
  final List<AdminPipelineStageView> pipelineStages;
  final List<Map<String, dynamic>> knowledgeUnits;
  final Map<String, dynamic>? validationReport;
  final Map<String, dynamic>? kbStatistics;
  final String reviewText;
  final String? rawOcrText;
  final String? documentType;
  final String? classificationReason;
  final int? publishedCount;
  final int? draftCount;
  final int? candidateHintCount;
  final int selectedOutlineIndex;
  final VoidCallback onPickFile;
  final VoidCallback onExtract;
  final VoidCallback onIngest;
  final ValueChanged<int> onSelectOutline;

  bool get _hasExtractionResult {
    final extractionText = buildFullExtractionText(
      reviewText: reviewText,
      knowledgeUnits: knowledgeUnits,
    );
    return extractionText.trim().isNotEmpty;
  }

  @override
  Widget build(BuildContext context) {
    final cleanDocumentType = formatDocumentTypeLabel(documentType);
    final extractionText = buildFullExtractionText(
      reviewText: reviewText,
      knowledgeUnits: knowledgeUnits,
    );
    final downloadText = _extractionDownloadText(
      reviewText: reviewText,
      knowledgeUnits: knowledgeUnits,
      fileName: fileName,
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _WorkspaceHeader(),
        const SizedBox(height: 16),
        _ActiveDocumentCard(
          fileName: fileName,
          fileSizeBytes: fileSizeBytes,
          pageCount: _pageCount(validationReport, knowledgeUnits),
          documentType: cleanDocumentType,
          isBusy: isBusy,
          onPickFile: onPickFile,
          onExtract: onExtract,
          onIngest: onIngest,
        ),
        const SizedBox(height: 14),
        _ProcessingStatusRow(stages: pipelineStages),
        if (status.trim().isNotEmpty) ...[
          const SizedBox(height: 10),
          Text(
            status,
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: isBusy ? DesignTokens.maroon : DesignTokens.muted,
              height: 1.35,
            ),
          ),
        ],
        const SizedBox(height: 14),
        if (knowledgeUnits.isNotEmpty || _hasExtractionResult)
          _ValidationSummaryRow(
            knowledgeUnitCount: knowledgeUnits.length,
            validationReport: validationReport,
          ),
        if (knowledgeUnits.isNotEmpty || _hasExtractionResult)
          const SizedBox(height: 10),
        _FullExtractionPanel(
          text: extractionText,
          downloadText: downloadText,
          fileName: fileName,
          unitCount: knowledgeUnits.length,
          collapsible: _hasExtractionResult,
          initiallyExpanded: !_hasExtractionResult,
        ),
      ],
    );
  }
}

class AdminPipelineStageView {
  const AdminPipelineStageView({
    required this.label,
    required this.status,
    this.detail,
  });

  final String label;
  final String status;
  final String? detail;
}

int? _pageCount(
  Map<String, dynamic>? validationReport,
  List<Map<String, dynamic>> units,
) {
  final fromReport = _asInt(
    validationReport?['page_count'] ??
        validationReport?['total_pages'] ??
        validationReport?['pages'],
  );
  if (fromReport != null && fromReport > 0) return fromReport;
  var maxPage = 0;
  for (final unit in units) {
    final page = _asInt(unit['page_end'] ?? unit['page_start'] ?? unit['page']);
    if (page != null && page > maxPage) maxPage = page;
  }
  return maxPage > 0 ? maxPage : null;
}

int? _asInt(Object? value) {
  if (value is int) return value;
  return int.tryParse((value ?? '').toString());
}

class _WorkspaceHeader extends StatelessWidget {
  const _WorkspaceHeader();

  @override
  Widget build(BuildContext context) {
    return const Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Extract & Index',
          style: TextStyle(
            fontSize: 22,
            fontWeight: FontWeight.w800,
            color: DesignTokens.ink,
          ),
        ),
        SizedBox(height: 6),
        Text(
          'Upload a document, extract content for Ask ASKa-Piyu, and index it for chatbot retrieval.',
          style: TextStyle(
            fontSize: 14,
            height: 1.45,
            color: DesignTokens.muted,
          ),
        ),
      ],
    );
  }
}

class _ActiveDocumentCard extends StatelessWidget {
  const _ActiveDocumentCard({
    required this.fileName,
    required this.fileSizeBytes,
    required this.pageCount,
    required this.documentType,
    required this.isBusy,
    required this.onPickFile,
    required this.onExtract,
    required this.onIngest,
  });

  final String? fileName;
  final int? fileSizeBytes;
  final int? pageCount;
  final String? documentType;
  final bool isBusy;
  final VoidCallback onPickFile;
  final VoidCallback onExtract;
  final VoidCallback onIngest;

  @override
  Widget build(BuildContext context) {
    final name =
        fileName?.trim().isNotEmpty == true ? fileName! : 'Choose a PDF or image';
    final ext = name.contains('.') ? name.split('.').last.toUpperCase() : 'FILE';
    return _SoftCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          LayoutBuilder(
            builder: (context, constraints) {
              final stacked = constraints.maxWidth < 760;
              final meta = Expanded(
                child: InkWell(
                  onTap: isBusy ? null : onPickFile,
                  borderRadius: BorderRadius.circular(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Active Document',
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          color: DesignTokens.maroon,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        name,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                          color: DesignTokens.ink,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        [
                          ext,
                          if (fileSizeBytes != null)
                            _formatBytes(fileSizeBytes!),
                          if (pageCount != null) '$pageCount pages',
                          if (documentType != null &&
                              documentType!.trim().isNotEmpty)
                            documentType!,
                        ].join(' · '),
                        style: const TextStyle(
                          fontSize: 12,
                          color: DesignTokens.muted,
                        ),
                      ),
                    ],
                  ),
                ),
              );
              final actions = Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  AdminSecondaryButton(
                    label: 'Extract & Structure',
                    minWidth: 168,
                    onPressed: isBusy ? null : onExtract,
                  ),
                  AdminPrimaryButton(
                    label: 'Index for Chatbot Retrieval',
                    minWidth: 220,
                    onPressed: isBusy ? null : onIngest,
                  ),
                ],
              );
              if (stacked) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(children: [meta]),
                    const SizedBox(height: 14),
                    actions,
                  ],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  meta,
                  const SizedBox(width: 16),
                  actions,
                ],
              );
            },
          ),
          const SizedBox(height: 12),
          const Text(
            'Indexing stores extracted knowledge units in ChromaDB for Ask ASKa-Piyu retrieval and citation grounding. It does not publish public articles.',
            style: TextStyle(
              fontSize: 12,
              height: 1.45,
              color: DesignTokens.muted,
            ),
          ),
        ],
      ),
    );
  }
}

class _ProcessingStatusRow extends StatelessWidget {
  const _ProcessingStatusRow({required this.stages});

  final List<AdminPipelineStageView> stages;

  @override
  Widget build(BuildContext context) {
    final items = stages.isEmpty
        ? const [
            AdminPipelineStageView(label: 'OCR/PDF extraction', status: 'waiting'),
            AdminPipelineStageView(label: 'Automatic cleaning', status: 'waiting'),
            AdminPipelineStageView(label: 'LLM structuring', status: 'waiting'),
            AdminPipelineStageView(label: 'Admin review/edit', status: 'waiting'),
            AdminPipelineStageView(label: 'Index to ChromaDB', status: 'waiting'),
          ]
        : stages;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Processing Status',
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w800,
            color: DesignTokens.maroon,
          ),
        ),
        const SizedBox(height: 8),
        LayoutBuilder(
          builder: (context, constraints) {
            final count = items.length;
            final gap = 10.0;
            final minCardWidth = constraints.maxWidth < 720
                ? constraints.maxWidth
                : math.max(150.0, (constraints.maxWidth - gap * (count - 1)) / count);
            return Wrap(
              spacing: gap,
              runSpacing: gap,
              children: [
                for (final stage in items)
                  SizedBox(
                    width: minCardWidth,
                    child: _ProcessingStageCard(stage: stage),
                  ),
              ],
            );
          },
        ),
      ],
    );
  }
}

class _ProcessingStageCard extends StatelessWidget {
  const _ProcessingStageCard({required this.stage});

  final AdminPipelineStageView stage;

  Color get _tone {
    switch (stage.status.toLowerCase()) {
      case 'done':
      case 'completed':
      case 'success':
        return const Color(0xFF2C9C5B);
      case 'error':
      case 'failed':
        return const Color(0xFFB42318);
      case 'running':
      case 'active':
      case 'in_progress':
      case 'needs review':
      case 'needs_review':
        return const Color(0xFFD97706);
      default:
        return DesignTokens.muted;
    }
  }

  String get _statusLabel {
    final raw = stage.status.trim();
    if (raw.isEmpty) return 'waiting';
    return raw.replaceAll('_', ' ').toLowerCase();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.03),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            stage.label,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w800,
              color: DesignTokens.ink,
              height: 1.3,
            ),
          ),
          const SizedBox(height: 8),
          if (stage.detail != null && stage.detail!.trim().isNotEmpty)
            Text(
              stage.detail!,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 11,
                height: 1.35,
                color: DesignTokens.muted,
              ),
            )
          else
            const Text(
              'Pipeline stage',
              style: TextStyle(
                fontSize: 11,
                height: 1.35,
                color: DesignTokens.muted,
              ),
            ),
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: _tone.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(999),
              border: Border.all(color: _tone.withValues(alpha: 0.2)),
            ),
            child: Text(
              _statusLabel,
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w700,
                color: _tone,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ValidationSummaryRow extends StatelessWidget {
  const _ValidationSummaryRow({
    required this.knowledgeUnitCount,
    required this.validationReport,
  });

  final int knowledgeUnitCount;
  final Map<String, dynamic>? validationReport;

  @override
  Widget build(BuildContext context) {
    final quality = (validationReport?['status'] ?? '—').toString().trim();
    final parts = <String>[
      if (quality.isNotEmpty && quality != '—') quality,
      if (knowledgeUnitCount > 0) '$knowledgeUnitCount units',
    ];
    if (parts.isEmpty) return const SizedBox.shrink();

    return Wrap(
      spacing: 8,
      runSpacing: 6,
      children: parts
          .map(
            (label) => Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
              decoration: BoxDecoration(
                color: const Color(0xFFF8FAFC),
                borderRadius: BorderRadius.circular(999),
                border: Border.all(color: DesignTokens.border),
              ),
              child: Text(
                label,
                style: const TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: DesignTokens.muted,
                ),
              ),
            ),
          )
          .toList(),
    );
  }
}

class _FullExtractionPanel extends StatefulWidget {
  const _FullExtractionPanel({
    required this.text,
    required this.downloadText,
    required this.fileName,
    required this.unitCount,
    this.collapsible = false,
    this.initiallyExpanded = true,
  });

  final String text;
  final String downloadText;
  final String? fileName;
  final int unitCount;
  final bool collapsible;
  final bool initiallyExpanded;

  @override
  State<_FullExtractionPanel> createState() => _FullExtractionPanelState();
}

class _FullExtractionPanelState extends State<_FullExtractionPanel> {
  late final ScrollController _scrollController;

  @override
  void initState() {
    super.initState();
    _scrollController = ScrollController();
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final viewportHeight = MediaQuery.sizeOf(context).height;
    final previewHeight = math.max(420.0, math.min(580.0, viewportHeight * 0.55));
    final body = _buildPreviewBody(context, previewHeight);

    if (!widget.collapsible) {
      return _SoftCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Full Extraction Result',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w800,
                color: DesignTokens.maroon,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              widget.unitCount > 0
                  ? 'Cleaned preview on screen. Download .txt exports all ${widget.unitCount} knowledge units in one file.'
                  : 'Cleaned document preview. Scroll inside this panel to review long extractions.',
              style: const TextStyle(
                fontSize: 13,
                height: 1.4,
                color: DesignTokens.muted,
              ),
            ),
            const SizedBox(height: 14),
            body,
          ],
        ),
      );
    }

    return _SoftCard(
      padding: const EdgeInsets.fromLTRB(18, 8, 18, 18),
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          initiallyExpanded: widget.initiallyExpanded,
          tilePadding: EdgeInsets.zero,
          childrenPadding: EdgeInsets.zero,
          title: const Text(
            'Full extraction preview',
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w800,
              color: DesignTokens.maroon,
            ),
          ),
          subtitle: Text(
            widget.unitCount > 0
                ? 'Collapsed by default. Download exports all ${widget.unitCount} knowledge units.'
                : 'Expand to review the cleaned extraction text.',
            style: const TextStyle(
              fontSize: 12,
              height: 1.35,
              color: DesignTokens.muted,
            ),
          ),
          children: [body],
        ),
      ),
    );
  }

  Widget _buildPreviewBody(BuildContext context, double previewHeight) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Align(
          alignment: Alignment.centerRight,
          child: Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              AdminSecondaryButton(
                label: 'Copy',
                minWidth: 88,
                onPressed: widget.text.isEmpty
                    ? null
                    : () async {
                        await Clipboard.setData(
                          ClipboardData(text: widget.text),
                        );
                        if (!context.mounted) return;
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('Extraction result copied'),
                            duration: Duration(seconds: 2),
                          ),
                        );
                      },
              ),
              AdminSecondaryButton(
                label: 'Download .txt',
                minWidth: 128,
                onPressed: widget.downloadText.isEmpty
                    ? null
                    : () {
                        _downloadExtractionTxt(
                          widget.downloadText,
                          widget.fileName,
                          suffix:
                              widget.unitCount > 0 ? 'units' : 'extraction',
                        );
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(
                            content: Text(
                              widget.unitCount > 0
                                  ? 'Downloaded all ${widget.unitCount} units as one .txt'
                                  : 'Extraction downloaded as .txt',
                            ),
                            duration: const Duration(seconds: 2),
                          ),
                        );
                      },
              ),
            ],
          ),
        ),
        const SizedBox(height: 14),
        SizedBox(
          height: previewHeight,
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: const Color(0xFFE5EAF1)),
            ),
            child: widget.text.isEmpty
                ? const Center(
                    child: Padding(
                      padding: EdgeInsets.symmetric(horizontal: 24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            'No extraction result yet.',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              color: DesignTokens.ink,
                              fontWeight: FontWeight.w700,
                              fontSize: 15,
                            ),
                          ),
                          SizedBox(height: 8),
                          Text(
                            'Upload or select a document, then click Extract & Structure.',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              color: DesignTokens.muted,
                              height: 1.5,
                              fontSize: 13,
                            ),
                          ),
                        ],
                      ),
                    ),
                  )
                : NotificationListener<ScrollNotification>(
                    onNotification: (_) => true,
                    child: Scrollbar(
                      controller: _scrollController,
                      thumbVisibility: true,
                      child: SingleChildScrollView(
                        controller: _scrollController,
                        primary: false,
                        physics: const ClampingScrollPhysics(),
                        padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
                        child: SelectableText(
                          widget.text,
                          style: const TextStyle(
                            fontFamily: 'monospace',
                            fontSize: 13.5,
                            height: 1.65,
                            color: DesignTokens.ink,
                          ),
                        ),
                      ),
                    ),
                  ),
          ),
        ),
      ],
    );
  }
}

/// Knowledge units grid for review inside Review & Publish.
class KbKnowledgeUnitsReviewPanel extends StatefulWidget {
  const KbKnowledgeUnitsReviewPanel({
    super.key,
    required this.knowledgeUnits,
    required this.fileName,
    this.borderless = false,
  });

  final List<Map<String, dynamic>> knowledgeUnits;
  final String? fileName;
  final bool borderless;

  @override
  State<KbKnowledgeUnitsReviewPanel> createState() =>
      _KbKnowledgeUnitsReviewPanelState();
}

class _KbKnowledgeUnitsReviewPanelState
    extends State<KbKnowledgeUnitsReviewPanel> {
  late final ScrollController _scrollController;

  @override
  void initState() {
    super.initState();
    _scrollController = ScrollController();
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final units = widget.knowledgeUnits;
    final listHeight = math.min(420.0, math.max(240.0, units.isEmpty ? 180.0 : 360.0));

    final content = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    widget.borderless
                        ? 'Step 1 — Knowledge units (${units.length})'
                        : 'Knowledge Units (${units.length})',
                    style: TextStyle(
                      fontSize: widget.borderless ? 14 : 16,
                      fontWeight: FontWeight.w800,
                      color: widget.borderless
                          ? DesignTokens.ink
                          : DesignTokens.maroon,
                    ),
                  ),
                  if (!widget.borderless) ...[
                    const SizedBox(height: 4),
                    const Text(
                      'Review extracted units used for chatbot indexing. Download exports every unit into one .txt.',
                      style: TextStyle(
                        fontSize: 12,
                        height: 1.4,
                        color: DesignTokens.muted,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(width: 10),
            AdminSecondaryButton(
              label: 'Download units .txt',
              minWidth: 148,
              onPressed: units.isEmpty
                  ? null
                  : () {
                      final text = buildKnowledgeUnitsExtractionTxt(
                        knowledgeUnits: units,
                        sourceFilename: widget.fileName,
                      );
                      _downloadExtractionTxt(
                        text,
                        widget.fileName,
                        suffix: 'units',
                      );
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          content: Text(
                            'Downloaded all ${units.length} units as one .txt',
                          ),
                          duration: const Duration(seconds: 2),
                        ),
                      );
                    },
            ),
          ],
        ),
        const SizedBox(height: 12),
        SizedBox(
          height: listHeight,
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: const Color(0xFFFBFCFD),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: DesignTokens.border),
            ),
            child: units.isEmpty
                ? const Center(
                    child: Padding(
                      padding: EdgeInsets.all(20),
                      child: Text(
                        'No knowledge units yet. Run Extract & Structure to populate this list.',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          color: DesignTokens.muted,
                          height: 1.45,
                        ),
                      ),
                    ),
                  )
                : NotificationListener<ScrollNotification>(
                    onNotification: (_) => true,
                    child: Scrollbar(
                      controller: _scrollController,
                      thumbVisibility: true,
                      child: LayoutBuilder(
                        builder: (context, constraints) {
                          final wide = constraints.maxWidth >= 900;
                          if (!wide) {
                            return ListView.separated(
                              controller: _scrollController,
                              primary: false,
                              physics: const ClampingScrollPhysics(),
                              padding: const EdgeInsets.all(10),
                              itemCount: units.length,
                              separatorBuilder: (_, __) =>
                                  const SizedBox(height: 8),
                              itemBuilder: (context, index) =>
                                  _KnowledgeUnitTile(unit: units[index]),
                            );
                          }
                          return GridView.builder(
                            controller: _scrollController,
                            primary: false,
                            physics: const ClampingScrollPhysics(),
                            padding: const EdgeInsets.all(10),
                            gridDelegate:
                                const SliverGridDelegateWithFixedCrossAxisCount(
                              crossAxisCount: 2,
                              mainAxisSpacing: 10,
                              crossAxisSpacing: 10,
                              childAspectRatio: 2.4,
                            ),
                            itemCount: units.length,
                            itemBuilder: (context, index) =>
                                _KnowledgeUnitTile(unit: units[index]),
                          );
                        },
                      ),
                    ),
                  ),
          ),
        ),
      ],
    );

    if (widget.borderless) return content;
    return _SoftCard(child: content);
  }
}

class _KnowledgeUnitTile extends StatelessWidget {
  const _KnowledgeUnitTile({required this.unit});

  final Map<String, dynamic> unit;

  @override
  Widget build(BuildContext context) {
    final title = (unit['title'] ?? 'Untitled').toString().trim();
    final path =
        (unit['hierarchy_path'] ?? unit['source_section'] ?? '').toString().trim();
    final status = (unit['status'] ?? 'OK').toString();
    final pageStart = unit['page_start'] ?? unit['page'];
    final pageEnd = unit['page_end'];
    final content = (unit['content'] ?? '').toString().trim();
    final snippet = content.length > 160
        ? '${content.substring(0, 160).trim()}…'
        : content;
    final pageLabel = pageStart == null
        ? null
        : pageEnd != null && pageEnd != pageStart
            ? 'Pages $pageStart–$pageEnd'
            : 'Page $pageStart';

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title.isEmpty ? 'Untitled' : title,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w800,
              color: DesignTokens.ink,
            ),
          ),
          if (path.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              path,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 11,
                color: DesignTokens.muted,
              ),
            ),
          ],
          const SizedBox(height: 6),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              _MetaChip(label: status),
              if (pageLabel != null) _MetaChip(label: pageLabel),
            ],
          ),
          if (snippet.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              snippet,
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 12,
                height: 1.4,
                color: DesignTokens.ink,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _MetaChip extends StatelessWidget {
  const _MetaChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: DesignTokens.maroon.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: DesignTokens.maroon.withValues(alpha: 0.18)),
      ),
      child: Text(
        label,
        style: const TextStyle(
          fontSize: 10,
          fontWeight: FontWeight.w700,
          color: DesignTokens.maroon,
        ),
      ),
    );
  }
}

class _SoftCard extends StatelessWidget {
  const _SoftCard({
    required this.child,
    this.padding = const EdgeInsets.all(18),
  });

  final Widget child;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: padding,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE8ECF2)),
        boxShadow: DesignTokens.softShadow(0.04),
      ),
      child: child,
    );
  }
}

String _formatBytes(int bytes) {
  if (bytes < 1024) return '$bytes B';
  final kb = bytes / 1024;
  if (kb < 1024) return '${kb.toStringAsFixed(kb >= 10 ? 0 : 1)} KB';
  final mb = kb / 1024;
  return '${mb.toStringAsFixed(mb >= 10 ? 0 : 1)} MB';
}
