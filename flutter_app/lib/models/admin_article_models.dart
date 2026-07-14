import 'dart:convert';

enum ArticleReviewBucket { recommended, needsReview, overflow, published }

class AdminArticle {
  const AdminArticle({
    required this.id,
    required this.title,
    required this.category,
    required this.published,
    this.slug,
    this.summary,
    this.content,
    this.office,
    this.sourceFilename,
    this.chunkCount,
    this.publishedAt,
    this.createdAt,
    this.updatedAt,
    this.metadata = const {},
    this.displayContent = '',
  });

  final String id;
  final String title;
  final String category;
  final bool published;
  final String? slug;
  final String? summary;
  final String? content;
  final String? office;
  final String? sourceFilename;
  final int? chunkCount;
  final String? publishedAt;
  final String? createdAt;
  final String? updatedAt;
  final Map<String, dynamic> metadata;
  final String displayContent;

  String? get documentType => metadata['document_type']?.toString();
  String? get sourceSection => metadata['source_section']?.toString();
  String? get officialSourceExcerpt =>
      metadata['official_source_excerpt']?.toString().trim().isNotEmpty == true
          ? metadata['official_source_excerpt']?.toString()
          : metadata['source_excerpt']?.toString().trim().isNotEmpty == true
              ? metadata['source_excerpt']?.toString()
              : null;
  List<Map<String, String>> get contentSections {
    final raw = metadata['content_sections'];
    if (raw is! List) return const [];
    return raw
        .whereType<Map>()
        .map((section) => {
              'heading': section['heading']?.toString() ?? '',
              'body': section['body']?.toString() ?? '',
            })
        .where((section) => section['heading']!.isNotEmpty)
        .toList();
  }
  double? get qualityScore => _readDouble(metadata['quality_score']);
  double? get categoryConfidence => _readDouble(metadata['category_confidence']);
  double? get studentUsefulnessScore =>
      _readDouble(metadata['student_usefulness_score']);
  bool get needsReview => metadata['needs_review'] == true;
  List<String> get reviewReasons => _readStringList(metadata['review_reason']);

  ArticleReviewBucket get reviewBucket {
    if (published) {
      return ArticleReviewBucket.published;
    }
    if (needsReview || reviewReasons.isNotEmpty) {
      return ArticleReviewBucket.needsReview;
    }
    final quality = qualityScore ?? 0;
    final confidence = categoryConfidence ?? 0;
    final usefulness = studentUsefulnessScore ?? 0;
    if (quality >= 7.0 && confidence >= 0.45 && usefulness >= 0) {
      return ArticleReviewBucket.recommended;
    }
    return ArticleReviewBucket.overflow;
  }

  factory AdminArticle.fromJson(Map<String, dynamic> json) {
    final rawContent = json['content']?.toString();
    final parsed = _parseArticleContent(rawContent);
    return AdminArticle(
      id: json['id']?.toString() ?? '',
      title: json['title']?.toString() ?? 'Untitled',
      category: json['category']?.toString() ?? 'General Information',
      published: json['published'] == true,
      slug: json['slug']?.toString(),
      summary: json['summary']?.toString(),
      content: rawContent,
      office: json['office']?.toString(),
      sourceFilename: json['source_filename']?.toString(),
      chunkCount: _readInt(json['chunk_count']),
      publishedAt: json['published_at']?.toString(),
      createdAt: json['created_at']?.toString(),
      updatedAt: json['updated_at']?.toString(),
      metadata: parsed.metadata,
      displayContent: parsed.displayContent,
    );
  }

  /// Lightweight list/card payload: metadata and labels only, no article body.
  factory AdminArticle.fromListJson(Map<String, dynamic> json) {
    final rawContent = json['content']?.toString();
    return AdminArticle(
      id: json['id']?.toString() ?? '',
      title: json['title']?.toString() ?? 'Untitled',
      category: json['category']?.toString() ?? 'General Information',
      published: json['published'] == true,
      slug: json['slug']?.toString(),
      summary: json['summary']?.toString(),
      content: null,
      office: json['office']?.toString(),
      sourceFilename: json['source_filename']?.toString(),
      chunkCount: _readInt(json['chunk_count']),
      publishedAt: json['published_at']?.toString(),
      createdAt: json['created_at']?.toString(),
      updatedAt: json['updated_at']?.toString(),
      metadata: _parseMetadataOnly(rawContent),
      displayContent: '',
    );
  }

  bool get hasLoadedContent => (content ?? '').trim().isNotEmpty || displayContent.trim().isNotEmpty;

  Map<String, dynamic> toCreatePayload({bool publish = false}) {
    final plannerBucket = metadata['planner_bucket']?.toString();
    var body = content ?? '';
    const marker = '----EXTRACTED METADATA----';
    final embedded = <String, dynamic>{
      ...metadata,
      if (sourceFilename != null) 'source_filename': sourceFilename,
      if (documentType != null) 'document_type': documentType,
      'published_write': publish,
    };
    if (body.trim().isNotEmpty) {
      final markerIndex = body.indexOf(marker);
      if (markerIndex >= 0) {
        body = body.substring(0, markerIndex).trimRight();
      }
      body =
          '$body\n\n$marker\n${const JsonEncoder.withIndent('  ').convert(embedded)}';
    }
    return {
      'title': title,
      'category': category,
      'summary': summary,
      'content': body,
      if (office != null && office!.trim().isNotEmpty) 'office': office,
      if (sourceFilename != null && sourceFilename!.trim().isNotEmpty)
        'source_document': sourceFilename,
      if ((metadata['source_section'] ?? '').toString().trim().isNotEmpty)
        'source_section': metadata['source_section'].toString(),
      if ((metadata['document_type'] ?? documentType ?? '').toString().trim().isNotEmpty)
        'document_type': (metadata['document_type'] ?? documentType).toString(),
      'publish_status': publish,
      'needs_review': needsReview || metadata['needs_review'] == true,
      if (plannerBucket != null && plannerBucket.trim().isNotEmpty)
        'planner_bucket': plannerBucket.trim(),
    };
  }

  Map<String, dynamic> toUpdatePayload({
    String? title,
    String? category,
    String? summary,
    String? content,
    String? office,
    String? sourceFilename,
  }) {
    final payload = <String, dynamic>{};
    if (title != null) payload['title'] = title;
    if (category != null) payload['category'] = category;
    if (summary != null) payload['summary'] = summary;
    if (content != null) payload['content'] = content;
    if (office != null) payload['office'] = office;
    if (sourceFilename != null) payload['source_document'] = sourceFilename;
    return payload;
  }
}

/// Promote a Low Quality candidate into a manual review draft (never auto-recommended).
AdminArticle stampManualReviewFromLowQuality(AdminArticle article) {
  final meta = Map<String, dynamic>.from(article.metadata);
  meta['manual_review_from_low_quality'] = true;
  meta['original_bucket'] = 'low_quality';
  meta['review_status'] = 'manually_corrected_draft';
  meta['needs_review'] = true;
  meta['planner_bucket'] = 'needs_review';
  meta['final_bucket'] = 'needs_review';
  meta['ui_group_bucket'] = 'needs_review';
  meta['publish_allowed'] = false;
  meta['save_draft_allowed'] = true;

  const marker = '----EXTRACTED METADATA----';
  final raw = article.content ?? article.displayContent;
  var body = raw;
  final markerIndex = body.indexOf(marker);
  if (markerIndex >= 0) {
    body = body.substring(0, markerIndex).trimRight();
  } else {
    body = body.trimRight();
  }
  final embedded = <String, dynamic>{
    ...meta,
    if (article.sourceFilename != null) 'source_filename': article.sourceFilename,
  };
  final newContent =
      '$body\n\n$marker\n${const JsonEncoder.withIndent('  ').convert(embedded)}';

  return AdminArticle(
    id: article.id,
    title: article.title,
    category: article.category,
    published: false,
    slug: article.slug,
    summary: article.summary,
    content: newContent,
    office: article.office,
    sourceFilename: article.sourceFilename,
    chunkCount: article.chunkCount,
    publishedAt: article.publishedAt,
    createdAt: article.createdAt,
    updatedAt: article.updatedAt,
    metadata: meta,
    displayContent: cleanArticleContentForDisplay(body),
  );
}

