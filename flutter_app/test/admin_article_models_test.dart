import 'package:flutter_test/flutter_test.dart';
import 'package:aska_piyu/models/admin_article_models.dart';
import 'package:aska_piyu/widgets/admin_article_preview_export.dart';

void main() {
  test('parses metadata block and strips it from display content', () {
    final article = AdminArticle.fromJson({
      'id': '1',
      'title': 'Admission Requirements',
      'category': 'Admissions',
      'published': false,
      'content':
          'Students must submit documents.\n\n----EXTRACTED METADATA----\n{"quality_score":8.5,"category_confidence":0.8,"student_usefulness_score":1.5,"needs_review":false,"review_reason":[],"document_type":"handbook_policy","source_section":"Admissions"}',
    });

    expect(article.displayContent, 'Students must submit documents.');
    expect(article.qualityScore, 8.5);
    expect(article.categoryConfidence, 0.8);
    expect(article.studentUsefulnessScore, 1.5);
    expect(article.documentType, 'handbook_policy');
    expect(article.reviewBucket, ArticleReviewBucket.recommended);
  });

  test('candidate generation result reads grouped summaries', () {
    final result = CandidateGenerationResult.fromJson({
      'total_detected': 3,
      'recommended_count': 1,
      'overflow_count': 1,
      'skipped_low_quality_count': 1,
      'skipped_duplicate_count': 0,
      'needs_review_count': 1,
      'created_count': 2,
      'preview_count': 3,
      'recommended_candidates': [
        {'title': 'Admission Requirements', 'quality_score': 8.0, 'id': 'preview-1'},
      ],
      'low_confidence_candidates': [
        {'title': 'Overview', 'quality_score': 1.0, 'id': 'preview-2'},
      ],
      'all_candidates': [
        {'title': 'Admission Requirements', 'quality_score': 8.0, 'id': 'preview-1'},
        {'title': 'Overview', 'quality_score': 1.0, 'id': 'preview-2'},
        {'title': 'Campus Map', 'quality_score': 6.0, 'id': 'preview-3'},
      ],
      'grouped_candidates': [
        {
          'group_name': 'Registrar',
          'group_type': 'office',
          'total_count': 2,
          'recommended_count': 1,
          'needs_review_count': 0,
          'low_confidence_count': 1,
          'duplicate_count': 0,
          'candidates': [
            {'title': 'Admission Requirements', 'id': 'preview-1', 'group_name': 'Registrar'},
            {'title': 'Overview', 'id': 'preview-2', 'group_name': 'Registrar'},
          ],
        },
      ],
    });

    expect(result.totalDetected, 3);
    expect(result.previewCount, 3);
    expect(result.recommendedCandidates.first.title, 'Admission Requirements');
    expect(result.lowConfidenceCandidates.first.title, 'Overview');
    expect(result.allCandidates.length, 3);
    expect(result.groupedCandidates.length, 1);
    expect(result.groupedCandidates.first.groupName, 'Registrar');
    expect(result.groupedCandidates.first.candidates.length, 2);
  });

  test('candidate generation result parses citizen charter report', () {
    final result = CandidateGenerationResult.fromJson({
      'total_detected': 12,
      'recommended_count': 4,
      'overflow_count': 0,
      'skipped_low_quality_count': 3,
      'skipped_duplicate_count': 0,
      'needs_review_count': 2,
      'created_count': 6,
      'preview_count': 6,
      'charter_report': {
        'document_type': 'citizen_charter',
        'document_profile': 'citizen_charter',
        'parser_used': 'citizen_charter_service_parser',
        'review_text_length': 12000,
        'knowledge_units_count': 247,
        'total_detected_service_blocks': 20,
        'valid_service_blocks': 9,
        'merged_split_services': 3,
        'rejected_artifact_headings': 7,
        'rejected_mixed_service_blocks': 2,
        'rejected_incomplete_blocks': 3,
        'recommended_services': 4,
        'needs_review_services': 2,
        'low_quality_artifacts_dropped': 8,
        'rag_only_references': 2,
        'generated_article_candidates': 14,
      },
      'recommended_candidates': [],
      'all_candidates': [],
    });

    expect(result.charterReport, isNotNull);
    expect(result.charterReport!.documentProfile, 'citizen_charter');
    expect(result.charterReport!.parserUsed, 'citizen_charter_service_parser');
    expect(result.charterReport!.reviewTextLength, 12000);
    expect(result.charterReport!.knowledgeUnitsCount, 247);
    expect(result.charterReport!.totalDetectedServiceBlocks, 20);
    expect(result.charterReport!.validServiceBlocks, 9);
    expect(result.charterReport!.mergedSplitServices, 3);
    expect(result.charterReport!.rejectedArtifactHeadings, 7);
    expect(result.charterReport!.rejectedMixedServiceBlocks, 2);
    expect(result.charterReport!.rejectedIncompleteBlocks, 3);
    expect(result.charterReport!.recommendedServices, 4);
    expect(result.charterReport!.needsReviewServices, 2);
    expect(result.charterReport!.lowQualityArtifactsDropped, 8);
    expect(result.charterReport!.ragOnlyReferences, 2);
    expect(result.charterReport!.generatedArticleCandidates, 14);
    expect(result.charterReport!.rescueAttempted, 0);
    expect(result.charterReport!.rescueSuccessful, 0);
  });

  test('charter report parses rescue counts', () {
    final result = CandidateGenerationResult.fromJson({
      'total_detected': 1,
      'recommended_count': 0,
      'overflow_count': 0,
      'skipped_low_quality_count': 0,
      'skipped_duplicate_count': 0,
      'needs_review_count': 1,
      'created_count': 0,
      'charter_report': {
        'document_type': 'citizen_charter',
        'v2_services_detected': 12,
        'rescue_attempted': 10,
        'rescue_successful': 3,
        'promoted_to_recommended_after_repair': 2,
        'downgraded_after_semantic_validation': 1,
        'internal_services_kept_as_needs_review_or_rag_only': 4,
        'true_low_quality_fragments': 3,
        'total_detected_service_blocks': 12,
        'merged_split_services': 0,
        'recommended_services': 2,
        'needs_review_services': 5,
        'low_quality_artifacts_dropped': 3,
        'rag_only_references': 2,
      },
      'recommended_candidates': [],
      'all_candidates': [],
    });

    expect(result.charterReport!.v2ServicesDetected, 12);
    expect(result.charterReport!.rescueAttempted, 10);
    expect(result.charterReport!.rescueSuccessful, 3);
    expect(result.charterReport!.promotedToRecommendedAfterRepair, 2);
    expect(result.charterReport!.downgradedAfterSemanticValidation, 1);
    expect(result.charterReport!.internalServicesKeptAsNeedsReviewOrRagOnly, 4);
    expect(result.charterReport!.trueLowQualityFragments, 3);
    expect(result.charterReport!.repairedButNotPromoted, 0);
  });

  test('charter report parses public priority chips and coverage fields', () {
    final result = CandidateGenerationResult.fromJson({
      'total_detected': 1,
      'recommended_count': 1,
      'overflow_count': 0,
      'skipped_low_quality_count': 0,
      'skipped_duplicate_count': 0,
      'needs_review_count': 0,
      'created_count': 0,
      'charter_report': {
        'document_type': 'citizen_charter',
        'total_detected_service_blocks': 2,
        'merged_split_services': 0,
        'recommended_services': 1,
        'needs_review_services': 1,
        'low_quality_artifacts_dropped': 0,
        'rag_only_references': 0,
        'public_priority_found': 5,
        'public_priority_recommended': 2,
        'public_priority_needs_review': 2,
        'public_priority_low_quality': 0,
        'public_priority_repaired': 3,
        'public_priority_blocked_by_article_body': 1,
        'priority_service_diagnostics': [
          {
            'title': 'ID Validation',
            'found': true,
            'final_bucket': 'recommended',
            'publish_allowed': true,
            'main_failed_field': null,
            'next_repair_target': null,
            'suggested_bucket_after_repair': 'recommended',
            'body_has_needs_review': false,
            'article_body_status': 'clean',
            'body_rebuilt_from_detected_fields': true,
            'required_step_count_met': true,
            'publish_safety_state': 'published',
            'already_published_match': true,
            'rendered_step_count': 3,
            'detected_step_count': 3,
            'detected_requirement_count': 2,
            'total_processing_time_detected': true,
            'is_public_priority': true,
          },
        ],
      },
      'recommended_candidates': [],
      'all_candidates': [],
    });

    final report = result.charterReport!;
    expect(report.publicPriorityFound, 5);
    expect(report.publicPriorityRecommended, 2);
    expect(report.publicPriorityNeedsReview, 2);
    expect(report.publicPriorityLowQuality, 0);
    expect(report.publicPriorityRepaired, 3);
    expect(report.publicPriorityBlockedByArticleBody, 1);
    expect(report.priorityServiceDiagnostics, isNotEmpty);
    expect(report.priorityServiceDiagnostics.first['body_has_needs_review'], isFalse);
    expect(report.priorityServiceDiagnostics.first['detected_requirement_count'], 2);
  });

  test('candidate summary merges rescue needs-review reasons', () {
    final candidate = CandidateSummary.fromJson({
      'id': 'preview-1',
      'title': 'Library Circulation Service',
      'needs_review': true,
      'review_reason': ['uncertain_office'],
      'needs_review_reasons': ['missing total processing time'],
      'remaining_blockers': ['incomplete step row'],
      'rescue_attempted': true,
      'rescue_successful': false,
      'original_bucket': 'needs_review',
      'repaired_bucket': 'needs_review',
      'repair_actions_applied': ['merged_wrapped_step_rows'],
    });

    expect(candidate.rescueAttempted, isTrue);
    expect(candidate.rescueSuccessful, isFalse);
    expect(candidate.displayReviewReasons, contains('missing total processing time'));
    expect(candidate.displayReviewReasons, contains('incomplete step row'));
    expect(candidate.displayReviewReasons, contains('uncertain_office'));
    expect(candidate.repairActionsApplied, ['merged_wrapped_step_rows']);
  });

  test('fromListJson omits article body for lightweight cards', () {
    final article = AdminArticle.fromListJson({
      'id': '2',
      'title': 'Campus Map',
      'category': 'Campus Life',
      'published': false,
      'summary': 'A long summary that should not appear in list cards.',
      'content':
          'Full article body with many paragraphs.\n\n----EXTRACTED METADATA----\n{"quality_score":7.5}',
    });

    expect(article.displayContent, isEmpty);
    expect(article.content, isNull);
    expect(article.hasLoadedContent, isFalse);
    expect(article.qualityScore, 7.5);
  });

  test('buildShortSummary avoids duplicating full content', () {
    const body =
        'Students must submit documents. Late submissions are not accepted. '
        'Contact the registrar for help.';
    final short = buildShortSummary(body, body, title: 'Document Submission');
    expect(short.length, lessThan(body.length));
    expect(short, isNot(equals(body)));
    expect(short, isNot(startsWith('Students must submit documents. Late submissions')));
    expect(short, contains('Document Submission'));
  });

  test('buildShortSummary prefers distinct summary when different', () {
    const summary = 'Quick overview of admission steps.';
    const content = 'Step one: gather documents. Step two: submit online.';
    expect(buildShortSummary(summary, content), summary);
  });

  test('buildShortSummary drops numbered clauses and uses title fallback', () {
    const title = 'Modified Grading Policy';
    const content =
        'The Modified Grading Policy During the pandemic, shall be observed: '
        '4.1. The university will continue using the numerical grading system; '
        '4.2. Additional rules apply.';
    final short = buildShortSummary(null, content, title: title);
    expect(short, isNot(contains('4.1')));
    expect(short, isNot(contains('4.2')));
    expect(short.length, lessThan(content.length));
    expect(short, contains(title));
  });

  test('cleanArticleContentForDisplay fixes OCR hyphen spacing', () {
    const raw =
        'Students must follow the regula- tion on attendance.\n4.1 Late arrivals are recorded.';
    final cleaned = cleanArticleContentForDisplay(raw);
    expect(cleaned, contains('regulation'));
    expect(cleaned, isNot(contains('regula- tion')));
    expect(cleaned, contains('4.1 Late arrivals are recorded.'));
  });

  test('cleanArticleContentForDisplay fixes line-break hyphenation', () {
    const raw = 'The univer-\nsity policy applies to all students.';
    expect(
      cleanArticleContentForDisplay(raw),
      'The university policy applies to all students.',
    );
  });

  test('buildShortSummary is shorter than content and not duplicated', () {
    const content =
        'Students must submit complete admission documents before the deadline. '
        'Late submissions may not be processed. Contact the registrar for assistance.';
    final short = buildShortSummary(
      content,
      content,
      title: 'Admission Requirements',
      documentType: 'requirement',
    );
    expect(short.length, lessThan(content.length));
    expect(normalizeArticleText(short), isNot(normalizeArticleText(content)));
    expect(short.split('.').where((part) => part.trim().isNotEmpty).length, lessThanOrEqualTo(2));
  });

  test('buildShortSummary counseling process is student friendly', () {
    const title = 'Counseling Process';
    const content =
        'This phase focuses on the counseling process per se. '
        'The process does not differ from a face-to-face counseling session. '
        'Virtual counseling sessions use video conference technology. '
        'Students may receive follow-up after consultation. '
        'Referral to other offices may be recommended when needed.';
    final short = buildShortSummary(
      content,
      content,
      title: title,
      documentType: 'procedure',
    );

    expect(short, isNot(contains('per se')));
    expect(short, isNot(contains('This phase focuses on the counseling process')));
    expect(short.length, lessThan(content.length));
    expect(short, contains(title));
    expect(short.toLowerCase(), contains('follow-up'));
    expect(short.toLowerCase(), contains('referral'));
    expect(
      short.toLowerCase(),
      anyOf(contains('virtual counseling'), contains('face-to-face counseling')),
    );
    expect(short.split('.').where((part) => part.trim().isNotEmpty).length, lessThanOrEqualTo(2));
  });

  test('buildShortSummary services title uses natural grammar', () {
    const title = 'Guidance and Counseling Services';
    const content =
        'Guidance and counseling services include individual and group counseling. '
        'Case conference may be done when needed. '
        'Students may be refer if necessary to counseling professors. '
        'Follow-up counselee with cases is part of the service.';

    final short = buildShortSummary(
      content,
      content,
      title: title,
      documentType: 'procedure',
    );

    final lowered = short.toLowerCase();
    expect(lowered, isNot(contains('services works')));
    expect(lowered, isNot(contains('follow-up counselee with cases')));
    expect(lowered, isNot(contains('case conference may')));
    expect(lowered, isNot(contains('refer if necessary')));
    expect(
      lowered,
      anyOf(contains('support provided'), contains('services')),
    );
    expect(
      lowered,
      anyOf(contains('case conferences'), contains('referral')),
    );
    expect(short.split('.').where((part) => part.trim().isNotEmpty).length, lessThanOrEqualTo(2));
  });

  test('buildShortSummary multidisciplinary referral note is natural', () {
    const title = 'Guidance and Counseling Services';
    const content =
        'Guidance and counseling services include individual and group counseling. '
        'Case conference may be done when needed. '
        'Follow-up counselee with cases and refer if necessary to multidisciplinary team '
        'of specialists to ensure that special needs of students are met.';

    final short = buildShortSummary(
      content,
      content,
      title: title,
      documentType: 'procedure',
    );

    final lowered = short.toLowerCase();
    expect(lowered, isNot(contains('referrals when needed to multidisciplinary team')));
    expect(lowered, contains('a multidisciplinary team'));
    expect(
      lowered,
      anyOf(
        contains('students may be referred'),
        contains('referrals to a multidisciplinary team'),
      ),
    );
    expect(short.split('.').where((part) => part.trim().isNotEmpty).length, lessThanOrEqualTo(2));
    expect(short.length, lessThan(content.length));
  });

  test('resolveSourceFilename falls back to metadata and upload name', () {
    final fromMeta = AdminArticle.fromJson({
      'id': '3',
      'title': 'Policy',
      'category': 'Policies',
      'published': false,
      'content':
          'Body text.\n\n----EXTRACTED METADATA----\n{"source_filename":"handbook.pdf"}',
    });
    expect(resolveSourceFilename(fromMeta), 'handbook.pdf');

    final missing = AdminArticle.fromListJson({
      'id': '4',
      'title': 'Policy',
      'category': 'Policies',
      'published': false,
    });
    expect(
      resolveSourceFilename(missing, fallbackFilename: 'uploaded.pdf'),
      'uploaded.pdf',
    );
    expect(resolveSourceFilename(missing), 'Not specified');
  });

  test('displayOffice shows Not specified when empty', () {
    expect(displayOffice(null), 'Not specified');
    expect(displayOffice(''), 'Not specified');
    expect(displayOffice('Registrar'), 'Registrar');
  });

  test('preview candidate ids are detected and converted to articles', () {
    expect(isPreviewCandidateId('preview-123'), isTrue);
    expect(isPreviewCandidateId('db-uuid'), isFalse);

    final candidate = CandidateSummary.fromJson({
      'id': 'preview-abc',
      'title': 'Admission Requirements',
      'category': 'Admissions',
      'summary': 'Short summary',
      'content': 'Body text',
      'is_preview': true,
      'quality_score': 8.0,
    });
    expect(candidate.isUnsavedPreview, isTrue);
    final article = candidate.toPreviewArticle();
    expect(article.title, 'Admission Requirements');
    expect(article.hasLoadedContent, isTrue);
  });

  test('request exception includes status and response body', () {
    final error = AdminArticleRequestException(
      message: 'Request failed with status 500',
      statusCode: 500,
      responseBody: '{"detail":"database unavailable"}',
    );
    expect(error.toString(), contains('HTTP 500'));
    expect(error.toString(), contains('database unavailable'));
  });

  test('buildShortSummary avoids weak covered in source document fallback', () {
    final summary = buildShortSummary(
      null,
      'General information about campus services and student support resources.',
      title: 'Student Services',
      documentType: 'information',
    );
    expect(summary.toLowerCase(), isNot(contains('covered in the source document')));
    expect(summary, contains('Student Services'));
  });

  test('coverage topic reads source section and reason', () {
    final topic = CoverageTopic.fromJson({
      'parent_topic': 'Front Matter',
      'canonical_topic': 'Foreword',
      'unit_count': 2,
      'status': 'rag_only',
      'source_section': 'Front Matter > Foreword',
      'reason': 'RAG-only',
    });
    expect(topic.sourceSection, 'Front Matter > Foreword');
    expect(topic.reason, 'RAG-only');
  });

  test('displaySourceSectionForCard collapses merged sections', () {
    final article = AdminArticle(
      id: 'preview-1',
      title: 'Admission Requirements',
      category: 'Admissions',
      published: false,
      metadata: {
        'source_sections': [
          'Admissions > Requirements > A',
          'Admissions > Requirements > B',
          'Admissions > Requirements > C',
        ],
      },
    );
    expect(
      displaySourceSectionForCard(article),
      '3 merged source sections',
    );
    expect(
      displaySourceSectionsForView(article),
      contains('Admissions > Requirements > A'),
    );
  });

  test('isNumericOnlyArticleTitle detects numeric section labels', () {
    expect(isNumericOnlyArticleTitle('1.1'), isTrue);
    expect(isNumericOnlyArticleTitle('4.2'), isTrue);
    expect(isNumericOnlyArticleTitle('Graduation Requirements'), isFalse);
  });

  test('buildShortSummary uses overview wording for consolidated parents', () {
    final summary = buildShortSummary(
      'Long merged child content. ' * 20,
      'Long merged child content. ' * 20,
      title: 'Graduation Requirements',
      consolidatedParent: true,
    );
    expect(
      summary,
      'This article provides an overview of Graduation Requirements based on the uploaded source document.',
    );
  });

  test('candidate generation result reads planner buckets without max candidates field', () {
    final result = CandidateGenerationResult.fromJson({
      'total_detected': 12,
      'blueprint_count': 8,
      'preview_count': 8,
      'recommended_count': 3,
      'consolidated_parent_count': 2,
      'needs_review_count': 2,
      'skipped_low_quality_count': 1,
      'rag_only_count': 4,
      'created_count': 8,
      'recommended_candidates': [
        {'title': 'Admission Requirements', 'planner_bucket': 'recommended', 'id': 'preview-1'},
      ],
      'consolidated_parent_candidates': [
        {'title': 'Graduation Requirements', 'planner_bucket': 'consolidated_parent', 'id': 'preview-2'},
      ],
      'needs_review_candidates': [
        {'title': 'Policy Review', 'planner_bucket': 'needs_review', 'id': 'preview-3'},
      ],
      'low_confidence_candidates': [
        {'title': 'Overview', 'planner_bucket': 'low_quality', 'id': 'preview-4'},
      ],
      'all_candidates': [
        {'title': 'Admission Requirements', 'planner_bucket': 'recommended', 'id': 'preview-1'},
        {'title': 'Graduation Requirements', 'planner_bucket': 'consolidated_parent', 'id': 'preview-2'},
        {'title': 'Policy Review', 'planner_bucket': 'needs_review', 'id': 'preview-3'},
        {'title': 'Overview', 'planner_bucket': 'low_quality', 'id': 'preview-4'},
      ],
      'coverage': [
        {
          'parent_topic': 'Front Matter',
          'canonical_topic': 'Foreword',
          'unit_count': 2,
          'status': 'rag_only',
        },
      ],
      'coverage_counts': {
        'generated': 3,
        'merged_parent': 2,
        'needs_review': 2,
        'needs_cleanup': 1,
        'rag_only': 4,
      },
    });

    expect(result.recommendedCandidates, hasLength(1));
    expect(result.consolidatedParentCandidates, hasLength(1));
    expect(result.needsReviewCandidates, hasLength(1));
    expect(result.lowConfidenceCandidates, hasLength(1));
    expect(result.coverageCounts['generated'], 3);
    expect(result.coverageCounts['rag_only'], 4);
  });

  test('officialSourceExcerpt is parsed from metadata', () {
    const excerpt =
        'This phase focuses on the counseling process per se. 3.1. Conference text.';
    final article = AdminArticle.fromJson({
      'id': '5',
      'title': 'Counseling Process',
      'category': 'Student Services',
      'published': false,
      'content':
          'Overview\nProcess steps.\n\n----EXTRACTED METADATA----\n{"official_source_excerpt":"$excerpt","document_type":"procedure"}',
    });

    expect(article.officialSourceExcerpt, excerpt);
    expect(article.displayContent, contains('Overview'));
    expect(article.displayContent, isNot(contains('3.1')));
    expect(isFormattedArticleSectionHeading('Overview'), isTrue);
    expect(isFormattedArticleSectionHeading('Process / Steps'), isTrue);
    expect(isFormattedArticleSectionHeading('Eligibility / Conditions'), isTrue);
    expect(isFormattedArticleSectionHeading('Roles and Responsibilities'), isTrue);
    expect(isFormattedArticleSectionHeading('Random paragraph'), isFalse);
    expect(
      articleContentStartsAtTop('Overview\nThis article explains the process.'),
      isTrue,
    );
  });

  test('download TXT helpers build safe filename and export body', () {
    final article = AdminArticle.fromJson({
      'id': 'preview-id-validation',
      'title': 'ID Validation',
      'category': 'Student Services',
      'published': false,
      'summary': 'How students validate their ID.',
      'source_filename': 'citizen-charter.pdf',
      'content':
          'Overview\nBring your COR.\n\n----EXTRACTED METADATA----\n'
          '{"planner_bucket":"recommended","source_section":"Student Services > ID Validation",'
          '"source_document_id":"doc-1","page":12,"official_source_excerpt":"Office or Division: OSAS",'
          '"quality_score":8.5,"category_confidence":0.9,"student_usefulness_score":2.0,'
          '"document_type":"procedure","review_reason":[]}',
    });

    expect(
      safePreviewFilename(title: 'ID Validation', bucketLabel: 'Recommended'),
      'aska_piyu_article_preview_id_validation_recommended.txt',
    );
    expect(
      safePreviewFilename(title: 'Classification: Simple', bucketLabel: 'Low Quality'),
      'aska_piyu_article_preview_classification_simple_low_quality.txt',
    );

    final text = buildArticlePreviewTxt(
      article: article,
      bucketLabel: 'Recommended',
    );
    expect(text, contains('Title:\nID Validation'));
    expect(text, contains('Bucket:\nRecommended'));
    expect(text, contains('Document Profile:'));
    expect(text, contains('Parser Used:'));
    expect(text, contains('Formatter Used:'));
    expect(text, contains('Source File:\ncitizen-charter.pdf'));
    expect(text, contains('Source Section:\nStudent Services > ID Validation'));
    expect(text, contains('Short Summary:\nHow students validate their ID.'));
    expect(text, contains('Article Content:\nOverview'));
    expect(text, contains('Official Source Excerpt:\nOffice or Division: OSAS'));
    expect(text, contains('Metadata:'));

    final low = AdminArticle.fromJson({
      'id': 'preview-class',
      'title': 'Classification: Academic',
      'category': 'General Information',
      'published': false,
      'content':
          'Artifact\n\n----EXTRACTED METADATA----\n'
          '{"planner_bucket":"low_quality","review_reason":["charter_artifact_title"]}',
    });
    final lowText = buildArticlePreviewTxt(
      article: low,
      bucketLabel: 'Low Quality',
    );
    expect(lowText, contains('Review Flags:\ncharter_artifact_title'));
    expect(shouldBlockCharterPublish(title: 'Classification: Academic'), isTrue);
    expect(shouldBlockCharterPublish(title: 'ID Validation'), isFalse);
    expect(isArtifactCharterTitle('4. Classification: Academic'), isTrue);
    expect(isArtifactCharterTitle('Classification of Students'), isFalse);
  });
}
