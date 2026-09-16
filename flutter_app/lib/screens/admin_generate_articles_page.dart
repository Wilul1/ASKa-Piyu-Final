import 'dart:async';

import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../models/admin_article_models.dart';
import '../services/admin_article_service.dart';
import '../services/extraction_preview_store.dart';
import '../widgets/admin_kb_article_shared.dart';
import '../widgets/student_ui.dart';
import '../widgets/sidebar.dart';
import 'admin_kb_generate_articles_section.dart';
import 'admin_kb_outline.dart';
import 'admin_scaffold.dart';
import 'knowledge_articles_page.dart';
import 'office_scaffold.dart';

class AdminGenerateArticlesPage extends StatefulWidget {
  const AdminGenerateArticlesPage({
    super.key,
    this.focusArticleId,
    this.embedded = false,
    this.embeddedCompact = false,
    this.liveSessionContext,
    this.onLibraryRefresh,
    this.debugGenerationResult,
    this.debugArticleService,
  });

  /// When set, expands Article Library and highlights this article.
  final String? focusArticleId;

  /// When true, render body content only (used inside Knowledge Base tabs).
  final bool embedded;

  /// Slim generate UI inside Review & Publish (no duplicate metadata card).
  final bool embeddedCompact;

  /// Live extraction context from the KB session (filename, type, unit count).
  final KbSessionDisplayContext? liveSessionContext;

  /// Notifies parent after a candidate is saved.
  final VoidCallback? onLibraryRefresh;

  @visibleForTesting
  final CandidateGenerationResult? debugGenerationResult;

  @visibleForTesting
  final AdminArticleService? debugArticleService;

  @override
  State<AdminGenerateArticlesPage> createState() =>
      _AdminGenerateArticlesPageState();
}

class _AdminGenerateArticlesPageState extends State<AdminGenerateArticlesPage> {
  Map<String, dynamic>? _extractionPreview;
  String? _sourceFilename;
  String? _detectedDocumentType;
  String? _documentProfile;
  int _knowledgeUnitCount = 0;
  int _charterV2ServicesCount = 0;
  bool _hasCharterV2Services = false;
  String _extractionStatus =
      'No extracted document found. Please run Extract & Structure first.';

  bool _isGeneratingCandidates = false;
  CandidateGenerationResult? _candidateGenerationResult;
  final TextEditingController _recommendedPreviewLimitController =
      TextEditingController();

  final Map<String, AdminArticle> _previewArticlesById = {};
  final Map<String, AdminArticle> _savedArticlesByPreviewId = {};
  final Set<String> _discardedPreviewIds = {};

  @override
  void initState() {
    super.initState();
    _loadLastExtraction();
  }

  @override
  void dispose() {
    _recommendedPreviewLimitController.dispose();
    super.dispose();
  }

  void _loadLastExtraction() {
    if (widget.debugGenerationResult != null) {
      setState(() {
        _extractionPreview = const {
          'knowledge_units': [
            {'title': 'debug'},
          ],
        };
        _extractionStatus = 'Extraction preview is ready.';
        _candidateGenerationResult = widget.debugGenerationResult;
      });
      return;
    }
    final saved = AppConfig.lastExtractionPreview;
    if (!isValidExtractionHandoff(saved)) {
      setState(() {
        _extractionPreview = null;
        _sourceFilename = null;
        _detectedDocumentType = null;
        _documentProfile = null;
        _knowledgeUnitCount = 0;
        _charterV2ServicesCount = 0;
        _hasCharterV2Services = false;
        _extractionStatus =
            'No extracted document found. Please run Extract & Structure first.';
        _candidateGenerationResult = null;
        _previewArticlesById.clear();
        _savedArticlesByPreviewId.clear();
        _discardedPreviewIds.clear();
      });
      return;
    }

    final meta = Map<String, dynamic>.from(saved!);
    final previewRaw = meta['preview'];
    final preview = previewRaw is Map
        ? Map<String, dynamic>.from(
            previewRaw.map((key, value) => MapEntry(key.toString(), value)),
          )
        : null;
    final units = preview?['knowledge_units'];
    final unitCount = units is List
        ? units.length
        : (meta['knowledge_units_count'] as num?)?.toInt() ?? 0;
    final v2 = preview?['charter_v2_services'];
    final v2Count = v2 is List
        ? v2.length
        : (meta['charter_v2_services_count'] as num?)?.toInt() ?? 0;
    final debug = extractionHandoffDebugSummary(meta);
    // ignore: avoid_print
    print('Generate Articles loaded extraction handoff: $debug');

    setState(() {
      _extractionPreview = preview;
      _sourceFilename = meta['source_filename']?.toString();
      _detectedDocumentType = formatDocumentTypeLabel(
            meta['detected_document_type'] ?? meta['document_type'],
          ) ??
          meta['document_type']?.toString();
      _documentProfile = (meta['document_profile'] ??
              preview?['document_profile'] ??
              '')
          .toString();
      _knowledgeUnitCount = unitCount;
      _charterV2ServicesCount = v2Count;
      _hasCharterV2Services = v2Count > 0;
      _extractionStatus = meta['status']?.toString() ??
          'Extraction preview is ready.';
      _candidateGenerationResult = null;
      _previewArticlesById.clear();
      _savedArticlesByPreviewId.clear();
      _discardedPreviewIds.clear();
    });
  }

