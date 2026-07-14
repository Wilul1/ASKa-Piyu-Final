import 'dart:convert';

import '../models/admin_article_models.dart';

const _publishBlockingFlags = {
  'mixed_charter_services',
  'administrative_background_title',
  'title_too_short',
  'title_incomplete_ocr_fragment',
  'artifact_title',
  'charter_artifact_title',
  'invalid_charter_service_block',
  'incomplete_charter_service',
  'incomplete_structured_fields',
  'incomplete_step_rows',
  'table_row_fragment',
  'field_label_title',
  'missing_required_charter_fields',
  'office_only_title',
  'form_code_only_title',
};

final _artifactTitlePatterns = <RegExp>[
  RegExp(r'^classification$', caseSensitive: false),
  RegExp(r'^classification\s*:\s*.+', caseSensitive: false),
  RegExp(r'^nexus\s+system\b', caseSensitive: false),
  RegExp(r'^official\s+receipt\b', caseSensitive: false),
  RegExp(r'^validation$', caseSensitive: false),
  RegExp(r'abstract\s+of\s+quotation', caseSensitive: false),
  RegExp(r'^board\s+of\s+regents\b', caseSensitive: false),
  RegExp(r'^board\s+secretary', caseSensitive: false),
  RegExp(r'^bac\s+sec\b', caseSensitive: false),
  RegExp(r'^checking\s+of\s+supporting', caseSensitive: false),
  RegExp(r'^prepare$', caseSensitive: false),
  RegExp(r'^page\s+\d+\b', caseSensitive: false),
  RegExp(r'^table\s+(?:continued|continuation)\b', caseSensitive: false),
  RegExp(r'^continued\b', caseSensitive: false),
  RegExp(r'^fees?\s*:', caseSensitive: false),
  RegExp(r'^processing\s+time\s*:', caseSensitive: false),
  RegExp(r'^transaction\s+type\s*:', caseSensitive: false),
  RegExp(r'^requirement\s*:', caseSensitive: false),
  RegExp(r'^client\s+step\s*:', caseSensitive: false),
  RegExp(r'^agency\s+action\s*:', caseSensitive: false),
  RegExp(r'^person\s+responsible\s*:', caseSensitive: false),
  RegExp(r'\[needs\s+review\]', caseSensitive: false),
  RegExp(r'^procurement\s+plan\b', caseSensitive: false),
  RegExp(r'^nstp\s+office$', caseSensitive: false),
];

bool isArtifactCharterTitle(String? title) {
  var cleaned = (title ?? '').trim();
  if (cleaned.isEmpty) return true;
  cleaned = cleaned.replaceFirst(RegExp(r'^\d{1,3}[\.\)]\s*'), '').trim();
  if (cleaned.contains('>')) {
    cleaned = cleaned.split(RegExp(r'\s*>\s*')).last.trim();
  }
  for (final pattern in _artifactTitlePatterns) {
    if (pattern.hasMatch(cleaned)) return true;
  }
  if (cleaned.isNotEmpty && RegExp(r'^[a-z]').hasMatch(cleaned)) {
    // Leading lowercase OCR crumb.
    return true;
  }
  if ((title ?? '').contains('>') &&
      RegExp(r'classification\s*:|abstract|official\s+receipt|nexus',
              caseSensitive: false)
          .hasMatch(title!)) {
    return true;
  }
  return false;
}

bool charterPathHasArtifact(String? path) {
  final text = (path ?? '').trim();
  if (text.isEmpty) return false;
  for (final part in text.split(RegExp(r'\s*>\s*'))) {
    if (isArtifactCharterTitle(part.trim())) return true;
  }
  return false;
}

bool shouldBlockCharterPublish({
  required String title,
  List<String> reviewReasons = const [],
  String? sourceSection,
  String? plannerBucket,
  String? finalBucket,
}) {
  if (reviewReasons.any(_publishBlockingFlags.contains)) return true;
  if (isArtifactCharterTitle(title)) return true;
  if (charterPathHasArtifact(sourceSection)) {
    final leaf = sourceSection!.split(RegExp(r'\s*>\s*')).last.trim();
    if (isArtifactCharterTitle(leaf) || isArtifactCharterTitle(title)) {
      return true;
    }
  }
  final bucket = (finalBucket ?? plannerBucket ?? '').toLowerCase();
  if (bucket == 'low_quality' || bucket == 'rag_only') return true;
  return false;
}

