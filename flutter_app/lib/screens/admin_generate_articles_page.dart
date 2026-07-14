import 'dart:html' as html;

import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../models/admin_article_models.dart';
import '../services/admin_article_service.dart';
import '../services/extraction_preview_store.dart';
import '../widgets/student_ui.dart';
import '../widgets/sidebar.dart';
import 'admin_kb_article_library_section.dart';
import 'admin_kb_generate_articles_section.dart';
import 'admin_kb_outline.dart';
import 'admin_management_pages.dart';

class AdminGenerateArticlesPage extends StatefulWidget {
  const AdminGenerateArticlesPage({super.key});

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
  int _articleLibraryRefreshToken = 0;

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
    return AdminArticleService(
      apiBase: AppConfig.resolvedApiBase,
      setAdminHeader: _setAdminHeader,
    );
  }

  void _setAdminHeader(html.HttpRequest request) {
    final auth = AuthScope.of(context);
    final token = auth.accessToken;
    if (auth.role != 'admin') {
      throw StateError('not_admin');
    }
    if (token == null || token.trim().isEmpty) {
      throw StateError('missing_admin_token');
    }
    request.setRequestHeader('Authorization', 'Bearer $token');
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
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.toString())));
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.toString())));
    } finally {
      if (mounted) {
        setState(() => _isGeneratingCandidates = false);
      }
    }
  }

  Future<void> _onGeneratedArticlesChanged() async {
    setState(() => _articleLibraryRefreshToken++);
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
    return AdminScaffold(
      current: StudentNavItem.adminGenerateArticles,
      title: 'Generate Articles',
      description:
          'Generate and review student-facing article candidates from extracted documents before saving or publishing.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _GenerateArticlesExtractionSummary(
            sourceFilename: _sourceFilename,
            documentType: _detectedDocumentType,
            documentProfile: _documentProfile,
            knowledgeUnitCount: _knowledgeUnitCount,
            charterV2ServicesCount: _charterV2ServicesCount,
            hasCharterV2Services: _hasCharterV2Services,
            status: _extractionStatus,
            hasExtractionPreview: _hasExtractionPreview,
            onReload: _loadLastExtraction,
          ),
          const SizedBox(height: 14),
          _GenerateArticlesControls(
            recommendedPreviewLimitController: _recommendedPreviewLimitController,
            isBusy: _isGeneratingCandidates,
            hasExtractionPreview: _hasExtractionPreview,
            onGenerate: _generateArticleCandidates,
          ),
          if (_candidateGenerationResult != null) ...[
            const SizedBox(height: 16),
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
          ] else ...[
            const SizedBox(height: 16),
            StudentPanel(
              shadow: false,
              child: Text(
                _hasExtractionPreview
                    ? 'No article candidates generated yet. Click Generate Article Candidates to create unsaved previews.'
                    : 'No extracted document found. Please run Extract & Structure first.',
                style: const TextStyle(
                  fontSize: 13,
                  color: DesignTokens.muted,
                  height: 1.45,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ],
          const SizedBox(height: 18),
          AdminKbArticleLibrarySection(
            setAdminHeader: _setAdminHeader,
            refreshToken: _articleLibraryRefreshToken,
          ),
        ],
      ),
    );
  }
}

class _GenerateArticlesExtractionSummary extends StatelessWidget {
  const _GenerateArticlesExtractionSummary({
    required this.sourceFilename,
    required this.documentType,
    required this.documentProfile,
    required this.knowledgeUnitCount,
    required this.charterV2ServicesCount,
    required this.hasCharterV2Services,
    required this.status,
    required this.hasExtractionPreview,
    required this.onReload,
  });

  final String? sourceFilename;
  final String? documentType;
  final String? documentProfile;
  final int knowledgeUnitCount;
  final int charterV2ServicesCount;
  final bool hasCharterV2Services;
  final String status;
  final bool hasExtractionPreview;
  final VoidCallback onReload;

  @override
  Widget build(BuildContext context) {
    return StudentPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const StudentSectionTitle(
            title: 'Selected Extracted Document',
            subtitle:
                'Uses the most recent successful Extract & Structure result from Documents.',
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 12,
            runSpacing: 8,
            children: [
              _MetaPill(
                icon: Icons.description_outlined,
                label: sourceFilename?.isNotEmpty == true
                    ? sourceFilename!
                    : 'No source file selected',
              ),
              _MetaPill(
                icon: Icons.article_rounded,
                label: hasExtractionPreview
                    ? 'Detected type: ${documentType ?? 'auto'}'
                    : 'Detected type: not available',
              ),
              if ((documentProfile ?? '').isNotEmpty)
                _MetaPill(
                  icon: Icons.folder_outlined,
                  label: 'Profile: $documentProfile',
                ),
              _MetaPill(
                icon: Icons.article_outlined,
                label: hasExtractionPreview
                    ? 'Knowledge units: $knowledgeUnitCount'
                    : 'Knowledge units: 0',
              ),
              _MetaPill(
                icon: Icons.auto_awesome_outlined,
                label: hasCharterV2Services
                    ? 'V2 services: $charterV2ServicesCount'
                    : 'V2 services: 0',
              ),
            ],
          ),
          const SizedBox(height: 10),
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
                child: const Text('Reload from Documents'),
                style: TextButton.styleFrom(
                  foregroundColor: DesignTokens.maroon,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _GenerateArticlesControls extends StatelessWidget {
  const _GenerateArticlesControls({
    required this.recommendedPreviewLimitController,
    required this.isBusy,
    required this.hasExtractionPreview,
    required this.onGenerate,
  });

  final TextEditingController recommendedPreviewLimitController;
  final bool isBusy;
  final bool hasExtractionPreview;
  final VoidCallback onGenerate;

  @override
  Widget build(BuildContext context) {
    return StudentPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const StudentSectionTitle(
            title: 'Generate Article Candidates',
            subtitle:
                'Create unsaved article candidate previews from planner blueprints. Review buckets below determine priority.',
          ),
          const SizedBox(height: 14),
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
        ],
      ),
    );
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
                'Preview-only topic blueprints. Generate does not save. Save as Draft = published=false. Publish = published=true.',
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
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
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
          Text(
            label,
            style: const TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: DesignTokens.muted,
            ),
          ),
        ],
      ),
    );
  }
}

class _MetaPill extends StatelessWidget {
  const _MetaPill({required this.icon, required this.label});

  final IconData icon;
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
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: DesignTokens.muted),
          const SizedBox(width: 6),
          Text(
            label,
            style: const TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: DesignTokens.muted,
            ),
          ),
        ],
      ),
    );
  }
}
