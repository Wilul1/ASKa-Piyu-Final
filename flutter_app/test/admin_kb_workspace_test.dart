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
    expect(joined, contains('UNIT 1 / 2'));
    expect(joined, contains('Foreword'));
    expect(joined, contains('Welcome to the handbook.'));
    expect(joined, contains('Admission'));
    expect(joined, contains('Admission requirements apply.'));
  });

  test('buildKnowledgeUnitsExtractionTxt writes all units in one file', () {
    final txt = buildKnowledgeUnitsExtractionTxt(
      sourceFilename: 'Citizen-Charter.pdf',
      knowledgeUnits: [
        {
          'unit_index': 0,
          'title': 'Issuance of TOR',
          'hierarchy_path': 'Registrar > TOR',
          'content_type': 'service_procedure',
          'status': 'OK',
          'page_start': 12,
          'page_end': 13,
          'content': 'Fees: P75.00/page; P150/page',
          'metadata': {
            'office': 'Registrar',
            'total_fees': 'P75.00/page; P150/page',
          },
        },
        {
          'unit_index': 1,
          'title': 'Diploma',
          'content': 'Second copy fee P100.00',
        },
      ],
    );

    expect(txt, contains('Source: Citizen-Charter.pdf'));
    expect(txt, contains('Total units: 2'));
    expect(txt, contains('UNIT 1 / 2'));
    expect(txt, contains('UNIT 2 / 2'));
    expect(txt, contains('title: Issuance of TOR'));
    expect(txt, contains('office: Registrar'));
    expect(txt, contains('total_fees: P75.00/page; P150/page'));
    expect(txt, contains('Fees: P75.00/page; P150/page'));
    expect(txt, contains('title: Diploma'));
    expect(txt, contains('Second copy fee P100.00'));
  });
}