String bucketLabelForExport(String? plannerBucket, {String? fallback}) {
  switch ((plannerBucket ?? fallback ?? '').toLowerCase()) {
    case 'recommended':
      return 'Recommended';
    case 'consolidated_parent':
      return 'Consolidated';
    case 'needs_review':
      return 'Needs Review';
    case 'low_quality':
      return 'Low Quality';
    case 'rag_only':
      return 'RAG-only';
    default:
      return (plannerBucket ?? fallback ?? 'Unknown').trim().isEmpty
          ? 'Unknown'
          : (plannerBucket ?? fallback)!;
  }
}

String safePreviewFilename({
  required String title,
  required String bucketLabel,
}) {
  final safeTitle = title
      .toLowerCase()
      .replaceAll(RegExp(r'[^a-z0-9]+'), '_')
      .replaceAll(RegExp(r'_+'), '_')
      .replaceAll(RegExp(r'^_|_$'), '');
  final safeBucket = bucketLabel
      .toLowerCase()
      .replaceAll(RegExp(r'[^a-z0-9]+'), '_')
      .replaceAll(RegExp(r'_+'), '_')
      .replaceAll(RegExp(r'^_|_$'), '');
  final stem = (safeTitle.isEmpty ? 'article' : safeTitle);
  final bucket = (safeBucket.isEmpty ? 'preview' : safeBucket);
  return 'aska_piyu_article_preview_${stem}_$bucket.txt';
}