class CandidateSummary {
  const CandidateSummary({
    required this.title,
    this.id,
    this.qualityScore,
    this.categoryConfidence,
    this.studentUsefulnessScore,
    this.needsReview = false,
    this.reviewReasons = const [],
    this.sourceSection,
    this.sourceSections = const [],
    this.documentType,
    this.articleType,
    this.category,
    this.summary,
    this.content,
    this.office,
    this.sourceFilename,
    this.groupName,
    this.groupType,
    this.parentTopic,
    this.canonicalTopic,
    this.mergedUnitCount,
    this.plannerBucket,
    this.finalBucket,
    this.rawBucket,
    this.charterCandidateBucket,
    this.uiGroupBucket,
    this.publishAllowed,
    this.saveDraftAllowed,
    this.bucketConsistencyCheck,
    this.consolidatedParent = false,
    this.isPreview = false,
    this.bucketReason,
    this.studentFacingScore,
    this.internalAdminScore,
    this.blockingReviewFlags = const [],
    this.parserUsed,
    this.formatterUsed,
    this.documentProfile,
    this.originalBucket,
    this.repairedBucket,
    this.rescueAttempted,
    this.rescueSuccessful,
    this.rescueReasons = const [],
    this.repairActionsApplied = const [],
    this.remainingBlockers = const [],
    this.needsReviewReasons = const [],
    this.existingArticleId,
    this.existingPublished,
    this.alreadyPublished,
    this.existingMatchReason,
  });

  final String? id;
  final String title;
  final double? qualityScore;
  final double? categoryConfidence;
  final double? studentUsefulnessScore;
  final bool needsReview;
  final List<String> reviewReasons;
  final String? sourceSection;
  final List<String> sourceSections;
  final String? documentType;
  final String? articleType;
  final String? category;
  final String? summary;
  final String? content;
  final String? office;
  final String? sourceFilename;
  final String? groupName;
  final String? groupType;
  final String? parentTopic;
  final String? canonicalTopic;
  final int? mergedUnitCount;
  final String? plannerBucket;
  final String? finalBucket;
  final String? rawBucket;
  final String? charterCandidateBucket;
  final String? uiGroupBucket;
  final bool? publishAllowed;
  final bool? saveDraftAllowed;
  final String? bucketConsistencyCheck;
  final bool consolidatedParent;
  final bool isPreview;
  final String? bucketReason;
  final double? studentFacingScore;
  final double? internalAdminScore;
  final List<String> blockingReviewFlags;
  final String? parserUsed;
  final String? formatterUsed;
  final String? documentProfile;
  final String? originalBucket;
  final String? repairedBucket;
  final bool? rescueAttempted;
  final bool? rescueSuccessful;
  final List<String> rescueReasons;
  final List<String> repairActionsApplied;
  final List<String> remainingBlockers;
  final List<String> needsReviewReasons;
  final String? existingArticleId;
  final bool? existingPublished;
  final bool? alreadyPublished;
  final String? existingMatchReason;

  bool get matchedExistingPublished =>
      alreadyPublished == true || existingPublished == true;

  bool get isUnsavedPreview =>
      !matchedExistingPublished && (isPreview || isPreviewCandidateId(id));

  factory CandidateSummary.fromJson(Map<String, dynamic> json) {
    final id = json['id']?.toString();
    return CandidateSummary(
      id: id,
      title: json['title']?.toString() ?? 'Untitled',
      qualityScore: _readDouble(json['quality_score']),
      categoryConfidence: _readDouble(json['category_confidence']),
      studentUsefulnessScore: _readDouble(json['student_usefulness_score']),
      needsReview: json['needs_review'] == true,
      reviewReasons: _readStringList(json['review_reason']),
      sourceSection: json['source_section']?.toString(),
      sourceSections: _readStringList(json['source_sections']),
      documentType: json['document_type']?.toString(),
      articleType: json['article_type']?.toString(),
      category: json['category']?.toString(),
      summary: json['summary']?.toString(),
      content: json['content']?.toString(),
      office: json['office']?.toString(),
      sourceFilename: json['source_filename']?.toString(),
      groupName: json['group_name']?.toString(),
      groupType: json['group_type']?.toString(),
      parentTopic: json['parent_topic']?.toString(),
      canonicalTopic: json['canonical_topic']?.toString(),
      mergedUnitCount: _readInt(json['merged_unit_count']),
      plannerBucket: json['planner_bucket']?.toString(),
      finalBucket: json['final_bucket']?.toString(),
      rawBucket: json['raw_bucket']?.toString(),
      charterCandidateBucket: json['charter_candidate_bucket']?.toString(),
      uiGroupBucket: json['ui_group_bucket']?.toString(),
      publishAllowed: json['publish_allowed'] is bool ? json['publish_allowed'] as bool : null,
      saveDraftAllowed:
          json['save_draft_allowed'] is bool ? json['save_draft_allowed'] as bool : null,
      bucketConsistencyCheck: json['bucket_consistency_check']?.toString(),
      consolidatedParent: json['consolidated_parent'] == true,
      isPreview: json['is_preview'] == true || isPreviewCandidateId(id),
      bucketReason: json['bucket_reason']?.toString(),
      studentFacingScore: _readDouble(json['student_facing_score']),
      internalAdminScore: _readDouble(json['internal_admin_score']),
      blockingReviewFlags: _readStringList(json['blocking_review_flags']),
      parserUsed: json['parser_used']?.toString(),
      formatterUsed: json['formatter_used']?.toString(),
      documentProfile: json['document_profile']?.toString(),
      originalBucket: json['original_bucket']?.toString(),
      repairedBucket: json['repaired_bucket']?.toString(),
      rescueAttempted: json['rescue_attempted'] is bool
          ? json['rescue_attempted'] as bool
          : null,
      rescueSuccessful: json['rescue_successful'] is bool
          ? json['rescue_successful'] as bool
          : null,
      rescueReasons: _readStringList(json['rescue_reasons']),
      repairActionsApplied: _readStringList(json['repair_actions_applied']),
      remainingBlockers: _readStringList(json['remaining_blockers']),
      needsReviewReasons: _readStringList(json['needs_review_reasons']),
      existingArticleId: json['existing_article_id']?.toString(),
      existingPublished: json['existing_published'] is bool
          ? json['existing_published'] as bool
          : null,
      alreadyPublished: json['already_published'] is bool
          ? json['already_published'] as bool
          : null,
      existingMatchReason: json['existing_match_reason']?.toString(),
    );
  }

  /// Prefer rescue blockers / needs-review reasons when present.
  List<String> get displayReviewReasons {
    final merged = <String>[];
    for (final reason in [
      ...needsReviewReasons,
      ...remainingBlockers,
      ...reviewReasons,
    ]) {
      final trimmed = reason.trim();
      if (trimmed.isEmpty || merged.contains(trimmed)) continue;
      merged.add(trimmed);
    }
    return merged;
  }

  AdminArticle toPreviewArticle() {
    final rawContent = content ?? '';
    final parsed = rawContent.contains('----EXTRACTED METADATA----')
        ? _parseArticleContent(rawContent)
        : _ParsedArticleContent(
            displayContent: cleanArticleContentForDisplay(rawContent),
            metadata: {
              if (documentType != null) 'document_type': documentType,
              if (articleType != null) 'article_type': articleType,
              if (sourceSection != null) 'source_section': sourceSection,
              if (sourceSections.isNotEmpty) 'source_sections': sourceSections,
              if (sourceFilename != null) 'source_filename': sourceFilename,
              if (groupName != null) 'group_name': groupName,
              if (groupType != null) 'group_type': groupType,
              if (parentTopic != null) 'parent_topic': parentTopic,
              if (canonicalTopic != null) 'canonical_topic': canonicalTopic,
              if (mergedUnitCount != null) 'merged_unit_count': mergedUnitCount,
              if (plannerBucket != null) 'planner_bucket': plannerBucket,
              if (finalBucket != null) 'final_bucket': finalBucket,
              if (rawBucket != null) 'raw_bucket': rawBucket,
              if (charterCandidateBucket != null)
                'charter_candidate_bucket': charterCandidateBucket,
              if (uiGroupBucket != null) 'ui_group_bucket': uiGroupBucket,
              if (publishAllowed != null) 'publish_allowed': publishAllowed,
              if (saveDraftAllowed != null) 'save_draft_allowed': saveDraftAllowed,
              if (bucketConsistencyCheck != null)
                'bucket_consistency_check': bucketConsistencyCheck,
              if (consolidatedParent) 'consolidated_parent': true,
              if (qualityScore != null) 'quality_score': qualityScore,
              if (categoryConfidence != null) 'category_confidence': categoryConfidence,
              if (studentUsefulnessScore != null)
                'student_usefulness_score': studentUsefulnessScore,
              'needs_review': needsReview,
              'review_reason': reviewReasons,
              if (bucketReason != null) 'bucket_reason': bucketReason,
              if (studentFacingScore != null) 'student_facing_score': studentFacingScore,
              if (internalAdminScore != null) 'internal_admin_score': internalAdminScore,
              if (blockingReviewFlags.isNotEmpty)
                'blocking_review_flags': blockingReviewFlags,
              if (parserUsed != null) 'parser_used': parserUsed,
              if (formatterUsed != null) 'formatter_used': formatterUsed,
              if (documentProfile != null) 'document_profile': documentProfile,
              if (originalBucket != null) 'original_bucket': originalBucket,
              if (repairedBucket != null) 'repaired_bucket': repairedBucket,
              if (rescueAttempted != null) 'rescue_attempted': rescueAttempted,
              if (rescueSuccessful != null) 'rescue_successful': rescueSuccessful,
              if (rescueReasons.isNotEmpty) 'rescue_reasons': rescueReasons,
              if (repairActionsApplied.isNotEmpty)
                'repair_actions_applied': repairActionsApplied,
              if (remainingBlockers.isNotEmpty)
                'remaining_blockers': remainingBlockers,
              if (needsReviewReasons.isNotEmpty)
                'needs_review_reasons': needsReviewReasons,
              if (displayReviewReasons.isNotEmpty)
                'review_reason': displayReviewReasons,
            },
          );
    return AdminArticle(
      id: (matchedExistingPublished ? (existingArticleId ?? id) : id) ?? '',
      title: title,
      category: category ?? 'General Information',
      published: matchedExistingPublished,
      summary: summary,
      content: rawContent.isEmpty ? null : rawContent,
      office: office,
      sourceFilename: sourceFilename,
      metadata: {
        ...parsed.metadata,
        if (existingArticleId != null) 'existing_article_id': existingArticleId,
        if (existingPublished != null) 'existing_published': existingPublished,
        if (alreadyPublished != null) 'already_published': alreadyPublished,
        if (existingMatchReason != null) 'existing_match_reason': existingMatchReason,
      },
      displayContent: parsed.displayContent,
    );
  }
}

