import 'package:flutter/material.dart';

import '../design_tokens.dart';
import '../models/admin_article_models.dart';
import '../services/admin_article_service.dart';
import '../widgets/admin_article_preview_export.dart';
import '../widgets/admin_kb_article_shared.dart';
import '../widgets/admin_kb_article_widgets.dart';

/// Topic-plan review: Recommended / Consolidated / Needs Review / Low Quality / RAG-only.
class GenerateArticlesReviewSection extends StatelessWidget {
  const GenerateArticlesReviewSection({
    super.key,
    required this.generationResult,
    required this.previewArticlesById,
    required this.savedArticlesByPreviewId,
    required this.discardedPreviewIds,
    required this.service,
    required this.onArticlesChanged,
    required this.onPreviewUpdated,
    required this.onPreviewSaved,
    required this.onDiscardPreview,
    this.fallbackSourceFilename,
    this.extractionPreview,
  });

  final CandidateGenerationResult generationResult;
  final Map<String, AdminArticle> previewArticlesById;
  final Map<String, AdminArticle> savedArticlesByPreviewId;
  final Set<String> discardedPreviewIds;
  final AdminArticleService service;
  final Future<void> Function() onArticlesChanged;
  final void Function(String previewId, AdminArticle article) onPreviewUpdated;
  final void Function(String previewId, AdminArticle saved) onPreviewSaved;
  final void Function(String previewId) onDiscardPreview;
  final String? fallbackSourceFilename;
  final Map<String, dynamic>? extractionPreview;

  List<CandidateSummary> _active(List<CandidateSummary> items) {
    return items.where((item) {
      final id = item.id;
      return id == null || id.isEmpty || !discardedPreviewIds.contains(id);
    }).toList();
  }

  bool _isPublishableBucketArtifact(CandidateSummary item) {
    return shouldBlockCharterPublish(
          title: item.title,
          reviewReasons: item.reviewReasons,
          sourceSection: item.sourceSection,
          plannerBucket: item.finalBucket ?? item.plannerBucket,
          finalBucket: item.finalBucket,
        ) ||
        isArtifactCharterTitle(item.title) ||
        charterPathHasArtifact(item.sourceSection);
  }

  String _resolvedBucket(CandidateSummary item) {
    final finalBucket = (item.finalBucket ?? '').toLowerCase();
    if (finalBucket.isNotEmpty) return finalBucket;
    final charter = (item.charterCandidateBucket ?? '').toLowerCase();
    if (charter.isNotEmpty) return charter;
    final planner = (item.plannerBucket ?? '').toLowerCase();
    if (planner.isNotEmpty && planner != 'pending') return planner;
    if (item.needsReview) return 'needs_review';
    return '';
  }

  List<CandidateSummary> _byBucket(String bucket) {
    final all = generationResult.allCandidates.isNotEmpty
        ? generationResult.allCandidates
        : [
            ...generationResult.recommendedCandidates,
            ...generationResult.consolidatedParentCandidates,
            ...generationResult.needsReviewCandidates,
            ...generationResult.lowConfidenceCandidates,
            ...generationResult.overflowCandidates,
          ];
    return _active(all.where((item) {
      final value = _resolvedBucket(item);
      if (bucket == 'recommended') {
        if (_isPublishableBucketArtifact(item)) return false;
        // Never fall back to empty/pending — incomplete charter cards must not land here.
        return value == 'recommended';
      }
      if (bucket == 'consolidated_parent') {
        if (_isPublishableBucketArtifact(item)) return false;
        return value == 'consolidated_parent';
      }
      if (bucket == 'needs_review') {
        if (_isPublishableBucketArtifact(item)) return false;
        return value == 'needs_review';
      }
      if (bucket == 'low_quality') {
        return value == 'low_quality' ||
            (value != 'rag_only' && _isPublishableBucketArtifact(item));
      }
      if (bucket == 'rag_only') {
        return value == 'rag_only';
      }
      return false;
    }).toList());
  }