String buildArticlePreviewTxt({
  required AdminArticle article,
  required String bucketLabel,
  CandidateSummary? candidate,
  String? fallbackSourceFilename,
}) {
  final meta = Map<String, dynamic>.from(article.metadata);
  final reviewFlags = <String>{
    ...article.reviewReasons,
    ...?candidate?.reviewReasons,
  }.toList();
  final page = meta['page']?.toString() ??
      meta['page_number']?.toString() ??
      meta['source_page']?.toString() ??
      'Not specified';
  final documentId = meta['source_document_id']?.toString() ??
      meta['document_id']?.toString() ??
      'Not specified';
  final excerpt = article.officialSourceExcerpt?.trim().isNotEmpty == true
      ? article.officialSourceExcerpt!.trim()
      : 'Not specified';
  final body = (article.displayContent.trim().isNotEmpty
          ? article.displayContent.trim()
          : (candidate?.content ?? article.content ?? '').trim())
      .trim();
  final summary = (article.summary ?? candidate?.summary ?? '').trim();
  final sourceFile = (article.sourceFilename ??
          candidate?.sourceFilename ??
          fallbackSourceFilename ??
          '')
      .trim();
  final sourceSection = (article.sourceSection ?? candidate?.sourceSection ?? '')
      .trim();

  final blockingFlags = <String>{
    ..._readExportStringList(meta['blocking_review_flags']),
    ...?candidate?.blockingReviewFlags,
    ...reviewFlags.where(_publishBlockingFlags.contains),
  }.toList();
  final bucketReason = meta['bucket_reason']?.toString() ??
      candidate?.bucketReason ??
      'Not specified';
  final studentFacing = meta['student_facing_score'] ??
      candidate?.studentFacingScore ??
      'Not specified';
  final internalAdmin = meta['internal_admin_score'] ??
      candidate?.internalAdminScore ??
      'Not specified';
  final parserDebug = meta['parser_debug'] is Map
      ? Map<String, dynamic>.from(meta['parser_debug'] as Map)
      : <String, dynamic>{};
  final parserDebugText = parserDebug.isEmpty
      ? 'Not specified'
      : [
          'raw_service_block: ${_clipDebug(parserDebug['raw_service_block'])}',
          'cleaned_service_block: ${_clipDebug(parserDebug['cleaned_service_block'])}',
          'dropped_header_fragments: ${parserDebug['dropped_header_fragments'] ?? '[]'}',
          'reconstructed_step_rows: ${parserDebug['reconstructed_step_rows'] ?? 'Not specified'}',
          'rejected_fake_steps: ${parserDebug['rejected_fake_steps'] ?? 'Not specified'}',
          'requirement_pairs_detected: ${parserDebug['requirement_pairs_detected'] ?? 'Not specified'}',
          'total_line_detected: ${parserDebug['total_line_detected'] ?? 'Not specified'}',
          // Citizen's Charter Extraction V2 debug fields (only present when V2 ran).
          'extraction_quality: ${parserDebug['extraction_quality'] ?? 'Not specified'}',
          'extraction_quality_reason: ${parserDebug['extraction_quality_reason'] ?? 'Not specified'}',
          'parser_strategy_used: ${parserDebug['parser_strategy_used'] ?? 'Not specified'}',
          'table_extraction_method: ${parserDebug['table_extraction_method'] ?? 'Not specified'}',
          'page_start: ${parserDebug['page_start'] ?? 'Not specified'}',
          'page_end: ${parserDebug['page_end'] ?? 'Not specified'}',
          'detected_service_title: ${parserDebug['detected_service_title'] ?? 'Not specified'}',
          'detected_office: ${parserDebug['detected_office'] ?? 'Not specified'}',
          'detected_requirements: ${parserDebug['detected_requirements'] ?? 'Not specified'}',
          'detected_step_rows: ${parserDebug['detected_step_rows'] ?? 'Not specified'}',
          'rejected_fragments: ${parserDebug['rejected_fragments'] ?? 'Not specified'}',
          'rescue: ${parserDebug['rescue'] ?? 'Not specified'}',
          'visual_table_debug: ${_clipDebug(parserDebug['visual_table_debug'])}',
          'no_step_rows_reason: ${parserDebug['no_step_rows_reason'] ?? 'Not specified'}',
        ].join('\n');

  final rescueMetaLines = <String>[
    'rescue_attempted: ${meta['rescue_attempted'] ?? candidate?.rescueAttempted ?? 'Not specified'}',
    'rescue_successful: ${meta['rescue_successful'] ?? candidate?.rescueSuccessful ?? 'Not specified'}',
    'original_bucket: ${meta['original_bucket'] ?? candidate?.originalBucket ?? 'Not specified'}',
    'repaired_bucket: ${meta['repaired_bucket'] ?? candidate?.repairedBucket ?? 'Not specified'}',
    'remaining_blockers: ${(meta['remaining_blockers'] ?? candidate?.remainingBlockers ?? const []).toString()}',
    'missing_fields: ${(meta['missing_fields'] ?? const []).toString()}',
    'row_merge_failure_reason: ${meta['row_merge_failure_reason'] ?? 'Not specified'}',
    'repair_actions_applied: ${(meta['repair_actions_applied'] ?? candidate?.repairActionsApplied ?? const []).toString()}',
  ];
  final priorityDiag = meta['priority_service_diagnostics'];
  if (priorityDiag is List && priorityDiag.isNotEmpty) {
    rescueMetaLines.add('priority_coverage / priority_service_diagnostics:');
    for (final item in priorityDiag.whereType<Map>()) {
      rescueMetaLines.add('  - ${const JsonEncoder().convert(item)}');
    }
  }

  final metadataJson = const JsonEncoder.withIndent('  ').convert(
    meta.isEmpty ? <String, dynamic>{'note': 'No embedded metadata'} : meta,
  );

  return [
    'Title:',
    article.title,
    '',
    'Bucket:',
    bucketLabel,
    '',
    'Rescue Diagnostics:',
    rescueMetaLines.join('\n'),
    '',
    'Final Bucket:',
    meta['final_bucket']?.toString() ??
        candidate?.finalBucket ??
        'Not specified',
    '',
    'Raw Bucket:',
    meta['raw_bucket']?.toString() ?? candidate?.rawBucket ?? 'Not specified',
    '',
    'Charter Candidate Bucket:',
    meta['charter_candidate_bucket']?.toString() ??
        candidate?.charterCandidateBucket ??
        'Not specified',
    '',
    'Planner Bucket:',
    meta['planner_bucket']?.toString() ??
        candidate?.plannerBucket ??
        'Not specified',
    '',
    'UI Group Bucket:',
    meta['ui_group_bucket']?.toString() ??
        candidate?.uiGroupBucket ??
        bucketLabel,
    '',
    'Publish Allowed:',
    '${meta['publish_allowed'] ?? candidate?.publishAllowed ?? 'Not specified'}',
    '',
    'Save Draft Allowed:',
    '${meta['save_draft_allowed'] ?? candidate?.saveDraftAllowed ?? 'Not specified'}',
    '',
    'Bucket Consistency Check:',
    meta['bucket_consistency_check']?.toString() ??
        candidate?.bucketConsistencyCheck ??
        'Not specified',
    '',
    'Bucket Reason:',
    bucketReason,
    '',
    'Student Facing Score:',
    '$studentFacing',
    '',
    'Internal Admin Score:',
    '$internalAdmin',
    '',
    'Blocking Review Flags:',
    blockingFlags.isEmpty ? 'None' : blockingFlags.join(', '),
    '',
    'Parser Debug:',
    parserDebugText,
    '',
    'Category:',
    article.category.isEmpty ? 'Not specified' : article.category,
    '',
    'Article Type:',
    (article.documentType ??
        candidate?.articleType ??
        candidate?.documentType ??
        'Not specified'),
    '',
    'Document Type:',
    meta['document_type']?.toString() ??
        article.documentType ??
        candidate?.documentType ??
        'Not specified',
    '',
    'Document Profile:',
    meta['document_profile']?.toString() ??
        candidate?.documentProfile ??
        meta['parser_document_type']?.toString() ??
        'Not specified',
    '',
    'Detected Document Type:',
    meta['detected_document_type']?.toString() ?? 'Not specified',
    '',
    'Admin Selected Document Type:',
    meta['admin_selected_document_type']?.toString() ?? 'Not specified',
    '',
    'Source Type:',
    meta['source_type']?.toString() ?? 'Not specified',
    '',
    'Parser Used:',
    meta['parser_used']?.toString() ??
        candidate?.parserUsed ??
        'Not specified',
    '',
    'Formatter Used:',
    meta['formatter_used']?.toString() ??
        candidate?.formatterUsed ??
        'Not specified',
    '',
    'Quality:',
    '${article.qualityScore ?? candidate?.qualityScore ?? 'Not specified'}',
    '',
    'Confidence:',
    '${article.categoryConfidence ?? candidate?.categoryConfidence ?? 'Not specified'}',
    '',
    'Usefulness:',
    '${article.studentUsefulnessScore ?? candidate?.studentUsefulnessScore ?? 'Not specified'}',
    '',
    'Review Flags:',
    reviewFlags.isEmpty ? 'None' : reviewFlags.join(', '),
    '',
    'Source File:',
    sourceFile.isEmpty ? 'Not specified' : sourceFile,
    '',
    'Source Section:',
    sourceSection.isEmpty ? 'Not specified' : sourceSection,
    '',
    'Source Document ID:',
    documentId,
    '',
    'Page:',
    page,
    '',
    'Short Summary:',
    summary.isEmpty ? 'Not specified' : summary,
    '',
    'Article Content:',
    body.isEmpty ? 'Not specified' : body,
    '',
    'Official Source Excerpt:',
    excerpt,
    '',
    'Metadata:',
    metadataJson,
    '',
  ].join('\n');
}

List<String> _readExportStringList(dynamic value) {
  if (value is! List) return const [];
  return value
      .map((item) => item?.toString().trim() ?? '')
      .where((item) => item.isNotEmpty)
      .toList();
}

String _clipDebug(dynamic value, {int maxChars = 500}) {
  final text = (value ?? '').toString().trim();
  if (text.isEmpty) return 'Not specified';
  if (text.length <= maxChars) return text;
  return '${text.substring(0, maxChars)}…';
}