  bool get _hasExtractionPreview {
    final units = _extractionPreview?['knowledge_units'];
    final hasUnits = units is List && units.isNotEmpty;
    final v2 = _extractionPreview?['charter_v2_services'];
    final hasV2 = v2 is List && v2.isNotEmpty;
    final review = (_extractionPreview?['review_text'] ??
            _extractionPreview?['extracted_text'] ??
            '')
        .toString()
        .trim();
    return hasUnits || hasV2 || review.isNotEmpty;
  }

  AdminArticleService _articleService() {
    return widget.debugArticleService ??
        AdminArticleService(
          apiBase: AppConfig.resolvedApiBase,
          setAdminHeader: _setAdminHeader,
        );
  }

  void _setAdminHeader(Map<String, String> headers) {
    final auth = AuthScope.of(context);
    final token = auth.accessToken;
    final role = auth.role;
    if (role != 'admin' && role != 'office') {
      throw StateError('not_admin');
    }
    if (token == null || token.trim().isEmpty) {
      throw StateError('missing_admin_token');
    }
    headers['Authorization'] = 'Bearer $token';
  }

  int? _optionalRecommendedPreviewLimit() {
    final raw = _recommendedPreviewLimitController.text.trim();
    if (raw.isEmpty) return null;
    final parsed = int.tryParse(raw);
    if (parsed == null || parsed <= 0) return null;
    return parsed;
  }

  Future<void> _generateArticleCandidates() async {
    if (!_hasExtractionPreview) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'No extracted document selected. Run Extract & Structure from Documents first.',
          ),
        ),
      );
      return;
    }

    final preview = _extractionPreview;
    if (preview == null) return;

    setState(() {
      _isGeneratingCandidates = true;
      _candidateGenerationResult = null;
      _previewArticlesById.clear();
      _savedArticlesByPreviewId.clear();
      _discardedPreviewIds.clear();
    });

    try {
      final result = await _articleService().generateFromPreview(
        preview: preview,
        filename: _sourceFilename,
        maxCandidates: _optionalRecommendedPreviewLimit(),
      );
      if (!mounted) return;
      setState(() {
        _candidateGenerationResult = result;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'Generated ${result.previewCount > 0 ? result.previewCount : result.createdCount} unsaved candidate previews.',
          ),
        ),
      );
    } on AdminArticleRequestException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(friendlyKbError(error))),
      );
    } on TimeoutException {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Article generation timed out. Large handbooks can take a few minutes — please try again.',
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(friendlyKbError(error))),
      );
    } finally {
      if (mounted) {
        setState(() => _isGeneratingCandidates = false);
      }
    }
  }

  Future<void> _onGeneratedArticlesChanged() async {
    widget.onLibraryRefresh?.call();
  }

  void _onPreviewUpdated(String previewId, AdminArticle article) {
    setState(() {
      _previewArticlesById[previewId] = article;
    });
  }

  void _onPreviewSaved(String previewId, AdminArticle saved) {
    setState(() {
      _savedArticlesByPreviewId[previewId] = saved;
    });
  }

  void _onDiscardPreview(String previewId) {
    setState(() => _discardedPreviewIds.add(previewId));
  }

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    final isOffice = auth.role == 'office';
    final content = Column(
      key: const Key('admin-generate-articles'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _GenerateArticlesSourcePanel(
          sourceFilename: _sourceFilename,
          documentType: _detectedDocumentType,
          documentProfile: _documentProfile,
          knowledgeUnitCount: _knowledgeUnitCount,
          charterV2ServicesCount: _charterV2ServicesCount,
          hasCharterV2Services: _hasCharterV2Services,
          status: _extractionStatus,
          hasExtractionPreview: _hasExtractionPreview,
          hasCandidates: _candidateGenerationResult != null,
          recommendedPreviewLimitController: _recommendedPreviewLimitController,
          isBusy: _isGeneratingCandidates,
          onReload: _loadLastExtraction,
          onGenerate: _generateArticleCandidates,
          compact: widget.embeddedCompact,
          liveSessionContext: widget.liveSessionContext,
        ),
        if (_candidateGenerationResult != null) ...[
          SizedBox(height: widget.embeddedCompact ? 12 : 16),
          _GenerateArticlesSummary(generation: _candidateGenerationResult!),
          const SizedBox(height: 14),
          GenerateArticlesReviewSection(
            generationResult: _candidateGenerationResult!,
            previewArticlesById: _previewArticlesById,
            savedArticlesByPreviewId: _savedArticlesByPreviewId,
            discardedPreviewIds: _discardedPreviewIds,
            service: _articleService(),
            onArticlesChanged: _onGeneratedArticlesChanged,
            onPreviewUpdated: _onPreviewUpdated,
            onPreviewSaved: _onPreviewSaved,
            onDiscardPreview: _onDiscardPreview,
            fallbackSourceFilename: _sourceFilename,
            extractionPreview: _extractionPreview,
          ),
        ],
        const SizedBox(height: 16),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton(
            key: const Key('view-knowledge-articles'),
            onPressed: () {
              Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => KnowledgeArticlesPage(
                    focusArticleId: widget.focusArticleId,
                  ),
                ),
              );
            },
            child: const Text('View Knowledge Articles'),
          ),
        ),
      ],
    );

    const title = 'Generate Articles';
    const description =
        'Generate and review student-facing article candidates from extracted documents before saving or publishing.';

    if (widget.embedded) {
      return content;
    }

    if (isOffice) {
      // Legacy standalone route — keep working, but prefer Knowledge Base tabs.
      return OfficeScaffold(
        current: StudentNavItem.officeKnowledgeBase,
        title: 'Knowledge Base',
        description:
            'Extract campus documents, then generate and publish public articles.',
        child: content,
      );
    }

    return AdminScaffold(
      current: StudentNavItem.adminKnowledgeBase,
      title: title,
      description: description,
      child: content,
    );
  }
}