  @override
  Widget build(BuildContext context) {
    final recommended = _byBucket('recommended');
    final consolidated = _byBucket('consolidated_parent');
    final needsReview = _byBucket('needs_review');
    final lowQuality = _byBucket('low_quality');
    final ragOnlyCandidates = _byBucket('rag_only');
    final coverage = generationResult.coverage;
    final ragOnlyCoverage = coverage.where((item) => item.status == 'rag_only').toList();

    final sections = <_PlannerSectionData>[
      _PlannerSectionData(
        'Recommended Articles',
        'recommended',
        recommended,
        expandedInitially: true,
        allowPublish: true,
        allowSaveDraft: true,
        allowBulkPublish: true,
        allowBulkSaveDraft: true,
        showReviewBeforePublishBadge: false,
        bulkSaveAllLabel: 'Save All Recommended as Draft',
        bulkPublishAllLabel: 'Publish All Recommended',
        bulkPublishAllConfirmMessage:
            'You are about to publish all Recommended Articles. Needs Review, Low Quality, and RAG-only sections will not be published.',
      ),
      _PlannerSectionData(
        'Consolidated Parent Articles',
        'consolidated_parent',
        consolidated,
        expandedInitially: true,
        allowPublish: true,
        allowSaveDraft: true,
        allowBulkPublish: true,
        allowBulkSaveDraft: true,
        showReviewBeforePublishBadge: false,
        bulkSaveAllLabel: 'Save All Consolidated as Draft',
        bulkPublishAllLabel: 'Publish All Consolidated',
        bulkPublishAllConfirmMessage:
            'You are about to publish all Consolidated Parent Articles that pass publish safety checks. Needs Review, Low Quality, and RAG-only sections will not be published.',
      ),
      _PlannerSectionData(
        'Needs Review',
        'needs_review',
        needsReview,
        expandedInitially: true,
        allowPublish: false,
        allowSaveDraft: true,
        allowBulkPublish: false,
        allowBulkSaveDraft: true,
        showReviewBeforePublishBadge: true,
      ),
      _PlannerSectionData(
        'Low Quality / Cleanup',
        'low_quality',
        lowQuality,
        expandedInitially: true,
        allowPublish: false,
        allowSaveDraft: true,
        allowBulkPublish: false,
        allowBulkSaveDraft: false,
        showReviewBeforePublishBadge: false,
        showLowQualityBadges: true,
        allowEditAsReviewDraft: true,
        lowQualityHelperText:
            'This article can be manually corrected and saved as a review draft before publishing.',
      ),
      _PlannerSectionData(
        'RAG-only',
        'rag_only',
        ragOnlyCandidates,
        expandedInitially: false,
        allowPublish: false,
        allowSaveDraft: false,
        allowBulkPublish: false,
        allowBulkSaveDraft: false,
        showReviewBeforePublishBadge: false,
        showLowQualityBadges: true,
      ),
    ];

    return KbAdminPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const KbSectionHeader(
            icon: Icons.fact_check_rounded,
            title: 'Generate Articles',
            subtitle:
                'Preview candidates from topic blueprints. Generate is preview-only. Save as Draft writes published=false. Publish writes published=true.',
          ),
          const SizedBox(height: 10),
          Text(
            '${generationResult.previewCount} preview candidates from ${generationResult.blueprintCount} blueprints '
            '(${generationResult.totalDetected} knowledge units tagged; ${generationResult.ragOnlyCount} RAG-only).',
            style: const TextStyle(fontSize: 13, color: DesignTokens.muted, height: 1.45),
          ),
          if (generationResult.charterReport != null) ...[
            const SizedBox(height: 14),
            _CharterGenerationReportPanel(report: generationResult.charterReport!),
          ],
          if (coverage.isNotEmpty) ...[
            const SizedBox(height: 14),
            _CoverageReportPanel(
              coverage: coverage,
              coverageCounts: generationResult.coverageCounts,
              recommendedCount: generationResult.recommendedCount,
            ),
          ],
          const SizedBox(height: 14),
          ...sections.asMap().entries.map((entry) {
            final index = entry.key;
            final section = entry.value;
            if (section.items.isEmpty) return const SizedBox.shrink();
            return Padding(
              padding: EdgeInsets.only(bottom: index < sections.length - 1 ? 12 : 0),
              child: GeneratedCandidateGroupSection(
                title: section.title,
                bucketKey: section.bucketKey,
                items: section.items,
                previewArticlesById: previewArticlesById,
                savedArticlesByPreviewId: savedArticlesByPreviewId,
                discardedPreviewIds: discardedPreviewIds,
                service: service,
                onArticlesChanged: onArticlesChanged,
                onPreviewUpdated: onPreviewUpdated,
                onPreviewSaved: onPreviewSaved,
                onDiscardPreview: onDiscardPreview,
                expandedInitially: section.expandedInitially,
                initialVisibleCount: 10,
                fallbackSourceFilename: fallbackSourceFilename,
                allowPublish: section.allowPublish,
                allowSaveDraft: section.allowSaveDraft,
                allowBulkPublish: section.allowBulkPublish,
                allowBulkSaveDraft: section.allowBulkSaveDraft,
                showReviewBeforePublishBadge: section.showReviewBeforePublishBadge,
                showLowQualityBadges: section.showLowQualityBadges,
                allowEditAsReviewDraft: section.allowEditAsReviewDraft,
                lowQualityHelperText: section.lowQualityHelperText,
                bulkPublishAllLabel: section.bulkPublishAllLabel,
                bulkSaveAllLabel: section.bulkSaveAllLabel,
                bulkPublishAllConfirmMessage: section.bulkPublishAllConfirmMessage,
              ),
            );
          }),
          if (ragOnlyCoverage.isNotEmpty) ...[
            const SizedBox(height: 12),
            _RagOnlyCoveragePanel(
              items: ragOnlyCoverage,
              extractionPreview: extractionPreview,
            ),
          ],
        ],
      ),
    );
  }
}