bool isPreviewCandidateId(String? id) {
  final value = (id ?? '').trim();
  return value.startsWith('preview-');
}

class BulkArticleActionResult {
  const BulkArticleActionResult({
    required this.successCount,
    required this.failureCount,
    required this.results,
  });

  final int successCount;
  final int failureCount;
  final List<BulkArticleActionItemResult> results;

  factory BulkArticleActionResult.fromJson(Map<String, dynamic> json) {
    final rawResults = json['results'];
    return BulkArticleActionResult(
      successCount: _readInt(json['success_count']) ?? 0,
      failureCount: _readInt(json['failure_count']) ?? 0,
      results: rawResults is List
          ? rawResults
              .whereType<Map>()
              .map(
                (item) => BulkArticleActionItemResult.fromJson(
                  Map<String, dynamic>.from(item),
                ),
              )
              .toList()
          : const [],
    );
  }
}

class BulkArticleActionItemResult {
  const BulkArticleActionItemResult({
    this.previewId,
    required this.success,
    this.id,
    this.title,
    this.published,
    this.error,
    this.code,
    this.existing,
  });

  final String? previewId;
  final bool success;
  final String? id;
  final String? title;
  final bool? published;
  final String? error;
  final String? code;
  final Map<String, dynamic>? existing;

  factory BulkArticleActionItemResult.fromJson(Map<String, dynamic> json) {
    final existing = json['existing'];
    return BulkArticleActionItemResult(
      previewId: json['preview_id']?.toString(),
      success: json['success'] == true,
      id: json['id']?.toString(),
      title: json['title']?.toString(),
      published: json['published'] is bool ? json['published'] as bool : null,
      error: json['error']?.toString(),
      code: json['code']?.toString(),
      existing: existing is Map
          ? Map<String, dynamic>.from(existing)
          : null,
    );
  }
}

class CandidateReviewGroup {
  const CandidateReviewGroup({
    required this.groupName,
    required this.groupType,
    required this.totalCount,
    required this.recommendedCount,
    required this.needsReviewCount,
    required this.lowConfidenceCount,
    required this.duplicateCount,
    this.candidates = const [],
  });

  final String groupName;
  final String groupType;
  final int totalCount;
  final int recommendedCount;
  final int needsReviewCount;
  final int lowConfidenceCount;
  final int duplicateCount;
  final List<CandidateSummary> candidates;

  factory CandidateReviewGroup.fromJson(Map<String, dynamic> json) {
    final candidates = json['candidates'];
    return CandidateReviewGroup(
      groupName: json['group_name']?.toString() ?? 'Uncategorized',
      groupType: json['group_type']?.toString() ?? 'uncategorized',
      totalCount: _readInt(json['total_count']) ?? 0,
      recommendedCount: _readInt(json['recommended_count']) ?? 0,
      needsReviewCount: _readInt(json['needs_review_count']) ?? 0,
      lowConfidenceCount: _readInt(json['low_confidence_count']) ?? 0,
      duplicateCount: _readInt(json['duplicate_count']) ?? 0,
      candidates: candidates is List
          ? candidates
              .whereType<Map>()
              .map((item) => CandidateSummary.fromJson(Map<String, dynamic>.from(item)))
              .toList()
          : const [],
    );
  }
}

class CoverageTopic {
  const CoverageTopic({
    required this.parentTopic,
    required this.canonicalTopic,
    required this.unitCount,
    required this.status,
    this.blueprintId,
    this.sourceSection,
    this.reason,
  });

  final String parentTopic;
  final String canonicalTopic;
  final int unitCount;
  final String status;
  final String? blueprintId;
  final String? sourceSection;
  final String? reason;

  factory CoverageTopic.fromJson(Map<String, dynamic> json) {
    return CoverageTopic(
      parentTopic: json['parent_topic']?.toString() ?? 'General',
      canonicalTopic: json['canonical_topic']?.toString() ?? 'General Information',
      unitCount: _readInt(json['unit_count']) ?? 0,
      status: json['status']?.toString() ?? 'needs_cleanup',
      blueprintId: json['blueprint_id']?.toString(),
      sourceSection: json['source_section']?.toString(),
      reason: json['reason']?.toString(),
    );
  }
}

class CharterGenerationReport {
  const CharterGenerationReport({
    required this.totalDetectedServiceBlocks,
    required this.mergedSplitServices,
    required this.recommendedServices,
    required this.needsReviewServices,
    required this.lowQualityArtifactsDropped,
    required this.ragOnlyReferences,
    this.validServiceBlocks = 0,
    this.rejectedArtifactHeadings = 0,
    this.rejectedMixedServiceBlocks = 0,
    this.rejectedIncompleteBlocks = 0,
    this.documentProfile,
    this.parserUsed,
    this.reviewTextLength = 0,
    this.knowledgeUnitsCount = 0,
    this.generatedArticleCandidates = 0,
    this.v2Used = false,
    this.v2ServicesDetected = 0,
    this.v2CleanCount = 0,
    this.v2NeedsReviewCount = 0,
    this.v2LowQualityCount = 0,
    this.v2RagOnlyCount = 0,
    this.v2FallbackUsed = false,
    this.v2ParserStrategyCounts = const {},
    this.v2Attempted = false,
    this.pdfPagesAvailable = false,
    this.pdfPagesCount = 0,
    this.pagesWithWordsCount = 0,
    this.totalWordsCount = 0,
    this.previewHasCharterV2Services = false,
    this.previewCharterV2ServicesCount = 0,
    this.generateReceivedCharterV2ServicesCount = 0,
    this.v2ErrorMessage,
    this.fallbackReason,
    this.rescueAttempted = 0,
    this.rescueSuccessful = 0,
    this.promotedToRecommendedAfterRepair = 0,
    this.downgradedAfterSemanticValidation = 0,
    this.internalServicesKeptAsNeedsReviewOrRagOnly = 0,
    this.trueLowQualityFragments = 0,
    this.repairedButNotPromoted = 0,
    this.repairFailed = 0,
    this.semanticValidationFailed = 0,
    this.recommendedBlockedBySemanticValidation = 0,
    this.lowQualityRescueAttempted = 0,
    this.lowQualityRescueSuccessful = 0,
    this.lowQualityRepairAttempted = 0,
    this.lowQualityRepairChangedFields = 0,
    this.lowQualityRescuedToNeedsReview = 0,
    this.lowQualityRescuedToRecommended = 0,
    this.lowQualityRepairFailed = 0,
    this.publicPriorityFound = 0,
    this.publicPriorityRecommended = 0,
    this.publicPriorityNeedsReview = 0,
    this.publicPriorityLowQuality = 0,
    this.publicPriorityRepaired = 0,
    this.publicPriorityBlockedByArticleBody = 0,
    this.priorityServiceDiagnostics = const [],
  });