class _GenerateArticlesSourcePanel extends StatelessWidget {
  const _GenerateArticlesSourcePanel({
    required this.sourceFilename,
    required this.documentType,
    required this.documentProfile,
    required this.knowledgeUnitCount,
    required this.charterV2ServicesCount,
    required this.hasCharterV2Services,
    required this.status,
    required this.hasExtractionPreview,
    required this.hasCandidates,
    required this.recommendedPreviewLimitController,
    required this.isBusy,
    required this.onReload,
    required this.onGenerate,
    this.compact = false,
    this.liveSessionContext,
  });

  final String? sourceFilename;
  final String? documentType;
  final String? documentProfile;
  final int knowledgeUnitCount;
  final int charterV2ServicesCount;
  final bool hasCharterV2Services;
  final String status;
  final bool hasExtractionPreview;
  final bool hasCandidates;
  final TextEditingController recommendedPreviewLimitController;
  final bool isBusy;
  final VoidCallback onReload;
  final VoidCallback onGenerate;
  final bool compact;
  final KbSessionDisplayContext? liveSessionContext;

  String? get _compactContextLine {
    final live = liveSessionContext;
    if (live == null) return null;
    final parts = <String>[
      if (live.fileName?.trim().isNotEmpty == true) live.fileName!.trim(),
      if (live.knowledgeUnitCount > 0) '${live.knowledgeUnitCount} units',
      if (live.documentType?.trim().isNotEmpty == true) live.documentType!.trim(),
    ];
    return parts.isEmpty ? null : parts.join(' · ');
  }