class _PlannerSectionData {
  const _PlannerSectionData(
    this.title,
    this.bucketKey,
    this.items, {
    required this.expandedInitially,
    required this.allowPublish,
    required this.allowSaveDraft,
    required this.allowBulkPublish,
    required this.allowBulkSaveDraft,
    required this.showReviewBeforePublishBadge,
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
  final bool expandedInitially;
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
}

class _CharterGenerationReportPanel extends StatelessWidget {
  const _CharterGenerationReportPanel({required this.report});

  final CharterGenerationReport report;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: DesignTokens.cardBg,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            "Citizen's Charter generation report",
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 6),
          const Text(
            'Parser cleanup summary for this Generate Articles run. '
            'Artifacts stay in Full Extraction; they are not public article candidates.',
            style: TextStyle(fontSize: 12, color: DesignTokens.muted, height: 1.4),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              if ((report.documentProfile ?? '').isNotEmpty)
                _CoverageChip('profile', report.documentProfile!),
              if ((report.parserUsed ?? '').isNotEmpty)
                _CoverageChip('parser', report.parserUsed!),
              _CoverageChip('review_text chars', report.reviewTextLength),
              _CoverageChip('knowledge units', report.knowledgeUnitsCount),
              _CoverageChip('detected services', report.totalDetectedServiceBlocks),
              _CoverageChip('valid services', report.validServiceBlocks),
              _CoverageChip('merged splits', report.mergedSplitServices),
              _CoverageChip('artifacts rejected', report.rejectedArtifactHeadings),
              _CoverageChip('mixed rejected', report.rejectedMixedServiceBlocks),
              _CoverageChip('incomplete rejected', report.rejectedIncompleteBlocks),
              _CoverageChip('generated candidates', report.generatedArticleCandidates),
              _CoverageChip('recommended', report.recommendedServices),
              _CoverageChip('needs review', report.needsReviewServices),
              _CoverageChip('low quality', report.lowQualityArtifactsDropped),
              _CoverageChip('RAG-only', report.ragOnlyReferences),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            report.v2Used
                ? "Citizen's Charter Extraction V2 (geometry-based) generated this run's services."
                : "Fallback text parser generated this run's services (V2 found no usable services).",
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: DesignTokens.muted),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _CoverageChip('v2 used', report.v2Used ? 'yes' : 'no'),
              _CoverageChip('v2 attempted', report.v2Attempted ? 'yes' : 'no'),
              _CoverageChip('v2 fallback used', report.v2FallbackUsed ? 'yes' : 'no'),
              _CoverageChip('pdf_pages available', report.pdfPagesAvailable ? 'yes' : 'no'),
              _CoverageChip('pdf_pages count', report.pdfPagesCount),
              _CoverageChip('pages with words', report.pagesWithWordsCount),
              _CoverageChip('total words', report.totalWordsCount),
              _CoverageChip(
                'preview has v2 services',
                report.previewHasCharterV2Services ? 'yes' : 'no',
              ),
              _CoverageChip(
                'preview v2 services count',
                report.previewCharterV2ServicesCount,
              ),
              _CoverageChip(
                'generate received v2 count',
                report.generateReceivedCharterV2ServicesCount,
              ),
              _CoverageChip('v2 services detected', report.v2ServicesDetected),
              _CoverageChip('v2 clean', report.v2CleanCount),
              _CoverageChip('v2 needs review', report.v2NeedsReviewCount),
              _CoverageChip('v2 low quality', report.v2LowQualityCount),
              _CoverageChip('v2 RAG-only', report.v2RagOnlyCount),
              if ((report.fallbackReason ?? '').isNotEmpty)
                _CoverageChip('fallback reason', report.fallbackReason!),
              if ((report.v2ErrorMessage ?? '').isNotEmpty)
                _CoverageChip('v2 error', report.v2ErrorMessage!),
              for (final entry in report.v2ParserStrategyCounts.entries)
                _CoverageChip('v2 strategy: ${entry.key}', entry.value),
            ],
          ),
          const SizedBox(height: 10),
          const Text(
            'Rescue / repair (before final bucket assignment)',
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: DesignTokens.muted),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _CoverageChip('rescue attempted', report.rescueAttempted),
              _CoverageChip('rescue successful', report.rescueSuccessful),
              _CoverageChip(
                'promoted to recommended after repair',
                report.promotedToRecommendedAfterRepair,
              ),
              _CoverageChip(
                'downgraded after semantic validation',
                report.downgradedAfterSemanticValidation,
              ),
              _CoverageChip(
                'internal kept as needs review/RAG-only',
                report.internalServicesKeptAsNeedsReviewOrRagOnly,
              ),
              _CoverageChip('true low quality fragments', report.trueLowQualityFragments),
              _CoverageChip('repaired but not promoted', report.repairedButNotPromoted),
              _CoverageChip('repair failed', report.repairFailed),
              _CoverageChip('semantic validation failed', report.semanticValidationFailed),
              _CoverageChip(
                'recommended blocked by semantic validation',
                report.recommendedBlockedBySemanticValidation,
              ),
              _CoverageChip('low quality rescue attempted', report.lowQualityRepairAttempted),
              _CoverageChip(
                'low quality repair changed fields',
                report.lowQualityRepairChangedFields,
              ),
              _CoverageChip(
                'low quality rescued to needs review',
                report.lowQualityRescuedToNeedsReview,
              ),
              _CoverageChip(
                'low quality rescued to recommended',
                report.lowQualityRescuedToRecommended,
              ),
              _CoverageChip('low quality repair failed', report.lowQualityRepairFailed),
              _CoverageChip(
                'low quality left LQ (successful)',
                report.lowQualityRescueSuccessful,
              ),
              _CoverageChip('public priority found', report.publicPriorityFound),
              _CoverageChip(
                'public priority recommended',
                report.publicPriorityRecommended,
              ),
              _CoverageChip(
                'public priority needs review',
                report.publicPriorityNeedsReview,
              ),
              _CoverageChip(
                'public priority low quality',
                report.publicPriorityLowQuality,
              ),
              _CoverageChip('public priority repaired', report.publicPriorityRepaired),
              _CoverageChip(
                'public priority blocked by article body',
                report.publicPriorityBlockedByArticleBody,
              ),
            ],
          ),
          if (report.priorityServiceDiagnostics.isNotEmpty) ...[
            const SizedBox(height: 10),
            const Text(
              'Priority Coverage',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: DesignTokens.muted),
            ),
            const SizedBox(height: 6),
            ...report.priorityServiceDiagnostics.map((item) {
              final title = item['title']?.toString() ?? 'Unknown';
              final found = item['found'] == true;
              final extractionStatus =
                  item['extraction_status']?.toString() ?? (found ? 'unknown' : 'not_found');
              final bucket = item['final_bucket']?.toString() ??
                  item['repaired_bucket']?.toString() ??
                  '—';
              final publishAllowed = item['publish_allowed'] == true;
              final reqCount =
                  item['detected_requirement_count'] ?? item['detected_requirements_count'];
              final stepCount = item['detected_step_count'];
              final renderedCount = item['rendered_step_count'];
              final totalTime = item['total_processing_time_detected'] == true;
              final bodyNeedsReview = item['body_has_needs_review'] == true;
              final blockersList = item['blockers'] is List
                  ? item['blockers'] as List
                  : (item['remaining_blockers'] is List
                        ? item['remaining_blockers'] as List
                        : const []);
              final blockers = blockersList.join(', ');
              final nextAction = item['next_action']?.toString() ?? '';
              final nextRepair = item['next_repair_target']?.toString() ?? '';
              final repairable = item['repairable'] == true;
              final mainFailed = item['main_failed_field']?.toString() ?? '';
              final suggested = item['suggested_bucket_after_repair']?.toString() ?? '';
              final isStudentPriority = item['is_student_priority'] != false;
              final isPublicPriority = item['is_public_priority'] != false;
              final articleBodyStatus = item['article_body_status']?.toString() ?? '';
              final bodyRebuilt = item['body_rebuilt_from_detected_fields'] == true;
              final requiredStepsMet = item['required_step_count_met'];
              final publishSafety = item['publish_safety_state']?.toString() ?? '';
              final alreadyPublishedMatch = item['already_published_match'] == true;
              final detail = [
                'found=${found ? 'yes' : 'no'}',
                'extraction_status=$extractionStatus',
                'final_bucket=$bucket',
                'publish_allowed=${publishAllowed ? 'yes' : 'no'}',
                if (mainFailed.isNotEmpty) 'main_failed_field=$mainFailed',
                if (nextRepair.isNotEmpty) 'next_repair_target=$nextRepair',
                if (suggested.isNotEmpty) 'suggested_bucket_after_repair=$suggested',
                if (articleBodyStatus.isNotEmpty) 'article_body_status=$articleBodyStatus',
                'body_has_needs_review=${bodyNeedsReview ? 'yes' : 'no'}',
                'body_rebuilt_from_detected_fields=${bodyRebuilt ? 'yes' : 'no'}',
                if (requiredStepsMet != null)
                  'required_step_count_met=${requiredStepsMet == true ? 'yes' : 'no'}',
                if (publishSafety.isNotEmpty) 'publish_safety_state=$publishSafety',
                'already_published_match=${alreadyPublishedMatch ? 'yes' : 'no'}',
                if (renderedCount != null) 'rendered_step_count=$renderedCount',
                if (stepCount != null) 'detected_step_count=$stepCount',
                if (reqCount != null) 'detected_requirement_count=$reqCount',
                'total_processing_time_detected=${totalTime ? 'yes' : 'no'}',
                if (blockers.isNotEmpty) 'blockers=$blockers',
                if (nextAction.isNotEmpty) 'next_action=$nextAction',
                'repairable=${repairable ? 'yes' : 'no'}',
                'is_public_priority=${isPublicPriority ? 'yes' : 'no'}',
                'is_student_priority=${isStudentPriority ? 'yes' : 'no'}',
              ].join(' · ');
              return Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(
                  '$title — $detail',
                  style: const TextStyle(fontSize: 11, color: DesignTokens.muted, height: 1.35),
                ),
              );
            }),
          ],
        ],
      ),
    );
  }
}