  final int totalDetectedServiceBlocks;
  final int mergedSplitServices;
  final int recommendedServices;
  final int needsReviewServices;
  final int lowQualityArtifactsDropped;
  final int ragOnlyReferences;
  final int validServiceBlocks;
  final int rejectedArtifactHeadings;
  final int rejectedMixedServiceBlocks;
  final int rejectedIncompleteBlocks;
  final String? documentProfile;
  final String? parserUsed;
  final int reviewTextLength;
  final int knowledgeUnitsCount;
  final int generatedArticleCandidates;
  // Citizen's Charter Extraction V2 fields (see citizen_charter_extractor_v2.py).
  final bool v2Used;
  final int v2ServicesDetected;
  final int v2CleanCount;
  final int v2NeedsReviewCount;
  final int v2LowQualityCount;
  final int v2RagOnlyCount;
  final bool v2FallbackUsed;
  final Map<String, int> v2ParserStrategyCounts;
  final bool v2Attempted;
  final bool pdfPagesAvailable;
  final int pdfPagesCount;
  final int pagesWithWordsCount;
  final int totalWordsCount;
  final bool previewHasCharterV2Services;
  final int previewCharterV2ServicesCount;
  final int generateReceivedCharterV2ServicesCount;
  final String? v2ErrorMessage;
  final String? fallbackReason;
  final int rescueAttempted;
  final int rescueSuccessful;
  final int promotedToRecommendedAfterRepair;
  final int downgradedAfterSemanticValidation;
  final int internalServicesKeptAsNeedsReviewOrRagOnly;
  final int trueLowQualityFragments;
  final int repairedButNotPromoted;
  final int repairFailed;
  final int semanticValidationFailed;
  final int recommendedBlockedBySemanticValidation;
  final int lowQualityRescueAttempted;
  final int lowQualityRescueSuccessful;
  final int lowQualityRepairAttempted;
  final int lowQualityRepairChangedFields;
  final int lowQualityRescuedToNeedsReview;
  final int lowQualityRescuedToRecommended;
  final int lowQualityRepairFailed;
  final int publicPriorityFound;
  final int publicPriorityRecommended;
  final int publicPriorityNeedsReview;
  final int publicPriorityLowQuality;
  final int publicPriorityRepaired;
  final int publicPriorityBlockedByArticleBody;
  final List<Map<String, dynamic>> priorityServiceDiagnostics;

  factory CharterGenerationReport.fromJson(Map<String, dynamic> json) {
    final rawStrategyCounts = json['v2_parser_strategy_counts'];
    final strategyCounts = <String, int>{};
    if (rawStrategyCounts is Map) {
      for (final entry in rawStrategyCounts.entries) {
        strategyCounts[entry.key.toString()] = _readInt(entry.value) ?? 0;
      }
    }
    return CharterGenerationReport(
      totalDetectedServiceBlocks: _readInt(json['total_detected_service_blocks']) ?? 0,
      mergedSplitServices: _readInt(json['merged_split_services']) ?? 0,
      recommendedServices: _readInt(json['recommended_services']) ?? 0,
      needsReviewServices: _readInt(json['needs_review_services']) ?? 0,
      lowQualityArtifactsDropped: _readInt(json['low_quality_artifacts_dropped']) ?? 0,
      ragOnlyReferences: _readInt(json['rag_only_references']) ?? 0,
      validServiceBlocks: _readInt(json['valid_service_blocks']) ?? 0,
      rejectedArtifactHeadings: _readInt(json['rejected_artifact_headings']) ?? 0,
      rejectedMixedServiceBlocks: _readInt(json['rejected_mixed_service_blocks']) ?? 0,
      rejectedIncompleteBlocks: _readInt(json['rejected_incomplete_blocks']) ?? 0,
      documentProfile: json['document_profile']?.toString(),
      parserUsed: json['parser_used']?.toString(),
      reviewTextLength: _readInt(json['review_text_length']) ?? 0,
      knowledgeUnitsCount: _readInt(json['knowledge_units_count']) ?? 0,
      generatedArticleCandidates: _readInt(json['generated_article_candidates']) ?? 0,
      v2Used: json['v2_used'] == true,
      v2ServicesDetected: _readInt(json['v2_services_detected']) ?? 0,
      v2CleanCount: _readInt(json['v2_clean_count']) ?? 0,
      v2NeedsReviewCount: _readInt(json['v2_needs_review_count']) ?? 0,
      v2LowQualityCount: _readInt(json['v2_low_quality_count']) ?? 0,
      v2RagOnlyCount: _readInt(json['v2_rag_only_count']) ?? 0,
      v2FallbackUsed: json['v2_fallback_used'] == true,
      v2ParserStrategyCounts: strategyCounts,
      v2Attempted: json['v2_attempted'] == true,
      pdfPagesAvailable: json['pdf_pages_available'] == true,
      pdfPagesCount: _readInt(json['pdf_pages_count']) ?? 0,
      pagesWithWordsCount: _readInt(json['pages_with_words_count']) ?? 0,
      totalWordsCount: _readInt(json['total_words_count']) ?? 0,
      previewHasCharterV2Services: json['preview_has_charter_v2_services'] == true,
      previewCharterV2ServicesCount:
          _readInt(json['preview_charter_v2_services_count']) ?? 0,
      generateReceivedCharterV2ServicesCount:
          _readInt(json['generate_received_charter_v2_services_count']) ?? 0,
      v2ErrorMessage: json['v2_error_message']?.toString(),
      fallbackReason: json['fallback_reason']?.toString(),
      rescueAttempted: _readInt(json['rescue_attempted']) ?? 0,
      rescueSuccessful: _readInt(json['rescue_successful']) ?? 0,
      promotedToRecommendedAfterRepair:
          _readInt(json['promoted_to_recommended_after_repair']) ?? 0,
      downgradedAfterSemanticValidation:
          _readInt(json['downgraded_after_semantic_validation']) ?? 0,
      internalServicesKeptAsNeedsReviewOrRagOnly:
          _readInt(json['internal_services_kept_as_needs_review_or_rag_only']) ??
              0,
      trueLowQualityFragments: _readInt(json['true_low_quality_fragments']) ?? 0,
      repairedButNotPromoted: _readInt(json['repaired_but_not_promoted']) ?? 0,
      repairFailed: _readInt(json['repair_failed']) ?? 0,
      semanticValidationFailed: _readInt(json['semantic_validation_failed']) ?? 0,
      recommendedBlockedBySemanticValidation:
          _readInt(json['recommended_blocked_by_semantic_validation']) ?? 0,
      lowQualityRescueAttempted:
          _readInt(json['low_quality_repair_attempted']) ??
              _readInt(json['low_quality_rescue_attempted']) ??
              0,
      lowQualityRescueSuccessful:
          _readInt(json['low_quality_rescue_successful']) ??
              (
                (_readInt(json['low_quality_rescued_to_needs_review']) ?? 0) +
                (_readInt(json['low_quality_rescued_to_recommended']) ?? 0)
              ),
      lowQualityRepairAttempted:
          _readInt(json['low_quality_repair_attempted']) ??
              _readInt(json['low_quality_rescue_attempted']) ??
              0,
      lowQualityRepairChangedFields:
          _readInt(json['low_quality_repair_changed_fields']) ?? 0,
      lowQualityRescuedToNeedsReview:
          _readInt(json['low_quality_rescued_to_needs_review']) ?? 0,
      lowQualityRescuedToRecommended:
          _readInt(json['low_quality_rescued_to_recommended']) ?? 0,
      lowQualityRepairFailed: _readInt(json['low_quality_repair_failed']) ?? 0,
      publicPriorityFound: _readInt(json['public_priority_found']) ?? 0,
      publicPriorityRecommended: _readInt(json['public_priority_recommended']) ?? 0,
      publicPriorityNeedsReview: _readInt(json['public_priority_needs_review']) ?? 0,
      publicPriorityLowQuality: _readInt(json['public_priority_low_quality']) ?? 0,
      publicPriorityRepaired: _readInt(json['public_priority_repaired']) ?? 0,
      publicPriorityBlockedByArticleBody:
          _readInt(json['public_priority_blocked_by_article_body']) ?? 0,
      priorityServiceDiagnostics: () {
        final raw = json['priority_service_diagnostics'];
        if (raw is! List) return const <Map<String, dynamic>>[];
        return raw
            .whereType<Map>()
            .map((item) => Map<String, dynamic>.from(item))
            .toList();
      }(),
    );
  }
}

class CandidateGenerationResult {
  const CandidateGenerationResult({
    required this.totalDetected,
    required this.recommendedCount,
    required this.overflowCount,
    required this.skippedLowQualityCount,
    required this.skippedDuplicateCount,
    required this.needsReviewCount,
    required this.createdCount,
    this.previewCount = 0,
    this.blueprintCount = 0,
    this.articleEligibleCount = 0,
    this.ragOnlyCount = 0,
    this.consolidatedParentCount = 0,
    this.recommendedCandidates = const [],
    this.needsReviewCandidates = const [],
    this.overflowCandidates = const [],
    this.lowConfidenceCandidates = const [],
    this.consolidatedParentCandidates = const [],
    this.skippedDuplicates = const [],
    this.allCandidates = const [],
    this.groupedCandidates = const [],
    this.coverage = const [],
    this.coverageCounts = const {},
    this.charterReport,
  });

