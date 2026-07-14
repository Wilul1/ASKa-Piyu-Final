import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:aska_piyu/models/admin_article_models.dart';
import 'package:aska_piyu/widgets/admin_article_preview_export.dart';

void main() {
  test('Generate Articles action buttons are text-only', () {
    final shared =
        File('lib/widgets/admin_kb_article_shared.dart').readAsStringSync();
    expect(shared.contains("child: const Text('View')"), isTrue);
    expect(shared.contains("child: Text(editLabel)"), isTrue);
    expect(shared.contains("child: const Text('Save as Draft')"), isTrue);
    expect(shared.contains("child: const Text('Publish')"), isTrue);
    expect(shared.contains("child: const Text('Discard')"), isTrue);
    expect(shared.contains('OutlinedButton.icon('), isFalse);
    expect(shared.contains('ElevatedButton.icon('), isFalse);
    expect(shared.contains('TextButton.icon('), isFalse);
  });

  test('Generate Articles supports safe bulk publish selection', () {
    final section = File('lib/screens/admin_kb_generate_articles_section.dart')
        .readAsStringSync();
    final shared =
        File('lib/widgets/admin_kb_article_shared.dart').readAsStringSync();
    expect(section, contains("bulkPublishAllLabel: 'Publish All Recommended'"));
    expect(section, contains('allowBulkPublish: false'));
    expect(shared, contains('Save Selected as Draft'));
    expect(shared, contains('Publish Selected'));
    expect(shared, contains('Publish selected articles?'));
    expect(shared, contains('bulkPublish'));
    expect(shared, contains('bulkSaveDraft'));
  });

  test('Low Quality section exposes Edit as Review Draft but never Publish', () {
    final section = File('lib/screens/admin_kb_generate_articles_section.dart')
        .readAsStringSync();
    final shared =
        File('lib/widgets/admin_kb_article_shared.dart').readAsStringSync();

    expect(section, contains("'Low Quality / Cleanup'"));
    expect(section, contains('allowEditAsReviewDraft: true'));
    expect(section, contains('allowPublish: false'));
    expect(section, contains('allowBulkPublish: false'));
    expect(section, contains('allowSaveDraft: true'));
    expect(
      section,
      contains(
        'This article can be manually corrected and saved as a review draft before publishing.',
      ),
    );
    expect(shared, contains('Edit as Review Draft'));
    expect(shared, contains('Not recommended for direct publishing'));
    expect(shared, contains('Needs Cleanup'));
    expect(shared, contains('stampManualReviewFromLowQuality'));

    // Recommended / Needs Review still have their own publish/save gates.
    expect(section, contains("bulkPublishAllLabel: 'Publish All Recommended'"));
    expect(section, contains("'Needs Review'"));
    expect(
      section.indexOf("'Recommended Articles'"),
      lessThan(section.indexOf("'Low Quality / Cleanup'")),
    );
  });

  test('stampManualReviewFromLowQuality embeds recovery metadata', () {
    final article = AdminArticle(
      id: 'preview-lq-1',
      title: 'Routine Medical',
      category: 'Student Services',
      published: false,
      summary: 'Clinic',
      content:
          'Office\nNot specified\n\n----EXTRACTED METADATA----\n'
          '{"planner_bucket":"low_quality","source_section":"Clinic","document_type":"citizen_charter","article_type":"procedure"}',
      office: 'University Clinic',
      sourceFilename: 'charter.pdf',
      metadata: const {
        'planner_bucket': 'low_quality',
        'source_section': 'Clinic',
        'document_type': 'citizen_charter',
        'article_type': 'procedure',
      },
      displayContent: 'Office\nNot specified',
    );

    final stamped = stampManualReviewFromLowQuality(article);
    expect(stamped.published, isFalse);
    expect(stamped.metadata['manual_review_from_low_quality'], isTrue);
    expect(stamped.metadata['original_bucket'], 'low_quality');
    expect(stamped.metadata['review_status'], 'manually_corrected_draft');
    expect(stamped.metadata['planner_bucket'], 'needs_review');
    expect(stamped.sourceFilename, 'charter.pdf');
    expect(stamped.sourceSection, 'Clinic');

    final payload = stamped.toCreatePayload(publish: false);
    expect(payload['publish_status'], isFalse);
    expect(payload['planner_bucket'], 'needs_review');
    expect(payload['source_document'], 'charter.pdf');
    final content = payload['content'] as String;
    expect(content, contains('manual_review_from_low_quality'));
    expect(content, contains('manually_corrected_draft'));

    expect(
      shouldBlockCharterPublish(
        title: article.title,
        plannerBucket: 'low_quality',
      ),
      isTrue,
    );
  });
}