class _CoverageReportPanel extends StatelessWidget {
  const _CoverageReportPanel({
    required this.coverage,
    this.coverageCounts = const {},
    this.recommendedCount = 0,
  });

  final List<CoverageTopic> coverage;
  final Map<String, int> coverageCounts;
  final int recommendedCount;

  @override
  Widget build(BuildContext context) {
    final counts = <String, int>{};
    if (coverageCounts.isNotEmpty) {
      counts.addAll(coverageCounts);
    } else {
      for (final item in coverage) {
        counts[item.status] = (counts[item.status] ?? 0) + 1;
      }
    }
    return KbAdminPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Coverage Report',
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 6),
          Text(
            'Generated = recommended article previews (${counts['generated'] ?? recommendedCount}). '
            'Merged parent = consolidated parent previews. '
            'Needs review = preview created but flagged for admin review. '
            'RAG-only = no article. Needs cleanup = low quality.',
            style: const TextStyle(fontSize: 12, color: DesignTokens.muted, height: 1.4),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _CoverageChip('generated', counts['generated'] ?? 0),
              _CoverageChip('merged_parent', counts['merged_parent'] ?? 0),
              _CoverageChip('needs_review', counts['needs_review'] ?? 0),
              _CoverageChip('rag_only', counts['rag_only'] ?? 0),
              _CoverageChip('needs_cleanup', counts['needs_cleanup'] ?? 0),
            ],
          ),
        ],
      ),
    );
  }
}