  final int totalDetected;
  final int recommendedCount;
  final int overflowCount;
  final int skippedLowQualityCount;
  final int skippedDuplicateCount;
  final int needsReviewCount;
  final int createdCount;
  final int previewCount;
  final int blueprintCount;
  final int articleEligibleCount;
  final int ragOnlyCount;
  final int consolidatedParentCount;
  final List<CandidateSummary> recommendedCandidates;
  final List<CandidateSummary> needsReviewCandidates;
  final List<CandidateSummary> overflowCandidates;
  final List<CandidateSummary> lowConfidenceCandidates;
  final List<CandidateSummary> consolidatedParentCandidates;
  final List<CandidateSummary> skippedDuplicates;
  final List<CandidateSummary> allCandidates;
  final List<CandidateReviewGroup> groupedCandidates;
  final List<CoverageTopic> coverage;
  final Map<String, int> coverageCounts;
  final CharterGenerationReport? charterReport;

  factory CandidateGenerationResult.fromJson(Map<String, dynamic> json) {
    List<CandidateSummary> readList(String key) {
      final value = json[key];
      if (value is! List) return const [];
      return value
          .whereType<Map>()
          .map((item) => CandidateSummary.fromJson(Map<String, dynamic>.from(item)))
          .toList();
    }

    List<CoverageTopic> readCoverage(String key) {
      final value = json[key];
      if (value is! List) return const [];
      return value
          .whereType<Map>()
          .map((item) => CoverageTopic.fromJson(Map<String, dynamic>.from(item)))
          .toList();
    }

    CharterGenerationReport? charterReport;
    final rawReport = json['charter_report'];
    if (rawReport is Map) {
      charterReport = CharterGenerationReport.fromJson(Map<String, dynamic>.from(rawReport));
    }

    return CandidateGenerationResult(
      totalDetected: _readInt(json['total_detected']) ?? 0,
      recommendedCount: _readInt(json['recommended_count']) ?? 0,
      overflowCount: _readInt(json['overflow_count']) ?? 0,
      skippedLowQualityCount: _readInt(json['skipped_low_quality_count']) ?? 0,
      skippedDuplicateCount: _readInt(json['skipped_duplicate_count']) ?? 0,
      needsReviewCount: _readInt(json['needs_review_count']) ?? 0,
      createdCount: _readInt(json['created_count']) ?? 0,
      previewCount: _readInt(json['preview_count']) ?? _readInt(json['created_count']) ?? 0,
      blueprintCount: _readInt(json['blueprint_count']) ?? 0,
      articleEligibleCount: _readInt(json['article_eligible_count']) ?? 0,
      ragOnlyCount: _readInt(json['rag_only_count']) ?? 0,
      consolidatedParentCount: _readInt(json['consolidated_parent_count']) ?? 0,
      recommendedCandidates: readList('recommended_candidates'),
      needsReviewCandidates: readList('needs_review_candidates'),
      overflowCandidates: readList('overflow_candidates'),
      lowConfidenceCandidates: readList('low_confidence_candidates'),
      consolidatedParentCandidates: readList('consolidated_parent_candidates'),
      skippedDuplicates: readList('skipped_duplicates'),
      allCandidates: readList('all_candidates').isNotEmpty
          ? readList('all_candidates')
          : [
              ...readList('recommended_candidates'),
              ...readList('overflow_candidates'),
              ...readList('needs_review_candidates'),
              ...readList('low_confidence_candidates'),
            ],
      groupedCandidates: _readGroupList(json['grouped_candidates']).isNotEmpty
          ? _readGroupList(json['grouped_candidates'])
          : _readGroupList(json['groups']),
      coverage: readCoverage('coverage'),
      coverageCounts: _readCoverageCounts(json['coverage_counts']),
      charterReport: charterReport,
    );
  }

  static Map<String, int> _readCoverageCounts(dynamic value) {
    if (value is! Map) return const {};
    final counts = <String, int>{};
    value.forEach((key, raw) {
      final parsed = _readInt(raw);
      if (parsed != null) counts[key.toString()] = parsed;
    });
    return counts;
  }

  static List<CandidateReviewGroup> _readGroupList(dynamic value) {
    if (value is! List) return const [];
    return value
        .whereType<Map>()
        .map((item) => CandidateReviewGroup.fromJson(Map<String, dynamic>.from(item)))
        .toList();
  }
}

class _ParsedArticleContent {
  const _ParsedArticleContent({
    required this.displayContent,
    required this.metadata,
  });

  final String displayContent;
  final Map<String, dynamic> metadata;
}

_ParsedArticleContent _parseArticleContent(String? rawContent) {
  if (rawContent == null || rawContent.trim().isEmpty) {
    return const _ParsedArticleContent(displayContent: '', metadata: {});
  }

  const marker = '----EXTRACTED METADATA----';
  var body = rawContent;
  Map<String, dynamic> metadata = {};

  final markerIndex = body.indexOf(marker);
  if (markerIndex >= 0) {
    final metaText = body.substring(markerIndex + marker.length).trim();
    body = body.substring(0, markerIndex).trimRight();
    try {
      final decoded = jsonDecode(metaText);
      if (decoded is Map) {
        metadata = Map<String, dynamic>.from(decoded);
      }
    } catch (_) {}
  }

  final rawMarker = RegExp(r'^\s*Raw Extraction:\s*$', multiLine: true, caseSensitive: false);
  final rawMatch = rawMarker.firstMatch(body);
  if (rawMatch != null) {
    body = body.substring(0, rawMatch.start).trimRight();
  }

  return _ParsedArticleContent(displayContent: cleanArticleContentForDisplay(body.trim()), metadata: metadata);
}

Map<String, dynamic> _parseMetadataOnly(String? rawContent) {
  if (rawContent == null || rawContent.trim().isEmpty) {
    return {};
  }
  const marker = '----EXTRACTED METADATA----';
  final markerIndex = rawContent.indexOf(marker);
  if (markerIndex < 0) {
    return {};
  }
  try {
    final decoded = jsonDecode(rawContent.substring(markerIndex + marker.length).trim());
    if (decoded is Map) {
      return Map<String, dynamic>.from(decoded);
    }
  } catch (_) {}
  return {};
}

String normalizeArticleText(String value) {
  return value.replaceAll(RegExp(r'\s+'), ' ').trim().toLowerCase();
}

final RegExp _numberedClausePrefix = RegExp(
  r'^\s*(?:\d+(?:\.\d+)+|\d+[\.\)]|[ivxlc]+\.|[a-z]\))\s+',
  caseSensitive: false,
);

String cleanArticleContentForDisplay(String text) {
  if (text.trim().isEmpty) return '';

  var cleaned = text.replaceAll('\r\n', '\n').replaceAll('\r', '\n');
  cleaned = cleaned.replaceAllMapped(
    RegExp(r'([A-Za-z])-\n([A-Za-z])'),
    (match) => '${match.group(1)}${match.group(2)}',
  );
  cleaned = cleaned.replaceAllMapped(
    RegExp(r'([a-z])-\s+([a-z]{2,})', caseSensitive: false),
    (match) => '${match.group(1)}${match.group(2)}',
  );

  final lines = cleaned
      .split('\n')
      .map((line) => line.replaceAll(RegExp(r'[ \t]+'), ' ').trim())
      .toList();
  cleaned = lines.join('\n');
  cleaned = cleaned.replaceAll(RegExp(r'\n{3,}'), '\n\n');
  return cleaned.trim();
}

List<String> splitArticleSentences(String text) {
  final normalized = text.replaceAll(RegExp(r'\s+'), ' ').trim();
  if (normalized.isEmpty) return const [];
  return normalized
      .split(RegExp(r'(?<=[.!?])\s+(?=[A-Z"(])'))
      .map((part) => part.trim())
      .where((part) => part.isNotEmpty)
      .toList();
}

String stripLeadingNumberedClause(String text) {
  var stripped = text.trim();
  while (stripped.isNotEmpty) {
    final updated = stripped.replaceFirst(_numberedClausePrefix, '').trim();
    if (updated == stripped) break;
    stripped = updated;
  }
  return stripped;
}

String trimSummaryLength(String text, {int maxChars = 350}) {
  final trimmed = text.trim();
  if (trimmed.length <= maxChars) return trimmed;

  final truncated = trimmed.substring(0, maxChars);
  final lastStop = [
    truncated.lastIndexOf('.'),
    truncated.lastIndexOf('!'),
    truncated.lastIndexOf('?'),
  ].reduce((a, b) => a > b ? a : b);

  if (lastStop >= maxChars ~/ 3) {
    return truncated.substring(0, lastStop + 1).trim();
  }

  final words = truncated.trimRight().split(' ');
  if (words.length <= 1) return truncated.trim();
  return words.sublist(0, words.length - 1).join(' ');
}