  @override
  Widget build(BuildContext context) {
    final emptyHint = hasExtractionPreview
        ? 'No article candidates generated yet. Click Generate Article Candidates to create unsaved previews.'
        : 'No extracted document found. Please run Extract & Structure first.';
    final showLiveContext = compact && _compactContextLine != null;

    final panelBody = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (!compact)
          const StudentSectionTitle(
            title: 'Generated article candidates',
            subtitle:
                'Prepare student-facing drafts from the extracted source document. Content comes from the document, not invented text.',
          ),
        if (!compact) const SizedBox(height: 12),
        if (!compact)
          Wrap(
            spacing: 12,
            runSpacing: 8,
            children: [
              _MetaPill(
                label: sourceFilename?.isNotEmpty == true
                    ? sourceFilename!
                    : 'No source file selected',
              ),
              _MetaPill(
                label: hasExtractionPreview
                    ? 'Detected type: ${documentType ?? 'auto'}'
                    : 'Detected type: not available',
              ),
              if ((documentProfile ?? '').isNotEmpty)
                _MetaPill(
                  label: 'Profile: $documentProfile',
                ),
              _MetaPill(
                label: hasExtractionPreview
                    ? 'Knowledge units: $knowledgeUnitCount'
                    : 'Knowledge units: 0',
              ),
              _MetaPill(
                label: hasCharterV2Services
                    ? 'Structured services: $charterV2ServicesCount'
                    : 'Structured services: 0',
              ),
            ],
          ),
        if (showLiveContext) ...[
          Text(
            _compactContextLine!,
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: DesignTokens.muted,
              height: 1.4,
            ),
          ),
          const SizedBox(height: 10),
        ],
        if (!compact) ...[
          Row(
            children: [
              Expanded(
                child: Text(
                  status,
                  style: const TextStyle(
                    fontSize: 13,
                    color: DesignTokens.muted,
                    height: 1.45,
                  ),
                ),
              ),
              TextButton(
                onPressed: onReload,
                style: TextButton.styleFrom(
                  foregroundColor: DesignTokens.maroon,
                ),
                child: const Text('Reload from Documents'),
              ),
            ],
          ),
          const Divider(height: 28),
        ] else if (!showLiveContext) ...[
          Row(
            children: [
              Expanded(
                child: Text(
                  status,
                  style: const TextStyle(
                    fontSize: 13,
                    color: DesignTokens.muted,
                    height: 1.45,
                  ),
                ),
              ),
              TextButton(
                onPressed: onReload,
                style: TextButton.styleFrom(
                  foregroundColor: DesignTokens.maroon,
                ),
                child: const Text('Reload'),
              ),
            ],
          ),
          const SizedBox(height: 8),
        ],
        Align(
          alignment: Alignment.centerLeft,
          child: SizedBox(
            height: 48,
            child: ElevatedButton(
              onPressed: isBusy || !hasExtractionPreview ? null : onGenerate,
              style: ElevatedButton.styleFrom(
                backgroundColor: DesignTokens.maroon,
                foregroundColor: Colors.white,
              ),
              child: isBusy
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : const Text('Generate Article Candidates'),
            ),
          ),
        ),
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: const Text(
              'Advanced developer options',
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w700,
                color: DesignTokens.muted,
              ),
            ),
            children: [
              TextField(
                controller: recommendedPreviewLimitController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Recommended preview limit',
                  helperText:
                      'Optional dev-only cap on the Recommended bucket. Leave blank to generate all planner buckets.',
                ),
              ),
            ],
          ),
        ),
        if (!hasCandidates) ...[
          const SizedBox(height: 8),
          Text(
            emptyHint,
            style: const TextStyle(
              fontSize: 13,
              color: DesignTokens.muted,
              height: 1.45,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ],
    );

    if (compact) return panelBody;
    return StudentPanel(child: panelBody);
  }
}

class _GenerateArticlesSummary extends StatelessWidget {
  const _GenerateArticlesSummary({required this.generation});

  final CandidateGenerationResult generation;

  @override
  Widget build(BuildContext context) {
    final metrics = <_GenerationMetricData>[
      _GenerationMetricData(
        label: 'Knowledge units tagged',
        value: generation.totalDetected,
      ),
      _GenerationMetricData(
        label: 'Blueprints',
        value: generation.blueprintCount,
      ),
      _GenerationMetricData(
        label: 'Preview candidates (unsaved)',
        value: generation.previewCount > 0
            ? generation.previewCount
            : generation.createdCount,
      ),
      _GenerationMetricData(
        label: 'Recommended for review',
        value: generation.recommendedCount,
      ),
      _GenerationMetricData(
        label: 'Consolidated parents',
        value: generation.consolidatedParentCount,
      ),
      _GenerationMetricData(
        label: 'Needs manual review',
        value: generation.needsReviewCount,
      ),
      _GenerationMetricData(
        label: 'Low quality / cleanup',
        value: generation.skippedLowQualityCount,
      ),
      _GenerationMetricData(
        label: 'RAG-only units',
        value: generation.ragOnlyCount,
      ),
    ];

    return StudentPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const StudentSectionTitle(
            title: 'Generation Summary',
            subtitle:
                'Preview-only topic blueprints. Generate does not save. Save Draft stores unpublished articles. Publish is available only where safety rules allow it.',
          ),
          const SizedBox(height: 10),
          LayoutBuilder(
            builder: (context, constraints) {
              final columns = constraints.maxWidth >= 720
                  ? 4
                  : constraints.maxWidth >= 520
                      ? 3
                      : 2;
              return StudentResponsiveWrap(
                columns: columns,
                spacing: 12,
                children: metrics
                    .map(
                      (metric) =>
                          _GenerationMetric(label: metric.label, value: metric.value),
                    )
                    .toList(),
              );
            },
          ),
        ],
      ),
    );
  }
}

class _GenerationMetricData {
  const _GenerationMetricData({required this.label, required this.value});

  final String label;
  final int value;
}

class _GenerationMetric extends StatelessWidget {
  const _GenerationMetric({required this.label, required this.value});

  final String label;
  final int value;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Row(
        children: [
          Text(
            value.toString(),
            style: const TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w900,
              color: DesignTokens.ink,
            ),
          ),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              label,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w700,
                color: DesignTokens.muted,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _MetaPill extends StatelessWidget {
  const _MetaPill({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
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
    );
  }
}