class _CoverageChip extends StatelessWidget {
  const _CoverageChip(this.label, this.value);

  final String label;
  final Object value;

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
        '$label: $value',
        style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class _RagOnlyCoveragePanel extends StatefulWidget {
  const _RagOnlyCoveragePanel({
    required this.items,
    this.extractionPreview,
  });

  final List<CoverageTopic> items;
  final Map<String, dynamic>? extractionPreview;

  @override
  State<_RagOnlyCoveragePanel> createState() => _RagOnlyCoveragePanelState();
}

class _RagOnlyCoveragePanelState extends State<_RagOnlyCoveragePanel> {
  static const _pageSize = 10;
  int _visibleCount = _pageSize;

  List<Map<String, dynamic>> _matchingUnits(CoverageTopic topic) {
    final raw = widget.extractionPreview?['knowledge_units'];
    if (raw is! List) return const [];
    final topicKey = topic.canonicalTopic.toLowerCase();
    final parentKey = topic.parentTopic.toLowerCase();
    return raw.whereType<Map>().map((item) => Map<String, dynamic>.from(item)).where((unit) {
      final title = unit['title']?.toString().toLowerCase() ?? '';
      final path = unit['hierarchy_path']?.toString().toLowerCase() ?? '';
      return title.contains(topicKey) ||
          path.contains(topicKey) ||
          path.contains(parentKey);
    }).toList();
  }