final RegExp _numberedClauseToken = RegExp(r'\b\d+(?:\.\d+)*\s*[.)]');

bool containsNumberedClause(String text) {
  return _numberedClauseToken.hasMatch(text);
}

bool summariesOverlap(String summary, String content) {
  final normSummary = normalizeArticleText(summary);
  final normContent = normalizeArticleText(content);
  if (normSummary.isEmpty || normContent.isEmpty) return false;
  if (normSummary == normContent) return true;
  if (normContent.startsWith(normSummary) &&
      normSummary.length >= (normContent.length * 0.6).round()) {
    return true;
  }
  final compareLength = normContent.length < 240 ? normContent.length : 240;
  if (normSummary.startsWith(normContent.substring(0, compareLength))) {
    return true;
  }
  return false;
}

String extractiveArticleSummary(String content) {
  final sentences = splitArticleSentences(content);
  final picked = <String>[];
  for (final sentence in sentences) {
    final candidate = stripLeadingNumberedClause(sentence);
    if (candidate.isEmpty) continue;
    if (candidate.length < 12 && picked.isEmpty) continue;
    picked.add(candidate);
    if (picked.length >= 2) break;
  }

  if (picked.isEmpty) {
    final firstLine = content.split('\n').first.trim();
    final fallback = stripLeadingNumberedClause(firstLine);
    if (fallback.isNotEmpty) picked.add(fallback);
  }

  return _ensureShorterThanContent(trimSummaryLength(picked.take(2).join(' ')), content);
}

class _ConceptPhrase {
  const _ConceptPhrase(this.pattern, this.label);
  final String pattern;
  final String label;
}

const List<_ConceptPhrase> _conceptPhrases = [
  _ConceptPhrase('face-to-face counseling', 'face-to-face counseling'),
  _ConceptPhrase('face to face counseling', 'face-to-face counseling'),
  _ConceptPhrase('virtual counseling', 'virtual counseling'),
  _ConceptPhrase('admission requirements', 'admission requirements'),
  _ConceptPhrase('follow-up', 'follow-up'),
  _ConceptPhrase('follow up', 'follow-up'),
  _ConceptPhrase('case conference', 'case conferences'),
  _ConceptPhrase('face-to-face', 'face-to-face counseling'),
  _ConceptPhrase('face to face', 'face-to-face counseling'),
  _ConceptPhrase('consultation', 'consultation'),
  _ConceptPhrase('conference', 'conference'),
  _ConceptPhrase('referral', 'referral'),
  _ConceptPhrase('requirements', 'requirements'),
  _ConceptPhrase('requirement', 'requirements'),
  _ConceptPhrase('procedure', 'procedure'),
  _ConceptPhrase('submission', 'submission'),
  _ConceptPhrase('deadline', 'deadlines'),
  _ConceptPhrase('eligibility', 'eligibility'),
  _ConceptPhrase('documents', 'documents'),
  _ConceptPhrase('services', 'services'),
  _ConceptPhrase('policy', 'policy'),
  _ConceptPhrase('process', 'process'),
  _ConceptPhrase('steps', 'steps'),
];

const List<String> _procedureConceptPriority = [
  'referral',
  'follow-up',
  'consultation',
  'process',
  'steps',
  'procedure',
  'virtual counseling',
  'face-to-face counseling',
  'conference',
  'services',
];

const List<String> _procedureSignals = [
  'process',
  'procedure',
  'steps',
  'step',
  'follow-up',
  'follow up',
  'referral',
  'consultation',
  'how to',
  'session',
];

const List<String> _requirementSignals = [
  'form',
  'requirement',
  'requirements',
  'submit',
  'document',
  'deadline',
  'eligibility',
  'fill out',
  'application',
];

String _simplifyAwkwardPhrases(String text) {
  var updated = text.trim();
  updated = updated.replaceAll(RegExp(r'\bper se\b', caseSensitive: false), '');
  updated = updated.replaceAll(RegExp(r'\bherein\b', caseSensitive: false), '');
  updated =
      updated.replaceAll(RegExp(r'\baforementioned\b', caseSensitive: false), 'the');
  updated = updated.replaceAll(RegExp(r'\bthereof\b', caseSensitive: false), '');
  updated = updated.replaceAll(
    RegExp(r'\bfollow-?up counselee(?: with cases)?\b', caseSensitive: false),
    'follow-up assistance',
  );
  updated = updated.replaceAll(
    RegExp(r'\bcase conference\b', caseSensitive: false),
    'case conferences',
  );
  updated = updated.replaceAll(
    RegExp(
      r'\brefer(?:red)? if necessary to (?:a )?multidisciplinary team(?: of specialists)?\b',
      caseSensitive: false,
    ),
    'students may be referred to a multidisciplinary team when needed',
  );
  updated = updated.replaceAll(
    RegExp(
      r'\breferrals when needed to (?:a )?multidisciplinary team(?: of specialists)?\b',
      caseSensitive: false,
    ),
    'referrals to a multidisciplinary team when needed',
  );
  updated = updated.replaceAll(
    RegExp(r'\brefer(?:red)? if necessary\b', caseSensitive: false),
    'referral when needed',
  );
  updated = updated.replaceAll(RegExp(r'\s+([,.;])'), r'$1');
  updated = updated.replaceAll(RegExp(r'\s{2,}'), ' ');
  return updated.trim().replaceAll(RegExp(r'^[ ,;]+|[ ,;]+$'), '');
}

String _polishSupplementClause(String text) {
  var updated = _simplifyAwkwardPhrases(text);
  updated = updated.replaceAll(
    RegExp(
      r'\breferrals when needed to (?:a )?multidisciplinary team(?: of specialists)?\b',
      caseSensitive: false,
    ),
    'referrals to a multidisciplinary team when needed',
  );
  updated = updated.replaceAll(
    RegExp(
      r'\brefer(?:red)? if necessary to (?:a )?multidisciplinary team(?: of specialists)?\b',
      caseSensitive: false,
    ),
    'students may be referred to a multidisciplinary team when needed',
  );
  if (!updated.toLowerCase().contains('a multidisciplinary team')) {
    updated = updated.replaceAll(
      RegExp(r'\bmultidisciplinary team\b', caseSensitive: false),
      'a multidisciplinary team',
    );
  }
  updated = updated.replaceAll(
    RegExp(r'\ba a multidisciplinary team\b', caseSensitive: false),
    'a multidisciplinary team',
  );
  updated = updated.replaceAll(RegExp(r'\s{2,}'), ' ');
  return updated.trim().replaceAll(RegExp(r'^[ ,;]+|[ ,;]+$'), '');
}

bool _isIncompleteSupplement(String clause) {
  final normalized = clause.trim();
  if (normalized.isEmpty) return true;
  if (RegExp(r'\breferrals when needed to\b', caseSensitive: false).hasMatch(normalized)) {
    return true;
  }
  if (RegExp(r'\bwhen needed to (?:a )?multidisciplinary\b', caseSensitive: false)
      .hasMatch(normalized)) {
    return true;
  }
  if (RegExp(r'\breferral when needed to\b', caseSensitive: false).hasMatch(normalized)) {
    return true;
  }
  if (RegExp(r'\bto ensure\b', caseSensitive: false).hasMatch(normalized) &&
      normalized.toLowerCase().contains('referral')) {
    return true;
  }
  return false;
}

String? _wrapSupplementClause(String clause) {
  final polished = _polishSupplementClause(clause);
  if (polished.isEmpty || _isIncompleteSupplement(polished)) return null;
  if (polished.toLowerCase().startsWith('students ')) {
    return 'It also notes that $polished.';
  }
  final firstChar = polished.length > 1
      ? polished[0].toLowerCase() + polished.substring(1)
      : polished.toLowerCase();
  return 'It also notes that $firstChar.';
}

String _formatConceptList(List<String> concepts) {
  if (concepts.isEmpty) return '';
  if (concepts.length == 1) return concepts.first;
  if (concepts.length == 2) return '${concepts[0]} and ${concepts[1]}';
  return '${concepts.sublist(0, concepts.length - 1).join(', ')}, and ${concepts.last}';
}

List<String> _extractKeyConcepts(String content) {
  final lower = content.toLowerCase();
  final found = <String>[];
  final seen = <String>{};
  for (final entry in _conceptPhrases) {
    if (lower.contains(entry.pattern) && !seen.contains(entry.label)) {
      found.add(entry.label);
      seen.add(entry.label);
    }
  }
  if (seen.contains('case conferences') && seen.contains('conference')) {
    found.removeWhere((concept) => concept == 'conference');
  }
  return found;
}

