import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/screens/admin_kb_outline.dart';

void main() {
  test('document outline is derived from knowledge units, not hardcoded', () {
    final outline = buildDocumentOutline([
      {
        'title': 'Excuse Slip',
        'hierarchy_path': 'Academic Policies > Attendance',
        'content': 'Students may request an excuse slip.',
        'page_start': 12,
      },
      {
        'title': 'Counseling',
        'hierarchy_path': 'Student Services > Guidance',
        'content': 'Guidance counseling is available.',
        'page_start': 40,
      },
    ]);

    expect(outline.map((section) => section.title).toList(), [
      'Academic Policies',
      'Student Services',
    ]);
    expect(outline.first.unitCount, 1);
    expect(outline.first.previewText, contains('excuse slip'));
  });

  test('formatDocumentTypeLabel cleans detection maps', () {
    expect(
      formatDocumentTypeLabel({
        'document_type': 'information',
        'reason': 'Manual admin selection.',
        'scores': {},
        'manual_override': true,
      }),
      'Information',
    );
    expect(formatDocumentTypeLabel('procedure'), 'Procedure');
    expect(
      formatDocumentTypeLabel(
        '{document_type: information, reason: Manual admin selection.}',
      ),
      'Information',
    );
  });

  test('formatClassificationReason reads reason field only', () {
    expect(
      formatClassificationReason({
        'document_type': 'information',
        'reason': 'Manual admin selection.',
      }),
      'Manual admin selection.',
    );
    expect(
      formatClassificationReason(
        '{document_type: information, reason: Manual admin selection.}',
      ),
      isNull,
    );
  });

  test('buildFullExtractionText prefers review text then joins units', () {
    expect(
      buildFullExtractionText(
        reviewText: 'Full cleaned handbook text',
        knowledgeUnits: const [],
      ),
      'Full cleaned handbook text',
    );
    final joined = buildFullExtractionText(
      reviewText: '',
      knowledgeUnits: [
        {
          'title': 'Foreword',
          'hierarchy_path': 'Front Matter > Foreword',
          'content': 'Welcome to the handbook.',
        },
        {
          'title': 'Admission',
          'content': 'Admission requirements apply.',
        },
      ],
    );
    expect(joined, contains('Foreword'));
    expect(joined, contains('Welcome to the handbook.'));
    expect(joined, contains('Admission'));
    expect(joined, contains('Admission requirements apply.'));
  });
}