  void _showSourceDialog(CoverageTopic topic) {
    final units = _matchingUnits(topic);
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(topic.canonicalTopic),
        content: SizedBox(
          width: 560,
          child: units.isEmpty
              ? Text(
                  topic.sourceSection?.isNotEmpty == true
                      ? 'Source section: ${topic.sourceSection}'
                      : 'No matching knowledge units found in the current extraction preview.',
                )
              : SingleChildScrollView(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: units.take(5).map((unit) {
                      final title = unit['title']?.toString() ?? 'Untitled';
                      final path = unit['hierarchy_path']?.toString() ?? '—';
                      final content = unit['content']?.toString() ?? '';
                      final preview = content.length > 280
                          ? '${content.substring(0, 280).trim()}…'
                          : content.trim();
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
                            const SizedBox(height: 4),
                            Text(
                              path,
                              style: const TextStyle(fontSize: 12, color: DesignTokens.muted),
                            ),
                            if (preview.isNotEmpty) ...[
                              const SizedBox(height: 6),
                              Text(preview, style: const TextStyle(fontSize: 13, height: 1.4)),
                            ],
                          ],
                        ),
                      );
                    }).toList(),
                  ),
                ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final visible = widget.items.take(_visibleCount).toList();
    final hasMore = _visibleCount < widget.items.length;

    return KbAdminPanel(
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: EdgeInsets.zero,
          initiallyExpanded: false,
          title: Text(
            'RAG-only Sections (${widget.items.length})',
            style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: DesignTokens.ink,
            ),
          ),
          subtitle: const Text(
            'These sections remain available for chatbot retrieval and citation grounding, '
            'but are not recommended as public Knowledge Base articles.',
            style: TextStyle(fontSize: 12, color: DesignTokens.muted, height: 1.4),
          ),
          children: [
            ...visible.map(
              (item) => Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            item.canonicalTopic,
                            style: const TextStyle(fontWeight: FontWeight.w700),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            [
                              if (item.sourceSection != null &&
                                  item.sourceSection!.isNotEmpty)
                                'Source: ${item.sourceSection}',
                              '${item.unitCount} unit(s)',
                              item.reason ?? 'RAG-only',
                            ].join(' • '),
                            style: const TextStyle(fontSize: 12, color: DesignTokens.muted),
                          ),
                        ],
                      ),
                    ),
                    TextButton(
                      onPressed: () => _showSourceDialog(item),
                      child: const Text('View Source'),
                    ),
                  ],
                ),
              ),
            ),
            if (hasMore)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton(
                  onPressed: () => setState(() => _visibleCount += _pageSize),
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