String _titleSummaryPhrase(String title, String kind) {
  final lowered = title.toLowerCase();
  if (lowered.endsWith('services') || lowered.endsWith('service')) {
    return 'explains the support provided to students';
  }
  if (lowered.endsWith('process')) {
    return 'explains the process';
  }
  if (lowered.endsWith('policy')) {
    return 'explains the policy';
  }
  if (lowered.endsWith('procedure')) {
    return 'explains the procedure';
  }
  if (kind == 'requirement') {
    return 'describes the requirements and information students need';
  }
  if (kind == 'procedure') {
    return 'explains the steps students should follow';
  }
  return 'explains $lowered';
}

List<String> _prioritizeConcepts(List<String> concepts, String kind) {
  if (kind != 'procedure') return concepts;

  final ordered = <String>[];
  final remaining = List<String>.from(concepts);
  for (final preferred in _procedureConceptPriority) {
    for (final concept in List<String>.from(remaining)) {
      if (concept == preferred || concept.contains(preferred)) {
        ordered.add(concept);
        remaining.remove(concept);
      }
    }
  }
  ordered.addAll(remaining);
  return ordered;
}

String _ensureShorterThanContent(String summary, String content) {
  if (summary.isEmpty || content.isEmpty) return summary;
  if (summary.length < content.length) return summary;

  final sentences = splitArticleSentences(summary);
  if (sentences.length >= 2) {
    final budget = content.length - sentences[1].length - 6 > 80
        ? content.length - sentences[1].length - 6
        : 80;
    var trimmedFirst = trimSummaryLength(sentences.first, maxChars: budget);
    if (!trimmedFirst.endsWith('.') &&
        !trimmedFirst.endsWith('!') &&
        !trimmedFirst.endsWith('?')) {
      final clauseParts = trimmedFirst.split(', and ');
      if (clauseParts.length == 2 && clauseParts[0].length >= 60) {
        trimmedFirst = '${clauseParts[0]}.';
      } else {
        trimmedFirst = '${trimmedFirst.replaceAll(RegExp(r'[,; ]+$'), '')}.';
      }
    }
    final combined = '$trimmedFirst ${sentences[1]}'.trim();
    if (combined.isNotEmpty && combined.length < content.length) {
      return combined;
    }
  }

  if (sentences.isNotEmpty) {
    final oneSentence = trimSummaryLength(
      sentences.first,
      maxChars: content.length > 85 ? content.length - 5 : 80,
    );
    if (oneSentence.isNotEmpty && oneSentence.length < content.length) {
      return oneSentence;
    }
  }

  return trimSummaryLength(
    summary,
    maxChars: content.length > 85 ? content.length - 5 : 80,
  );
}

bool _isComposedSupplement(String supplement) {
  final lowered = supplement.toLowerCase();
  return lowered.contains('students may be referred to a multidisciplinary team') ||
      lowered.contains('virtual counseling follows similar principles');
}
String _detectArticleKind(String content, {String? documentType}) {
  final docType = (documentType ?? '').trim().toLowerCase();
  if (docType == 'requirement' || docType == 'procedure') return docType;
  if (docType == 'policy' || docType == 'handbook_policy') return 'policy';
  if (docType == 'information') return 'information';

  final lower = content.toLowerCase();
  if (lower.contains('policy') &&
      (lower.contains('shall') ||
          lower.contains('must') ||
          lower.contains('students'))) {
    return 'policy';
  }
  final requirementScore =
      _requirementSignals.where((signal) => lower.contains(signal)).length;
  final procedureScore =
      _procedureSignals.where((signal) => lower.contains(signal)).length;
  if (requirementScore >= 2 ||
      (lower.contains('form') && lower.contains('requirement'))) {
    return 'requirement';
  }
  if (procedureScore >= 1) return 'procedure';
  return 'information';
}

int _sentenceMentionsConcepts(String sentence, List<String> concepts) {
  final lower = sentence.toLowerCase();
  return concepts.where((concept) => lower.contains(concept.toLowerCase())).length;
}

bool _tooSimilarToOpening(String summary, String content) {
  final sentences = splitArticleSentences(content);
  if (sentences.isEmpty) return false;
  final opening =
      normalizeArticleText(stripLeadingNumberedClause(sentences.first));
  final normSummary = normalizeArticleText(summary);
  if (opening.isEmpty || normSummary.isEmpty) return false;
  if (opening.contains(normSummary) || normSummary.contains(opening)) {
    return true;
  }
  final openingWords = opening.split(' ').toSet();
  final summaryWords = normSummary.split(' ').toSet();
  if (openingWords.isEmpty) return false;
  final overlap =
      openingWords.intersection(summaryWords).length / openingWords.length;
  return overlap >= 0.72;
}

String? _composeComparisonNote(String content) {
  final lower = content.toLowerCase();
  final hasVirtual = lower.contains('virtual') && lower.contains('counsel');
  final hasFace =
      lower.contains('face-to-face') || lower.contains('face to face');
  final hasSimilarity = [
    'does not differ',
    'no different',
    'similar principles',
    'same principles',
    'same as',
    'similar to',
  ].any(lower.contains);
  if (hasVirtual && hasFace && hasSimilarity) {
    return 'It also notes that virtual counseling follows similar principles '
        'to face-to-face counseling.';
  }
  return null;
}

String? _composeReferralNote(String content) {
  final lower = content.toLowerCase();
  final hasTeam = lower.contains('multidisciplinary team') ||
      (lower.contains('multidisciplinary') && lower.contains('team'));
  final hasReferral = [
    'refer',
    'referral',
    'referred',
    'refer if necessary',
  ].any(lower.contains);
  if (!hasTeam || !hasReferral) return null;

  if (lower.contains('specialist') || lower.contains('special needs')) {
    return 'It also notes that students may be referred to a multidisciplinary team '
        'of specialists when additional support is needed.';
  }
  return 'It also notes that students may be referred to a multidisciplinary team '
      'when additional support is needed.';
}

String? _pickSupplementSentence(
  String content,
  List<String> concepts,
  List<String> usedConcepts,
) {
  final comparison = _composeComparisonNote(content);
  if (comparison != null) return comparison;

  final referral = _composeReferralNote(content);
  if (referral != null) return referral;

  final sentences = splitArticleSentences(content);
  int? bestScore;
  String? bestSentence;
  for (final sentence in sentences.skip(1)) {
    var cleaned = _polishSupplementClause(stripLeadingNumberedClause(sentence));
    if (cleaned.length < 35 || cleaned.length > 220) continue;
    if (_numberedClauseToken.hasMatch(cleaned)) continue;
    if (_isIncompleteSupplement(cleaned)) continue;
    final mentionCount = _sentenceMentionsConcepts(cleaned, concepts);
    if (mentionCount == 0) continue;
    final score = mentionCount * 10 + (cleaned.length > 160 ? 160 : cleaned.length);
    if (bestScore == null || score > bestScore) {
      bestScore = score;
      bestSentence = cleaned;
    }
  }

  if (bestSentence != null) {
    final adapted =
        trimSummaryLength(bestSentence, maxChars: 180).replaceAll(RegExp(r'\.$'), '');
    final wrapped = _wrapSupplementClause(adapted);
    if (wrapped != null) return wrapped;
  }

  final remaining =
      concepts.where((concept) => !usedConcepts.contains(concept)).toList();
  if (remaining.isNotEmpty) {
    return 'It also covers ${_formatConceptList(remaining.take(3).toList())}.';
  }
  return null;
}

String buildStudentFriendlySummary(
  String content, {
  String? title,
  String? documentType,
}) {
  final titleClean = (title ?? '').replaceAll(RegExp(r'\s+'), ' ').trim();
  final kind = _detectArticleKind(content, documentType: documentType);
  final concepts = _prioritizeConcepts(_extractKeyConcepts(content), kind);
  final articleRef =
      titleClean.isNotEmpty ? 'The $titleClean article' : 'This article';
  final topicPhrase =
      titleClean.isNotEmpty ? _titleSummaryPhrase(titleClean, kind) : 'explains the main topic';
  final composedSupplement =
      _composeComparisonNote(content) ?? _composeReferralNote(content);
  final primaryConcepts =
      concepts.take(composedSupplement != null ? 2 : 4).toList();
  final usedConcepts = List<String>.from(primaryConcepts);

  late final String first;
  if (kind == 'requirement') {
    first = primaryConcepts.isNotEmpty
        ? '$articleRef $topicPhrase and '
            'the key requirements involved, including ${_formatConceptList(primaryConcepts)}.'
        : '$articleRef $topicPhrase and '
            'the information students need to provide.';
  } else if (kind == 'procedure') {
    first = primaryConcepts.isNotEmpty
        ? '$articleRef $topicPhrase, including '
            '${_formatConceptList(primaryConcepts)}.'
        : '$articleRef explains the main steps students should follow '
            'based on the source document.';
  } else if (primaryConcepts.isNotEmpty) {
    first = '$articleRef $topicPhrase and what students can learn about '
        '${_formatConceptList(primaryConcepts.take(3).toList())}.';
  } else if (titleClean.isNotEmpty) {
    if (kind == 'requirement' || kind == 'procedure') {
      first =
          'This article explains the requirements and related instructions for $titleClean.';
    } else if (kind == 'policy') {
      first =
          'This article explains the policy on $titleClean and the conditions students should be aware of.';
    } else {
      first =
          'This article provides information about $titleClean based on the uploaded source document.';
    }
  } else {
    first = 'This article provides information based on the uploaded source document.';
  }

  final sentences = <String>[_simplifyAwkwardPhrases(first)];
  final supplement = _pickSupplementSentence(content, concepts, usedConcepts);
  if (supplement != null &&
      sentences.length < 2 &&
      (_isComposedSupplement(supplement) ||
          sentences.first.length + supplement.length + 1 < content.length)) {
    sentences.add(_simplifyAwkwardPhrases(supplement));
  }

  var summary = trimSummaryLength(sentences.take(2).join(' '));
  if (_tooSimilarToOpening(summary, content)) {
    if (kind == 'procedure' && primaryConcepts.isNotEmpty) {
      summary = trimSummaryLength(
        '$articleRef $topicPhrase, including '
        '${_formatConceptList(primaryConcepts)}.',
      );
    } else if (titleClean.isNotEmpty) {
      summary = trimSummaryLength(
        'This article provides information about $titleClean '
        'based on the uploaded source document.',
      );
    }
  }
  return _ensureShorterThanContent(summary, content);
}

String firstSentences(String text, {int maxSentences = 2}) {
  final parts = splitArticleSentences(text);
  if (parts.isEmpty) return text.trim();
  if (parts.length <= maxSentences) {
    return parts.join(' ');
  }
  return parts.take(maxSentences).join(' ').trim();
}

String buildShortSummary(
  String? summary,
  String content, {
  String? title,
  String? documentType,
  bool consolidatedParent = false,
}) {
  final cleanedContent = cleanArticleContentForDisplay(content);
  final summaryText = (summary ?? '').trim();
  final titleText = (title ?? '').trim();

  if (consolidatedParent && titleText.isNotEmpty) {
    return 'This article provides an overview of $titleText based on the uploaded source document.';
  }

  if (summaryText.isEmpty && cleanedContent.isEmpty) {
    return '';
  }

  if (summaryText.isNotEmpty &&
      cleanedContent.isNotEmpty &&
      !summariesOverlap(summaryText, cleanedContent)) {
    var short = firstSentences(summaryText);
    short = stripLeadingNumberedClause(short);
    short = trimSummaryLength(short);
    if (containsNumberedClause(short) &&
        title != null &&
        title.trim().isNotEmpty) {
      return 'This article discusses ${title.trim()} based on the uploaded source document.';
    }
    return short;
  }

  if (cleanedContent.isNotEmpty) {
    var short = buildStudentFriendlySummary(
      cleanedContent,
      title: title,
      documentType: documentType,
    );
    if (short.isEmpty || summariesOverlap(short, cleanedContent)) {
      short = extractiveArticleSummary(cleanedContent);
    }
    if (normalizeArticleText(short) == normalizeArticleText(cleanedContent)) {
      short = buildStudentFriendlySummary(
        cleanedContent,
        title: title,
        documentType: documentType,
      );
      if (short.isEmpty) {
        final sentences = splitArticleSentences(cleanedContent);
        if (sentences.isNotEmpty) {
          short = trimSummaryLength(stripLeadingNumberedClause(sentences.first));
        }
      }
    }
    if (_tooSimilarToOpening(short, cleanedContent)) {
      final rebuilt = buildStudentFriendlySummary(
        cleanedContent,
        title: title,
        documentType: documentType,
      );
      if (rebuilt.isNotEmpty) short = rebuilt;
    }
    if (containsNumberedClause(short) &&
        title != null &&
        title.trim().isNotEmpty) {
      return 'This article discusses ${title.trim()} based on the uploaded source document.';
    }
    return _ensureShorterThanContent(short, cleanedContent);
  }

  var short = trimSummaryLength(
    stripLeadingNumberedClause(firstSentences(summaryText)),
  );
  if (containsNumberedClause(short) &&
      title != null &&
      title.trim().isNotEmpty) {
    return 'This article discusses ${title.trim()} based on the uploaded source document.';
  }
  return short;
}

String resolveSourceFilename(
  AdminArticle article, {
  String? fallbackFilename,
}) {
  final fromField = (article.sourceFilename ?? '').trim();
  if (fromField.isNotEmpty) return fromField;

  final fromMeta = (article.metadata['source_filename'] ??
          article.metadata['source_document'])
      ?.toString()
      .trim();
  if (fromMeta != null && fromMeta.isNotEmpty) return fromMeta;

  final fallback = (fallbackFilename ?? '').trim();
  if (fallback.isNotEmpty) return fallback;

  return 'Not specified';
}

String displayOffice(String? office) {
  final value = (office ?? '').trim();
  return value.isEmpty ? 'Not specified' : value;
}

String displaySourceSection(String? section) {
  final value = (section ?? '').trim();
  return value.isEmpty ? 'Not specified' : value;
}

List<String> readSourceSections(AdminArticle article) {
  final fromMetadata = _readStringList(article.metadata['source_sections']);
  if (fromMetadata.isNotEmpty) return fromMetadata;
  final primary = (article.sourceSection ?? '').trim();
  if (primary.contains(';')) {
    return primary
        .split(';')
        .map((part) => part.trim())
        .where((part) => part.isNotEmpty)
        .toList();
  }
  return primary.isEmpty ? const [] : [primary];
}

String displaySourceSectionForCard(AdminArticle article) {
  final sections = readSourceSections(article);
  if (sections.length > 1) {
    return '${sections.length} merged source sections';
  }
  if (sections.length == 1) {
    return sections.first;
  }
  return displaySourceSection(article.sourceSection);
}

String displaySourceSectionsForView(AdminArticle article) {
  final sections = readSourceSections(article);
  if (sections.length > 1) {
    return sections.join('\n');
  }
  return displaySourceSection(article.sourceSection);
}

const Set<String> formattedArticleSectionHeadings = {
  'overview',
  'process',
  'process / steps',
  'important notes',
  'requirements',
  'instructions / how to submit',
  'instructions',
  'how to submit',
  'notes',
  'key points',
  'important reminders',
  'eligibility / conditions',
  'roles and responsibilities',
  'details',
  'purpose',
  'when to use',
  'how to fill out',
  'related service / office',
  'source',
};

bool isFormattedArticleSectionHeading(String line) {
  final normalized = line.trim().toLowerCase();
  if (normalized.isEmpty) return false;
  return formattedArticleSectionHeadings.contains(normalized);
}

bool articleContentStartsAtTop(String content) {
  final display = cleanArticleContentForDisplay(content);
  if (display.isEmpty) return true;
  final firstLine = display.split('\n').map((line) => line.trim()).firstWhere(
        (line) => line.isNotEmpty,
        orElse: () => '',
      );
  return isFormattedArticleSectionHeading(firstLine) || firstLine == 'Overview';
}

bool isNumericOnlyArticleTitle(String? title) {
  final value = (title ?? '').trim();
  if (value.isEmpty) return false;
  return RegExp(r'^\d+(?:\.\d+)*\.?$').hasMatch(value);
}

double? _readDouble(dynamic value) {
  if (value is num) return value.toDouble();
  return double.tryParse(value?.toString() ?? '');
}

int? _readInt(dynamic value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse(value?.toString() ?? '');
}

List<String> _readStringList(dynamic value) {
  if (value is List) {
    return value.map((item) => item.toString()).where((item) => item.isNotEmpty).toList();
  }
  if (value == null) return const [];
  final text = value.toString().trim();
  return text.isEmpty ? const [] : [text];
}

class AdminArticleRequestException implements Exception {
  AdminArticleRequestException({
    required this.message,
    this.statusCode,
    this.responseBody,
    this.conflictDetail,
  });

  final String message;
  final int? statusCode;
  final String? responseBody;
  final Map<String, dynamic>? conflictDetail;

  bool get isSimilarArticleConflict =>
      statusCode == 409 &&
      (conflictDetail?['code']?.toString() == 'similar_article_exists');

  Map<String, dynamic>? get existingArticle {
    final existing = conflictDetail?['existing'];
    if (existing is Map) {
      return Map<String, dynamic>.from(existing);
    }
    return null;
  }

  @override
  String toString() {
    final buffer = StringBuffer(message);
    if (statusCode != null) {
      buffer.write(' (HTTP $statusCode)');
    }
    if (responseBody != null && responseBody!.trim().isNotEmpty) {
      buffer.write('\n$responseBody');
    }
    return buffer.toString();
  }
}
